# emu68hatcher

Cross-platform GUI tool (PySide6) that builds bootable Amiga SD card
images for Emu68/PiStorm. Packages of ADFs, ROMs, Workbench files,
network stacks, etc. get assembled into a PFS3 image written via
`hst-imager`.

## Dev

```bash
python3 bootstrap.py            # creates .venv, pip install -e . (windows: `python bootstrap.py`)
python3 bootstrap.py --dev      # also install pytest + ruff
source .venv/bin/activate
python -m emu68hatcher          # or just: emu68hatcher
```

`bootstrap.py` is the canonical install path (README + docs point at it)
and is the **only** thing that sets `core.hooksPath .githooks`, so a
hand-rolled venv gets no ruff pre-commit gate. Extras are `dev` and
`docs` only — there is no `gui` extra, and an unquoted `.[dev]` is a zsh
glob that fails before pip ever runs. bootstrap sidesteps this by passing
argv to `subprocess.run` with no shell.

ruff: line-length 100, target py310, `E,W,F,I,B,C4,UP`, ignores E501/B008
(`pyproject.toml`). `.githooks/pre-commit` is plain sh, checks staged
`*.py` only.

## Tests

There is no test suite — it was deleted deliberately (net-negative on
time). Don't write or propose tests. The `testpaths` entry in
`pyproject.toml` is vestigial and `tests/` is gitignored.

Nothing but a manual build exercises the pipeline: the GUI is its only
constructor, and there is no CLI driver. Offscreen smoke check:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -c "
from PySide6.QtWidgets import QApplication; app=QApplication([])
from emu68hatcher.gui.main_window import MainWindow"
```

That constructs `StartTab`, which mkdirs `hatcher_data/` as a side effect.

## Build pipeline

Eleven stages, in `workflow.py`. `_finalize_output_move` runs after the
loop, not as a stage.

```
validate → setup_workspace → download → extract → create_image →
install_workbench → install_packages → configure → install_extras →
finalize → flash
```

Ordering constraints that are not obvious:

- **validate is not a pure check.** It acquires `state.elevation`, pushes
  global hst-imager settings, and holds a macOS DiskArbitration claim.
  Every later elevated call reads `state.elevation`. It runs before
  `setup_workspace` on purpose and must not touch the work dirs.
- **setup_workspace is the sole writer** of
  `work_dir/{staging,downloads,extracted,workbench}`.
- **extract → install_packages** is a naming contract: `PackageInstaller`
  looks for sources at exactly `extracted_dir/<pkg.name>`. Miss it and
  every rule for that package installs 0 files with a debug log only.
- **install_workbench → configure**: `configure_scripts` raises
  `BuildError` without `S/Startup-Sequence`, which only ADF extraction
  produces. There is no generated fallback.
- **install_extras is last in staging on purpose** — user files overwrite
  everything before them.
- **finalize deletes** staging/downloads/extracted/workbench. Nothing may
  read them after.
- `_finalize_output_move` only runs on success, so a failed macOS build
  leaves the .img in the temp workdir and the chosen path empty.

### BuildState

Typed dataclass, but every field defaults to `None`/empty, so nothing
forces a stage to populate anything — missing values surface only as
hand-written "may have failed" guards in each consumer.

- `image_path` is `Path | str`. DEVICE mode stores `\\.\PhysicalDriveN`
  as a **str deliberately**; `pathlib` appends a trailing backslash and
  corrupts hst-imager argv. Gate `.exists()`/`.parent` on `OutputType`.
- `state.resolution` is cached build-wide, first caller wins. Mutating
  `config.packages` after that point does nothing.
- Anything a stage creates under `staging_dir/<name>/` is read by
  finalize as an **Amiga RDB device name** and fs-copied into the image.
  A scratch dir there lands on the card or fails the build.

### Progress, cancel, errors

- `state.progress` is always per-stage 0..100. The global bar is computed
  GUI-side from a hardcoded `_STAGE_ORDER` + `_STAGE_NAMES` in
  `build_progress_dialog.py`. A new stage missing from those two lists
  contributes exactly nothing to the bar. flash emits `0.0` as a protocol
  to flip the bar to indeterminate.
- Convention: `_update_state(BuildStage.X, 0.0)` first, then
  `_update_state(progress=100.0)` + `_milestone(...)` last. `_log` sets
  the status label; `_milestone` sets label **and** logs INFO.
  `logger.debug` never reaches the dialog.
- Cancel is checked **between stages only**, after each returns. The
  entire `configure` stage has zero checks, as do `extract_archive` and
  the local-archive loop. `extract_archive` catches bare `Exception`, so
  a cancel raised inside it degrades into a "failed extraction" warning.
- `BuildCancelledError` does **not** subclass `BuildError`. `except
  BuildError` won't swallow a cancel; `except Exception` will.
- `BuildError` → user-facing message with no traceback, so its text must
  be actionable prose. Anything else → `logger.exception` + "Unexpected
  error".
- Warn-and-continue is the norm for content (optional downloads, missing
  ADF for a rule, icon patches). Hard-fail is reserved for mandatory
  downloads, zero ADF files, missing Startup-Sequence, no ID76 partition,
  any partition copy failure. `install_packages` can never fail a build —
  an unknown package logs a warning and returns 0.

## Package model

`data/packages/*.yaml` is the unit of everything: one file per package,
auto-discovered by glob. No registration step, no Python change needed.

- **`name:` must be lowercase.** The resolver lowercases `install_order`,
  but `get_package_by_name` compares exactly — an uppercase name resolves
  and then silently never installs.
- **Failure asymmetry at load.** Broken/invalid YAML is a *silent skip*
  (warning + the package vanishes from the catalogue). A dangling
  `requires:`/`recommends:` token is a *hard ValueError* that aborts
  loading everything. So a syntax error in A makes A disappear quietly
  and then B, which requires A, fails fatally — easy to misdiagnose as a
  bug in B.
- Caches (`_packages_cache`, `_bundles_cache`, `_adf_rules_cache`) are
  module globals with no invalidation. YAML edits need a process restart.
- `group:` — only `System` and `Locale` are load-bearing: both are hidden
  in the GUI tree. `Drivers`/`RTG`/`Commodities`/`Network` are not in
  `PACKAGE_GROUPS` and just sort last.

### install:

- `from:` root is `extracted_dir/<pkg.name>` (falling back to the
  download filename stem, then a case-insensitive match).
- `to:` root is `staging_dir/SDH0`, **not** `System:` as the schema
  comment claims. Resolved case-insensitively; missing components are
  appended unchanged, so whichever rule creates a dir first fixes its
  casing for every later rule.
- `to:` is always the **parent**. A matched directory contributes its own
  name, so `from: X/Plugins` + `to: A/B/` lands at `A/B/Plugins`.
- A `*` anywhere — including in a directory component — takes the glob
  branch, where `recursive:` is ignored (dirs always deep-merge) and
  `rename:` renames every match to the same name (last wins).
- `stack:` patches a BE long at offset 74 only if the file starts `E3 10`.
  Silent no-op otherwise, and never applied to merged trees.
- Nested archives (`from: X.lha/inner/path`) work one level deep only,
  and a `*` *before* the archive component breaks resolution silently.
  The extract dir is reused if it merely exists, so a failed nested
  extraction is never retried in that work dir.
- `ensure_dir(dest)` runs **before** any match check, so a typo'd `from:`
  creates an empty dir on the image, installs nothing, and warns nothing.

### relocate: vs install:

`relocate` moves files already staged by the ADF/OS install; `install`
copies out of an extracted download. Using relocate for a downloaded file
is an info-level skip — no error, no file.

relocate also carries the sibling `.info` and, when `to:` contains
`wbstartup`, forces `DONOTWAIT` or drops in a stock `_tool.info`.
`install:` does none of that, so hand-placing a commodity into WBStartup
via `install:` yields a file Workbench never launches.

### scripts:

Always `ADD` (append to EOF), default target `S/User-Startup`. The
injector always wraps the block in
`;<name> - Added by Emu68 Hatcher - BEGIN/END`.

Adding your own `;BEGIN/;END` inside `content:` is redundant — nothing
parses either set, no code ever removes a block by name, the markers are
purely cosmetic. Six of nine script-carrying YAMLs do it anyway; the
convention is simply inconsistent.

`when_user_archive` gates a variant on whether the user supplied their
own archive. Only roadshow uses it.

### Dependency resolution

- Virtual token = any `provides:` entry; a package implicitly provides
  its own name. Multiple providers resolve by: already-selected >
  requested > mandatory > `default:` > alphabetical.
- Mutual exclusion idiom = same token in **both** `provides` and
  `conflicts` (see mui38/mui5). The conflict test is symmetric, so
  declare it once.
- Conflict losers are pruned over connected components, not cliques. Two
  pairwise-conflicting mandatory packages raise at build time.
- Unsatisfiable `requires` is only a warning at install. A requires-cycle
  warns and installs in arbitrary order.
- `recommends` are currently **unsuppressable**: `resolve_selection`
  always passes `deselected=set()` and the GUI never calls the resolver,
  so unticking a recommended package doesn't drop it if anything
  recommends it.

### adf_rules.yaml

- `mandatory: true` on a *rule* does not mean the package is mandatory —
  it means "ignore the `package:` filter, always include". It is `false`
  everywhere today.
- `sequence:` (default 0) is the only ordering. Omit it and your rule
  runs before everything and gets overwritten. In use: 1 base OS, 2
  updates, 3 icon overlays.
- Version keys are `str()`-ed at load, so an unquoted `3.10:` parses as
  float 3.1 and collides with `'3.1'`. Quote them.
- `3.2.2.1` and `3.2.3` are YAML **aliases** of anchors in the `'3.2'`
  block. Editing a 3.2 rule silently changes the other two.

### local packages

`source: local` has two modes. With `download.path` the file is an
archive under `local_packages/` extracted to `extracted_dir/<name>`.
Without `path`, nothing is extracted and the source root is
`local_packages/` itself — which is why those YAMLs write
`from: System/...`, where `System/` is a **host** directory, not Amiga
`SYS:`. The Amiga side is always `to:`.

Omitting `download:` entirely is not the same as `download: {source:
local}` — the former kills all install rules.

## Paths and staging

- `DEFAULT_BOOT_DEVICE = "SDH0"`; FAT32 boot partition dir is
  `EMU68BOOT`. Staging root is `<workdir>/staging/<DEVICE>/`.
- `prepare_staging_directory` scaffolds `C S L Libs Devs Prefs Fonts T`
  on the boot partition only, so Work/Data volumes stay clean.
- `resolve_staging_path` (destinations) walks components with a
  case-insensitive lookup and **appends missing ones as-is** — it never
  fails and never creates. The source-side `_ci_resolve_path` returns
  `None` on a miss instead. That asymmetry is why a wrong `to:` silently
  makes a new directory while a wrong `from:` silently installs nothing.
  It exists because ADF/PFS3 are case-insensitive and Linux/macOS hosts
  are not; without it you get sibling `Devs/` + `DEVS/` with split
  contents.
- hst-imager path syntax: RDB ops use `<image>/mbr/<n>`, a partition is
  `<image>/mbr/<n>/rdb/<Device>`. `hst_path()` is the separator gate — a
  Windows raw device path keeps backslashes, everything else goes
  `as_posix()`.
- `localize_for_hst` copies a UNC-share source into the local work dir
  first, because `as_posix()` turns `\\server\share\x.adf` into
  `//server/share/x.adf`, which hst-imager rejects. Apply it to **every**
  input file handed to hst-imager as a source. A UNC *output* image can't
  be localised and is rejected up front in validate.

## Amiga boot model

Which file is which, and who writes it:

| file | origin |
|---|---|
| `S/Startup-Sequence` | stock from the install ADF, only ever surgically edited |
| `S/User-Startup` | created empty if missing, package `scripts:` blocks appended |
| `S/Shell-Startup` | fully generated from a jinja template, overwrites the ADF copy |
| `S:Hatcher-FirstBoot`, `S:FirstBoot/*` | bundled, byte-copied, gated on `S:FirstBoot.done` |

Startup-Sequence surgery removes the CPU CheckInstall block (errors on
68040 under Emu68), the stock RexxMast start (re-added after BindDrivers
so FirstBoot scripts can use ARexx; double-start fails rc20), and the
bare `Mount DEVS:DOSDrivers` line (re-injected with `>NIL:` to swallow
the duplicate-mount error on later boots). The ROM CheckInstall block is
deliberately **kept**.

**InjectAfter on a shared anchor is LIFO.** Each injection re-reads the
file and inserts immediately after the anchor, so the *last* entry in the
list ends up *first* at runtime. `STARTUP_SEQUENCE_INJECTIONS` is written
in reverse execution order for the `BindDrivers` group. To make your
injection run later at boot, put it **earlier** in the list.

Injector footguns: a not-found pattern is a warning and the block is
appended to EOF anyway, yet `inject_script` still returns `True` — the
injection count proves nothing. `REMOVE` with a start match but no end
match deletes to EOF. Nothing checks for pre-existing markers, so
re-running against a dirty staging dir double-injects.

Ordering consequence for packages: FirstBoot runs at BindDrivers time,
far earlier than User-Startup. Anything needing mounted volumes, assigns,
or a live ARexx port belongs in a Startup-Sequence injection or an
`S:FirstBoot/` one-shot. Everything else goes in User-Startup via
`scripts:`.

**Text encoding is load-bearing.** Amiga scripts are read/written
`iso-8859-1` (decodes every byte, so no fallback is needed) with explicit
`newline="\n"` on every build-time writer. `.gitattributes` is a repo-wide
`* -text` so Windows CI's `core.autocrlf=true` can't ship CRLF. Both
halves are needed: gitattributes covers byte-copied assets, the newline
pins cover generated files. v0.4.1 shipped CRLF Amiga scripts and
AmigaDOS failed at first boot ("bad number" from FailAt, unknown command,
missing ENDIF).

## Host tools

- `tools.yaml` is the single source for host downloads. `platform-url`
  keys are `f"{os}-{arch}"` with values `darwin|windows|linux` ×
  `x64|arm64` — never `macos`/`x86_64`. `direct-url` is a single url.
  Unsupported platform returns `None` (logged, not raised); malformed
  YAML *does* raise. Don't re-introduce a separate `startup_files.yaml`.
- **hst-imager: `fs extract` vs `fs copy`.** `fs extract` pulls *out of* a
  container (adf/iso/lha). `fs copy` pushes host files *into* a PFS3
  partition. They are not interchangeable.
- **LHA uses hst-imager `fs extract` first** (it preserves
  Latin-1 names), with 7z only as fallback. Windows ships full `7z.exe` +
  `7z.dll`, unix `7zz`; `run_7z` is the single choke point. Windows needs
  a two-stage bootstrap because the 7-Zip release is a self-extractor, so
  `7zr.exe` is fetched first to unpack it.
- Download cache: MD5 only, compared case-insensitively. A cached file
  with no configured hash is reused forever with no TTL. Nothing ever
  hard-fails on a *missing* hash. Writes go to `<dest>.tmp` + rename so a
  partial never poisons the cache. HTTP 404 is permanent and aborts
  remaining mirrors; 5xx/429 retry.
- `mirrors` means two different things: for aminet hosts they are *base
  URLs* joined with the path; everywhere else they are *full backup URLs*
  (that's what `backup_url` becomes).
- Tool cache invalidates via a `<binary>.version` sidecar holding the
  pinned URL — bump the URL in tools.yaml to force a re-fetch. 7z is
  exempt and never updates once present.
- Elevation: one `acquire_elevation()` per build. Windows and headless
  macOS use a long-lived elevated helper with file-based JSON IPC; Linux
  and tty macOS use sudo/pkexec directly. **Do not reintroduce a per-call
  `runas` fallback on Windows** — it UAC-prompts on every call and one
  missed prompt fails the build midway; failing fast is the design. The
  `runas` branch must also stay unredirected: combining `-Verb RunAs`
  with `-RedirectStandardOutput` makes Start-Process fail parameter
  binding and exit 0, i.e. a silent false success on a flash that never
  wrote.
- `archive.py`'s LHA call passes `timeout=None` deliberately; `run_7z`
  and `tools.py download_file` have no timeout by omission, so a stalled
  tool download hangs the setup worker forever.

## GUI and config

- `BuildConfig` is pydantic v2 with **`validate_assignment` off**, so
  `collect_config`'s field-by-field mutation is never validated. You can
  save a config that explodes on reload.
- The round-trip is asymmetric: out via `collect_config` +
  `model_dump_json`, in via `model_validate` + a hand-maintained list of
  per-tab `set_config` calls. pydantic ignores unknown keys, so removing
  a schema field never errors on load — it errors later in whichever
  `set_config` still reads it. **Grep the GUI side before deleting any
  field**; a round-trip check does not exercise that path.
- **No persistence.** MainWindow always starts from
  `create_default_config()`. Config moves only via explicit Load/Save
  dialogs. `hatcher_data/` is the only cross-run state.
- Threading: workers subclass `QThread` and override `run()`, so the
  worker object lives in the GUI thread and only `run()` is off-thread.
  The whole `builder/` tree is Qt-free; results cross back as signals
  only. An uncaught exception in `run()` dies silently and
  `build_finished` never fires, freezing the dialog at "Initializing" —
  only `BuildWorker` has the try/except wrapper.
- Tree keys are **not** package names: bundle rows expand to member lists.
  `set_config` collapses any-member-on into whole-bundle-on, so a
  partially-disabled bundle round-trips to fully enabled. A bundled
  package's own `default:` is dead — `Bundle.default` wins.
- Signal ordering in `open_config` is load-bearing:
  `output_tab.set_config` emits `target_size_changed`, which rebuilds the
  partition layout from defaults, so `partitions_tab.set_config` must run
  after or custom sizes are lost. Programmatic `setChecked` doesn't fire
  `buttonClicked`, hence the manual `_on_mode_changed()` calls.

## Generated files and meta

- **`docs/packages.md` is generated** by `docs_hooks.py` (an mkdocs
  `on_pre_build` hook) from the package YAMLs, and is **gitignored**.
  Never hand-edit it — edits are silently overwritten on the next mkdocs
  run and can never be committed. Group order and header prose live in
  `docs_hooks.py`. Every other file in `docs/` is hand-written and
  tracked.
- Version lives in **two** places that must match: `pyproject.toml` and
  `src/build/settings/base.json`. The runtime/GUI title reads
  `pyproject.toml` via importlib metadata; artifact filenames are renamed
  from `base.json`. Drift means the window title and the installer
  filename disagree. Nothing checks the tag against either.
- CI: `release.yml` fires on `v*` tags (or dispatch, which builds
  artifacts only), 6-job matrix, `fail-fast: false`. **The GitHub release
  is created as a draft** and must be published by hand — the Discord
  announcement triggers on `release: published`, not on the tag.
  `docs.yml` is **`workflow_dispatch` only**; docs are never rebuilt on
  push.
- `.gitignore` starts with a blanket `.*`, so all dotfiles are ignored
  except four explicit un-ignores. Local agent instructions are therefore
  invisible to collaborators. Also ignored and easy to
  mistake for tracked: `docs/packages.md`, `tests/`, the root
  `emu68-config.json`, `build-and-extract.sh`, root-level `*.lha`.
  `src/build/settings/windows.json` is *not* ignored but is intentionally
  absent — CI synthesizes it.

## Fixed — don't reintroduce

- **Install rules must use the configured boot device.**
  `PackageInstaller` takes `boot_device` and `install_packages` passes
  `partitions.bootable_device_or_default`, matching `configure.py` and
  `install_workbench.py`. It used to hardcode `DEFAULT_BOOT_DEVICE`, so a
  renamed boot partition split staging in two and package files landed in
  an `SDH0` tree finalize never copied.
- **Any GUI list of packages must filter on `emu68_version`, not just
  kickstart.** The resolver filters on both and drops unknown names with
  a bare `continue`, so a tree built without the emu68 filter offers
  packages that vanish from the build with no warning. `Emu68Tab`
  emits `emu68_version_changed` (including from `set_emu68_version`,
  since `setChecked` doesn't fire `buttonClicked`) and `PackagesTab`
  rebuilds on it. Same applies to `get_bundles_for_version` /
  `get_bundle_members`, which both take the emu68 arg now.
- **Never accept `7za`.** It's the reduced "Extra" build with no LHA
  codec. `_TOOL_NAMES` lists `7zz` before `7z` on POSIX so a system-wide
  7-Zip can't shadow the full build in the tools dir, and `download_7zip`
  no longer probes PATH for `7za`.

## Reference implementation

Original PowerShell imager at
`/Users/chris/Coding/Emu68-Imager-Software-2.1.2`. When in doubt about
file formats, script logic, or Amiga-side behaviour, check that tree
first — output should match it byte-for-byte where possible.

## Gotchas

- **Icon positioning is build-time, alphabetical, per-drawer, and
  written by byte-patching — no external tool.**
  `staging/icon_grid.py:arrange_icons` walks the whole boot staging
  tree and grids **every** drawer containing `.info` files — package
  drawers included, because install rules merge archives (HippoPlayer +
  HippoSupport) and vendor layouts interleave. Containers first, then
  tools. Skips `Prefs/Env-Archive/`; `disk.info` is never touched
  (volume icon, and the SYS: window geometry lives in it — hence the
  root grid gets the smaller `_ROOT_INNER_W` budget so the stock window
  doesn't clip a column). Runs **last** in `configure_prefs` on purpose:
  `apply_icon_set_drawer` matches drawers by byte-equality against the
  template, so any position patch before it would stop every swap.
  Writers, all in `icon_grid.py`: classic position = BE i32 pair at
  offset 58; drawer window = NewWindow at 78–86 inside DrawerData (only
  when the pointer at 66 is set); show-all-files = `dd_Flags` in the
  6-byte DrawerData2 after the classic data (located via
  `files.py:_parse_info_to_tooltypes`, revision bit in Gadget UserData
  at 44, inserted for rev-0 icons). PowerIcons-style icons (plain PNG
  `.info`, e.g. MagicMenu 3's DualPNG set): sized from the IHDR,
  position written into the `icOn` chunk (OS4 tag list: 0x80001001/2 =
  x/y, 0x8000100B = tooltype strings; strip-everywhere + append-once,
  CRCs recomputed); they render on 3.x only via PeterK's icon.library
  (mandatory iconlib package). Sizing (mirrors iTidy's on-Amiga
  measurements): the planar gadget size can be a stub (seen 8×8) — real
  size comes from the ColorIcon `FACE` chunk or the NewIcons `IM1=`
  tooltype (bytes +5/+6 minus 0x21), take the max; add the 3px emboss
  frame (×2 when framed, ×1 when the FACE flags say frameless); label
  width counts at 8px/char (Topaz 8); icons are bottom-aligned per row
  so labels share a baseline. Column widths are per-column and row
  heights per-row (workbench clean-up density - a long label only
  widens its own column), 8px gaps. Column count aims for a 2:1 window
  (min 2 columns) and shrinks until the width budget fits; the root
  instead fills the fixed stock width. First boot mutates some drawers
  after the grid is baked: `_SLOT_ALIASES` stacks variants FirstBoot
  collapses onto one canonical icon (HDToolBoxPi3/Pi4 → HDToolbox,
  _AUX → AUX) on a single slot, `_SORT_LAST` pushes icons that vanish
  after first boot (FirstBootWB, uaegfx/videocore) to the grid tail —
  extend both when a new FirstBoot script deletes or renames a visible
  `.info`. Package drawers under `Programs/` holding only icon-less
  files (Roadshow docs) get show-all-files on their drawer icon so the
  window doesn't open empty — deliberately not applied outside
  Programs/ so stock drawers (Storage/Keymaps) keep OS behaviour.
  Field-verified on 3.2.3 hardware (first boot keeps the positions; the
  old "positions don't survive fs copy" belief was wrong).
- `ensure_drawer_icons()` walks `staging/icons.py:_ICON_ROOTS`
  (`Programs/`, `Prefs/`) and drops `_drawer.info` beside any icon-less
  folder so it is at least visible. System dirs are excluded on purpose
  — Workbench hides them by default. `apply_icon_set_drawer` then swaps
  only drawers byte-identical to the template, and refuses any source
  that isn't `do_Type == 2` (a WBTOOL source made every folder throw
  "Unable to open your tool" on 3.9).
- **Empty drawers get dropped by `hst-imager fs extract`.**
  `ensure_dirs_for_orphan_drawer_icons()` scans for `.info` files with
  magic `0xE310` and `do_Type == 2` at offset 48 of the DiskObject struct
  and recreates the missing directory. Catches `Storage/DataTypes/`,
  `Storage/DOSDrivers/` on stock installs.
- **Amiga folder naming.** The tool's folder on the boot partition is
  `SYS:Emu68-Hatcher/`. Don't touch `SYS:System/` (OS-owned) or
  `SYS:Pistorm/` (legacy; removed).
- **macOS can't mount Amiga PFS3 partitions.** Read files off a card with
  `sudo hst-imager fs copy /dev/diskN/mbr/2/rdb/1/<path> dest/`. The raw
  `/dev/disk` node needs sudo; slice-level `disk8s2` access is not enough
  (hst-imager wants the full MBR+RDB layer stack).
- **ROM scanner ≠ ADF scanner.** The ROM scanner recognises files by
  extension and size; the ADF scanner uses a hash database
  (`data/reference/install_media_hashes.yaml`). They live in
  `data/rom_detection.py` and `data/install_media.py` and share little
  code on purpose.
- `str.splitlines()` in the injector also splits on `\x0b \x0c \x1c-\x1e
  \x85`, all legal Latin-1 bytes — content carrying those silently gains
  lines.

## Commits

- lowercase subject, imperative mood, no Co-Authored-By
- short body explaining *why*, not *what* (the diff is the what)
- push only when the user explicitly asks
