# Repository review findings

Reviewed 2026-08-08 against the current working tree. The tree already had local edits; those edits were included in the review and were not changed.

Scope covered 82 Python modules under src/main/python/emu68hatcher, bootstrap.py, and 115 YAML files under the data tree. The Python tree is 15,887 lines. Ruff passes, all 109 package files load, all three bundles load, and all five ADF rule sets load. No project test directory exists in this checkout or its Git common directory. The pytest section in pyproject.toml points at the deliberately absent tests directory.

Severity means impact, not certainty. Every high and medium claim below was checked against its full caller path.

## Behavior and safety

### F1 [high, M] Raw disk exclusion is not required before destructive work

Evidence:

- builder/host/disk_enum.py:75-142 logs macOS and Linux unmount failures and returns normally.
- builder/host/disk_enum.py:213-219 discards the result of an elevated Windows Set-Disk command.
- builder/pipeline/create_image.py:151-154, builder/pipeline/flash.py:36-44, and builder/pipeline/finalize.py:114 continue after those calls.
- builder/pipeline/flash.py:41-44 brings a Windows disk online immediately after unmount_disk took it offline. workflow.py:372-384 already contains the correct end-of-build restore path.

A busy filesystem can remain mounted while the application repartitions or writes the device. On Windows, the flash stage also removes its own shell exclusion just before the write.

Direction: make offline or unmount failure an explicit error at destructive call sites, check the elevated result code, remove the early online_disk call from flash, and keep the final cleanup restore.

### F2 [high, M] Loading a saved device config can select another disk

Evidence:

- gui/tabs/output.py:202-218 restores only the mode. It does not retain OutputConfig.path for device mode or OutputConfig.flash_target for image-plus-flash mode.
- gui/tabs/output.py:144-171 clears the combo and accepts the first enumerated disk after each refresh.
- gui/tabs/output.py:186-200 and gui/main_window.py:235-245 overwrite the loaded config with the current combo row.
- gui/main_window.py:316-325 shows the image path in the confirmation dialog but does not show the flash target.

A config saved for one card can silently target the first currently enumerated card. In image-plus-flash mode, the final confirmation does not expose the changed physical target.

Direction: retain a pending device ID across refresh, select it only after enumeration completes, leave the selection empty if it is absent, and show every physical target in the confirmation dialog.

### F3 [high, M] Direct flash cancel and timeout depend on process output

Evidence:

- builder/host/disk_writer.py:132-180 checks cancel and deadline only inside iteration over proc.stdout.
- gui/dialogs/build_progress_dialog.py:183-190 notes that the writer is silent when piped.
- A quiet process blocks the iterator, so cancel and timeout are not checked. A quiet process that exits after the deadline can still be reported as successful.
- The direct Popen call at disk_writer.py:134-142 also omits get_hst_imager_env, unlike the helper worker and every shared host-tool runner.

This affects Linux, terminal-launched macOS, and already-root execution.

Direction: drain output on a reader thread while a control loop polls process state, cancel, and deadline. Pass the host-tool environment on the direct path. Keep raw-write termination separate from the generic elevated runner because its kill requirements differ.

### F4 [high, L] Required content can disappear while the build still succeeds

Evidence:

- builder/pipeline/download.py:184-185 warns when required boot download metadata cannot be resolved.
- builder/pipeline/extract.py:90-102 warns on every extraction failure, including mandatory packages and boot archives.
- builder/pipeline/configure_boot.py:38-46 warns and returns when boot files are absent.
- builder/pipeline/install_packages.py:50-55 warns for unsatisfied hard dependencies, and lines 71-77 reduce a zero-file install to a debug message.
- data/package_schema.py:116-120 describes requires as hard and recommends as soft.

The application can display "Build successful" for an image missing boot files or mandatory package content.

Direction: carry required artifact status through download, extraction, and install. Fail for unresolved boot metadata, failed extraction of required archives, unsatisfied requires, and missing sources for mandatory packages with install rules. Keep the existing warn-and-continue policy for optional content.

### F5 [high, M] Partition validation and finalization accept different layouts

Evidence:

- gui/tabs/partitions.py:303-337 mutates existing AmigaPartition objects. Assignment validation is disabled.
- config/partition_helpers.py:156-175 passes those instances into a new parent model without rebuilding them, so nested field validators are not rerun.
- A live check showed that device="NOT A DEVICE" and a 40-character volume survive build_partition_config and BuildConfig, while a newly constructed AmigaPartition rejects both.
- config/schema.py:188-273 allows zero or multiple FAT32 partitions and multiple ID76 containers.
- builder/pipeline/finalize.py:95-106 records each device's MBR number, then lines 139-143 ignore that mapping for Amiga devices and use the last ID76 number. EMU68BOOT falls back to MBR 1 when no FAT32 entry exists.

Hand-edited configs and GUI-edited nested models can pass validation but fail later or receive files in the wrong container.

Direction: put supported layout rules in PartitionConfig, rebuild nested models from plain data before save or build, require the current one-FAT32 and one-ID76 shape, and make finalization use its per-device mapping.

### F6 [medium, M] Async disk discovery overwrites loaded partitions

Evidence:

- gui/main_window.py:144-148 assumes output setup emits the target-size signal before saved partitions are applied.
- gui/tabs/output.py:116-171 actually starts DiskListWorker and emits after it returns.
- gui/tabs/partitions.py:181-239 rebuilds the default layout when that late signal arrives.

A config can appear loaded, then lose its partition count, names, filesystems, sizes, priorities, and extra-content paths.

Direction: treat config loading as one ordered operation. Restore the target, process its size, then apply the saved partition model after the disk result is known. Do not let later refresh completion reset an explicitly loaded layout.

### F7 [medium, S] Directory symlink loops can exhaust staging

Evidence:

- builder/pipeline/install_extras.py:66-90 follows directory symlinks whose targets stay under the source root.
- builder/staging/packages.py:53-78 does the same during package tree merges.
- Neither walker records visited directories.

A link such as loop pointing to the current directory, or a child link pointing to its parent, recurses until path, stack, or disk exhaustion.

Direction: share a tree-copy helper that tracks resolved directory identities. Skip repeated directories and continue rejecting targets outside the source root.

### F8 [medium, M] Background worker failures and lifetime are not controlled consistently

Evidence:

- gui/workers.py:142-150, 162-170, and 178-185 convert scan and disk-enumeration exceptions into empty results with no log or error signal.
- gui/tabs/kickstart.py:335-362 disconnects prior scan workers but does not stop or retain them safely.
- gui/tabs/start.py:273-293 and gui/tabs/output.py:144-156 create more user-owned QThreads.
- gui/main_window.py:344-352 has no close hook for these workers. The build dialog has such a guard at gui/dialogs/build_progress_dialog.py:291-313 because destroying a running QThread is fatal.

A real permissions, parser, hashing, or disk command failure looks like "nothing found". Closing the main window or rescanning at the wrong time can destroy an active thread.

Direction: add worker error signals, interruption checks in scan loops, one owner for each active worker, and a main-window close guard that requests interruption and refuses teardown while a worker is still running.

### F9 [medium, M] Hashless downloads can be stale, truncated, and slow to cancel

Evidence:

- builder/host/downloads.py:99-108 treats any existing hashless cache file as valid.
- builder/host/downloads.py:123-138 does not compare bytes read with Content-Length and does not check cancellation inside the body loop.
- data/packages/emu68_tools.yaml:11-15 follows the latest release with a stable filename and no hash.
- data/packages/genet_device_legacy.yaml:13-18 is a mandatory raw executable with no hash.

A short response can be renamed into the cache and reused. A later release at a new resolved URL is ignored when the filename stays the same. Cancel waits for the current transfer or socket failure.

Direction: reject a known-length short body before rename, check cancel between chunks, and store the resolved source URL beside hashless cache entries so a changed release URL invalidates the old file. Keep atomic temporary-file writes and current MD5 checks.

### F10 [medium, M] External archive extraction has no expanded-size limit

Evidence:

- builder/host/archive.py:45-46 defines an 8 GiB ceiling.
- ZIP and TAR enforce it at archive.py:178-202 and 263-298.
- 7z and LHA extract first at archive.py:205-260 and only count files afterward.
- User-supplied Roadshow and Picasso96 archives use these paths.

A crafted or accidental archive can fill the work filesystem before any size check runs.

Direction: list and sum file sizes before external extraction, then keep the current extraction order so LHA filenames still pass through the preferred extractor.

### F11 [medium, M] Startup-Sequence edits can corrupt a changed input and still report success

Evidence:

- builder/staging/scripts/injector.py:126-169 appends an injection to EOF when its anchor is missing.
- injector.py:172-206 removes from a matched start through EOF when the end pattern is missing.
- inject_script returns True after either outcome at lines 96-99.
- builder/pipeline/configure_scripts.py:93-103 counts those results and checks only whether two words appear anywhere in the file.

Changed installation media can receive misplaced startup code or lose the remainder of Startup-Sequence without stopping the build.

Direction: return a structured match result, find both removal boundaries before changing the file, leave the file unchanged on an incomplete match, and fail required startup edits when an anchor is absent.

### F12 [medium, M] Package selections do not round-trip faithfully

Evidence:

- gui/tabs/packages.py:225-241 turns a partially enabled bundle into fully enabled when any member is on.
- gui/tabs/packages.py:216-223 saves the collapsed state back to every member.
- builder/pipeline/_selection.py:24-42 discards disabled package entries and always passes an empty deselected set.
- data/package_resolver.py:95-101 already has suppression logic for disabled recommendations, but it cannot run.

Loading and saving can change package choices. Explicitly disabled recommended packages can return during resolution.

Direction: preserve partial bundle state, preferably with a partially checked bundle row whose next user action applies to all members, and pass disabled names to the resolver.

### F13 [medium, L] Config loading has no active compatibility boundary

Evidence:

- gui/main_window.py:173-247 mutates a previously validated BuildConfig field by field.
- config/schema.py:413-547 does not validate assignment and ignores unknown fields by default.
- config/loader.py:25-34 loads directly into the current model.
- BuildConfig.version at schema.py:416 is serialized but never read for a migration or rejection decision.

Cross-field rules can be bypassed, and a config from a newer incompatible version can lose unknown fields before being saved again.

Direction: build a plain aggregate from tab state, validate a fresh BuildConfig, and replace the live config only after success. Read the raw version before validation, migrate known older formats, reject newer formats, and reject unknown keys after migration.

### F14 [medium, M] Package identity and catalogue errors have conflicting rules

Evidence:

- data/package_schema.py:93-121 does not constrain package name case.
- data/package_resolver.py:40-47 normalizes names to lowercase.
- data/package_loader.py:122-127 looks up exact names.
- data/package_loader.py:32-60 silently omits a malformed package, then graph validation can blame a dependent for the missing token.
- data/package_schema.py:163-180 omits active groups including Commodities, Drivers, RTG, and Network, so they all share the final sort rank.

An uppercase name can resolve but fail later lookup, and one bad file can produce an error that points at the wrong package.

Direction: validate lowercase identifiers, reject case-insensitive duplicates, index once by normalized name, collect all file parse errors before graph validation, and define the full group order in one catalogue.

### F15 [medium, S] A timed-out macOS disk claim can outlive its caller

Evidence:

- builder/host/disk_claim.py:33-44 starts a daemon thread and returns False after a three-second wait without setting its stop event.
- builder/pipeline/validate.py:205-220 discards the claim object when acquisition reports failure.
- The worker can finish its claim after the timeout and then wait for a stop event that no retained caller can set.

The card can remain claimed for the rest of the process after the UI was told the claim failed.

Direction: stop and join on timeout, and make claim_macos_disk release every failed acquisition before returning None.

## Architecture and maintainability

### F16 [medium, L] Stage order, state, and GUI progress are separate contracts

Evidence:

- builder/workflow.py:20-82 owns stage and state types.
- builder/workflow.py:287-315 owns a separate execution list.
- gui/dialogs/build_progress_dialog.py:150-178 owns another label and order list.
- builder/pipeline/download.py:25-44 reports workspace setup as INIT, so setup contributes nothing to overall progress.
- Every stage accepts one BuildWorkflow containing optional state fields and checks its requirements by hand.
- download.py:72-140 also extracts the FFS handler, despite setup_workspace being the only workspace owner and extract being the named extraction stage.

Adding or reordering a stage requires edits in several places. Missing stage outputs surface late through uneven guards.

Direction: move BuildStage, BuildState, and result types to builder/state.py. Add one ordered stage registry for identity and labels. Derive execution and GUI progress from it. Later, replace the optional state bag with typed phase outputs passed to the next phase.

### F17 [medium, L] Eight large modules and five long functions need narrower ownership

The issue is mixed responsibility, not line count alone.

| File | Lines | Concrete split |
| --- | ---: | --- |
| gui/tabs/kickstart.py | 630 | Move directory controls, two scan workers, results, and details dialog to gui/widgets/asset_scan_panel.py. Keep version, icon, locale, and config translation in KickstartTab. |
| gui/tabs/partitions.py | 570 | Move disk size, boot size, partition mutations, validation, and fresh model construction to gui/partition_editor_model.py. If still large, move row rendering to gui/widgets/partition_table.py. |
| config/schema.py | 547 | Add config/constants.py, partition_models.py, display_models.py, and network_models.py. Keep BuildConfig and compatibility re-exports in schema.py. |
| builder/host/elevation.py | 439 | Keep a facade in elevation.py. Move token, quoting, wrapping, and common execution to _elevation_common.py; Unix acquisition to _elevation_unix.py; Windows acquisition to _elevation_windows.py. |
| builder/pipeline/configure_prefs.py | 435 | Move network writers to configure_network.py, hardware and tooltype changes to configure_hardware.py, and icon-set application to configure_icons.py. Keep ordering in configure_prefs.py. |
| builder/pipeline/validate.py | 429 | Move disk, claim, and elevation checks to validate_output.py. Move archive classifiers to validate_archives.py. Keep the stage coordinator and media checks in validate.py. |
| builder/host/disk_enum.py | 423 | Put DiskInfo in disk_info.py and move platform enumerators and disk operations to _disk_linux.py, _disk_macos.py, and _disk_windows.py. Keep a facade at the old import path. |
| builder/pipeline/install_workbench.py | 400 | Move ADF name mapping to adf_mapping.py and rule selection and execution to adf_extract.py. Keep stage order and compressed-file follow-up in install_workbench.py. |

Long functions worth local decomposition:

- gui/widgets/partition_bar.py:121-288 paintEvent, 168 lines.
- data/package_resolver.py:29-195 resolve, 167 lines and several nested graph operations.
- builder/pipeline/download.py:144-281 stage_download, 138 lines.
- builder/pipeline/finalize.py:67-198 _copy_staged_files_to_image, 132 lines.
- builder/staging/packages.py:204-302 _apply_install_rule, 99 lines.

The binary icon module is dense but cohesive. Its approach and format comments should stay. The full 7-Zip setup is also justified platform work and is not a cleanup target.

## Dead and stale code

### F18 [low, S] Confirmed dead code remains after recent feature removals

Safe candidates with no production or project-test readers:

| Location | Dead item |
| --- | --- |
| builder/staging/packages.py:84-102 | kickstart_version and emu68_version constructor inputs, their stored fields, the unread packages catalogue, and its import. |
| builder/staging/packages.py:104-127 | install_package progress_callback. The sole caller reports progress itself. |
| builder/staging/packages.py:204-208 | pkg parameter to _apply_install_rule. |
| builder/workflow.py:123-128 | BuildWorkflow.gui_mode parameter and field. |
| gui/widgets/partition_bar.py:69-71 | disk_size argument stored by set_data but never read. |
| gui/tabs/kickstart.py:596-603 | wb_version return key. MainWindow reads only version and asset_directories. |
| pyproject.toml:79-81 | pytest settings for the deleted test suite. |

Several defaulted parameters are never overridden, including flash force, FileMapping.add_directory filter_func, preference formatting knobs, and HSTRunner dry_run. These may be deliberate extension points; leave them until their public-contract status is decided.

BuildConfig.version is also unread, but it is persisted and belongs to F13 rather than safe deletion. Legacy rom_directory and install_media.directory are still read by config migration and GUI loading.

### F19 [low, S] User guidance, examples, and comments have drifted

Verified stale text:

- builder/host/hst_runner.py:89-95 recommends an emu68hatcher setup command that does not exist.
- builder/pipeline/install_workbench.py:126-130 recommends an emu68hatcher tools setup command that does not exist.
- config/schema.py:511-514 shows WHDLoad and DirectoryOpus package IDs, but current IDs are whdload and dopus418 and lookup is exact.
- docs/usage.md:25 says the default image is 64 GB, while config/defaults.py:35-47 creates 8 GB.
- config/loader.py:30-32 incorrectly says model_validate_json skips field validators.
- builder/pipeline/download.py:144-145 says every failure aborts, while optional failures continue.
- builder/workflow.py:1 omits workspace setup, extras, and flash.
- builder/staging/scripts/injector.py:242, 250, and 258 have stale shared-anchor ordinal comments. Runtime order is RTC, RexxMast, iconlib, FirstBoot, UAEGFX.

Comment volume is not broadly excessive: only four function docstrings exceed 18 words or one line. The real noise is self-evident narration and typoed restatements. Safe targets include injector.py:54,62,74,77,96; config/loader.py:45,48; host/downloads.py:207,253,282; and staging/packages.py:145,157,171,179,192,216,219,230,235.

Retain comments that explain elevation behavior, raw device path handling, Amiga script encoding and injection order, full 7-Zip selection, binary offsets, and icon layout rules.

### F20 [low, S] Small resource and consistency defects remain

- builder/host/elevation.py:281-291 creates askpass scripts. Successful sudo tokens retain the path, but workflow cleanup never unlinks it. The Linux fallback path also leaves the file after a failed sudo attempt.
- builder/staging/packages.py:179-194 treats the existence of a nested archive extraction directory as success. A failed extraction leaves the directory, so later rules never retry it.
- builder/staging/packages.py:40-50 and builder/pipeline/relocate.py:17-27 contain equivalent case-insensitive source resolvers under different names.

Direction: unlink askpass files when the elevation token is released, use a temporary directory plus success rename for nested archives, and share the source resolver beside ci_match_child while keeping destination append-on-miss behavior separate.

## Negative findings

- Ruff found no unused imports.
- No orphan Python module was found.
- No commented-out Python block longer than two lines was found.
- No statically unreachable block after return or raise was found.
- Legacy asset-directory fields and excluded Wi-Fi persistence are active compatibility behavior, not dead code.
- The icon positioning implementation is specialized but cohesive. Replacing its binary-patching approach is not recommended.
