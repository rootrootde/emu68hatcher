# Remediation plan

Each package below is one change and should land separately. Behavior fixes come first, dead code follows, and file moves happen last. No package adds a test suite. Verification is manual and uses the existing static checks and GUI build paths.

## Behavior fixes

### P1 Require disk exclusion before raw operations

Findings: F1

Files: builder/host/disk_enum.py, builder/pipeline/create_image.py, builder/pipeline/flash.py, builder/pipeline/finalize.py, builder/workflow.py

Change:

- Return a checked disk-operation result from unmount_disk and _set_windows_disk_offline, including exit code and command output.
- Raise BuildError before repartition, copy, or flash when the target cannot be unmounted or taken offline.
- Remove online_disk from stage_flash. Restore the disk only in BuildWorkflow.finally.

Must not change: Windows raw device targets stay plain strings. Elevation is acquired once per build. Keep the long-lived helper and do not add a per-call RunAs path.

Risk: high. This is destructive-device code.

Manual verification: on each host OS, hold a card volume busy and confirm the build stops before the first raw command. On Windows, confirm the card stays offline through flash and returns online after success, failure, and cancel.

### P2 Restore saved physical targets and loaded partition layouts

Findings: F2, F6

Files: gui/tabs/output.py, gui/tabs/partitions.py, gui/main_window.py

Change:

- Add a pending target field in OutputTab. Set it from device path or flash_target during set_config.
- Preserve the current target across refresh. After disk discovery, select the exact pending device or select none if it is absent.
- Emit a completion signal after target restoration and size publication.
- During open_config, apply the saved partition model only after that completion signal. A later refresh must not reset a loaded model unless the user chooses another target.
- Show the physical target in the build confirmation for both raw-device and image-plus-flash modes.

Must not change: output_tab.set_config still calls its mode handler because programmatic setChecked does not emit buttonClicked. A missing saved card must never fall back to another card.

Risk: high. A wrong selection erases the wrong device.

Manual verification: save a config for the second of two cards, restart, reverse enumeration order, load the config, and confirm the correct card and custom partition layout remain selected. Remove that card and confirm no replacement target is selected.

### P3 Make direct flash control independent of output

Findings: F3

Files: builder/host/disk_writer.py, new builder/host/_flash_process.py, utils/host_tools.py

Change:

- Add a local flash adapter that starts the wrapped process with get_hst_imager_env.
- Drain merged output on a reader thread into the existing tail buffer.
- Poll process state, cancellation, and deadline on the control thread.
- Return the same typed result shape as the helper adapter and keep progress parsing in one place.
- On cancel or timeout, terminate the raw writer, wait with a bounded deadline, and report a failure if it does not stop.

Must not change: raw-write cancellation must not use the generic elevated runner's weaker root-child handling. Keep helper streaming, recent error lines, verification, and skip-unused-sectors behavior.

Risk: high. This touches subprocess cancellation and elevated raw writes.

Manual verification: point the local adapter at a temporary executable that prints once and then stays silent. Confirm cancel and timeout return promptly. Then run one real card flash with verification enabled.

### P4 Track required artifacts through extraction and install

Findings: F4

Files: builder/pipeline/download.py, builder/pipeline/extract.py, builder/pipeline/configure_boot.py, builder/pipeline/install_packages.py, builder/pipeline/_selection.py, builder/workflow.py

Change:

- Record which download items and selected packages are required.
- Fail when boot metadata cannot be resolved or a required boot archive cannot be extracted.
- Fail when Resolution.unsatisfiable contains a hard requirement.
- Before package install, require an extracted source for every mandatory package that has a download and install rules.
- After boot copy, require at least one primary boot file and every selected kernel variant expected by the chosen release.

Must not change: optional package downloads, optional boot variants, icon patches, and absent optional ADF rules remain warnings. Do not make every zero-file package fatal because script-only, relocate-only, and ADF-sourced packages can legitimately copy zero downloaded files.

Risk: medium.

Manual verification: corrupt a required boot archive and a mandatory package archive and confirm each build stops with the component name. Make an optional package unavailable and confirm the build continues with one warning.

### P5 Put partition rules in the persisted model

Findings: F5

Files: config/schema.py, config/partition_helpers.py, gui/tabs/partitions.py, builder/pipeline/finalize.py

Change:

- Move hard layout checks from validate_partition_layout into PartitionConfig validation: one FAT32 container, one ID76 container, supported order, partition count, alignment, size bounds, filesystem bounds, unique names, and one bootable Amiga partition.
- Keep validate_partition_layout as a UI adapter over the same rule function.
- Make PartitionsTab.get_config rebuild every AmigaPartition from model_dump data before constructing the parent model.
- Use device_to_mbr for every finalization destination. Remove the MBR 1 and last-ID76 fallbacks.

Must not change: configured boot-device lookup, case-insensitive Amiga names, Windows raw path handling, and filesystem size limits.

Risk: medium.

Manual verification: enter an invalid device name and overlong volume in the table and confirm save and build reject them. Load a config with two ID76 containers and one with no FAT32 container and confirm both fail during load with direct messages.

### P6 Prevent tree-copy cycles

Findings: F7

Files: builder/pipeline/install_extras.py, builder/staging/packages.py, new builder/staging/tree_copy.py

Change:

- Move contained-tree traversal into tree_copy.py.
- Track resolved directory identities for the current copy.
- Skip a directory already visited and keep rejecting links outside the original source root.
- Preserve case-insensitive destination merging for package installs and overwrite behavior for user extras.

Must not change: user extras still overwrite earlier staged content, and package trees still merge rather than replace whole drawers.

Risk: medium.

Manual verification: mirror an extras directory containing loop pointing to the current directory and child/back pointing to its parent. Confirm the copy finishes once, reports skipped cycles, and does not create nested repeats.

### P7 Own and stop every GUI worker

Findings: F8

Files: gui/workers.py, gui/tabs/kickstart.py, gui/tabs/output.py, gui/tabs/start.py, gui/main_window.py, data/install_media.py, data/rom_detection.py

Change:

- Add interruption checks to directory walks and hashing boundaries.
- When rescanning, request interruption from prior workers and keep references until they finish.
- Add tab methods that request worker interruption and wait for a bounded period.
- Add MainWindow.closeEvent. Ignore close and display a status message while any worker remains active.

Must not change: scanning and tool downloads stay off the GUI thread. Do not terminate QThreads forcibly. Keep the deliberate no-timeout behavior of host-tool downloads; a blocked download means close is refused until it returns.

Risk: medium.

Manual verification: start both media scans, refresh disks, and start a tool download. Try rescan and close during each operation. Confirm no running worker is destroyed and the UI remains responsive.

### P8 Report worker failures instead of empty results

Findings: F8

Files: gui/workers.py, gui/tabs/kickstart.py, gui/tabs/output.py

Change:

- Add an error signal to ROMScanWorker, ADFScanWorker, and DiskListWorker.
- Log the caught traceback before emitting it.
- Show a distinct scan or enumeration failure state in the owning tab. Keep valid empty results as the current empty state.

Must not change: worker exceptions must not escape QThread.run, because an uncaught exception can leave the UI waiting forever.

Risk: low.

Manual verification: make a scan directory unreadable and make the platform disk command unavailable. Confirm both produce a logged error and a failure label, not only "none found".

### P9 Validate hashless download bodies and cache origin

Findings: F9

Files: builder/host/downloads.py, builder/host/download_catalog.py

Change:

- Check cancellation between response chunks.
- When Content-Length is nonzero, require the final byte count to match before renaming the temporary file.
- Store the resolved URL in a sidecar for hashless entries. Reuse only when the sidecar matches the current URL.
- Remove the temporary file and sidecar on failed verification.

Must not change: current MD5 comparison, mirror policy, 404 handling, retry backoff, and atomic temporary-file rename. Do not change tools.yaml or the pinned host-tool download rules.

Risk: medium.

Manual verification: use a local HTTP server that advertises more bytes than it sends, changes the URL while keeping the filename, and responds slowly enough to cancel. Confirm no partial cache entry survives and the changed URL downloads again.

### P10 Make startup edits transactional

Findings: F11

Files: builder/staging/scripts/injector.py, builder/pipeline/configure_scripts.py

Change:

- Return an InjectionResult containing matched, changed, and error fields.
- Locate both remove boundaries before constructing output.
- Treat a missing required before or after anchor as failure, not append-at-EOF.
- Write the file only after a complete action.
- Detect existing marker blocks so rerunning against a dirty staging tree does not duplicate them.
- Have configure_scripts raise BuildError when a required action fails.

Must not change: read and write Amiga scripts as ISO-8859-1 with LF newlines. Preserve the shared BindDrivers LIFO order and keep the ROM CheckInstall block.

Risk: high. Startup-Sequence is boot-critical and newline-sensitive.

Manual verification: build each supported Workbench family, inspect the blocks around BindDrivers, and confirm the generated file uses LF. Remove one anchor in a scratch Startup-Sequence and confirm the operation leaves the file unchanged and reports the missing pattern.

### P11 Enforce the external archive size ceiling

Findings: F10

Files: builder/host/archive.py, utils/host_tools.py

Change:

- Add a 7-Zip listing parser that returns member sizes without extraction.
- Sum declared regular-file sizes and reject totals above DEFAULT_MAX_EXTRACTED_BYTES.
- Run the check before both 7z and LHA extraction.

Must not change: LHA extraction still tries hst-imager first to preserve Latin-1 names and uses the full 7-Zip build only as fallback. Do not replace the shipped 7-Zip build.

Risk: medium.

Manual verification: list and extract a normal LHA and 7z archive, then present a scratch archive whose declared expanded size exceeds the ceiling and confirm rejection happens before output files appear.

### P12 Preserve disabled recommendations and partial bundles

Findings: F12

Files: gui/tabs/packages.py, builder/pipeline/_selection.py, data/package_resolver.py

Change:

- Pass disabled PackageConfig names as deselected to resolve.
- Represent a mixed bundle as PartiallyChecked and retain its member map.
- When the user clicks a mixed bundle, apply the new checked state to every member. If untouched, save the original per-member state.

Must not change: bundle rows remain the normal UI, mandatory packages remain selected, and MUI conflict handling stays symmetric.

Risk: medium.

Manual verification: load a config with one member of a bundle disabled and one recommended package disabled. Save without edits and compare member values. Build and confirm the disabled recommendation does not return.

### P13 Make config assembly and version handling atomic

Findings: F13

Files: gui/main_window.py, config/schema.py, config/loader.py, config/defaults.py

Change:

- Have collect_config build plain data from all tabs, then call BuildConfig.model_validate once.
- Replace self.config only after validation succeeds.
- Parse version from the raw JSON before model validation.
- Add explicit migrations for accepted older versions, reject unsupported future versions, and forbid unknown fields after migration.
- Save only the current schema version.

Must not change: Wi-Fi credentials remain excluded from saved JSON. Legacy rom_directory and install_media.directory still migrate into asset_directories. Output tab setup remains before partition setup where target sizing applies.

Risk: medium.

Manual verification: load and save a current config, an old single-directory config, a future-version config, and a config with an unknown key. Confirm only the first two load and the old one preserves its asset directory.

### P14 Normalize package catalogue identity and errors

Findings: F14

Files: data/package_schema.py, data/package_loader.py

Change:

- Validate package names with a lowercase identifier pattern.
- Reject case-insensitive duplicate names and capability tokens.
- Build a normalized lookup index once and use it in get_package_by_name.
- Parse all package files first, collect filename-specific errors, and stop before dependency graph validation if any file failed.
- Add every active group to the ordered group catalogue.

Must not change: package discovery stays file-based with no Python registration step. Broken optional package files must no longer disappear silently, but valid packages and provider selection keep their current order.

Risk: medium.

Manual verification: use a scratch package directory with an uppercase name, a duplicate differing only by case, and one malformed file referenced by another package. Confirm the error names the originating files in one report.

### P15 Stop failed disk-claim threads

Findings: F15

Files: builder/host/disk_claim.py

Change:

- On readiness timeout, set the stop event and join the worker before returning False.
- If the worker cannot stop within the release deadline, retain the object and report the failure instead of discarding it.
- Make claim_macos_disk call release for every failed acquisition path.

Must not change: a successful claim stays alive for the full build and is released in workflow cleanup.

Risk: medium. This touches macOS DiskArbitration lifetime.

Manual verification: delay the claim worker beyond three seconds and confirm it cannot acquire after the caller reports failure. Confirm a normal claim remains held until release.

### P16 Clean askpass files and nested extraction sentinels

Findings: F20

Files: builder/host/elevation.py, builder/workflow.py, builder/staging/packages.py

Change:

- Add an elevation-token cleanup function that shuts down helpers and unlinks askpass_path.
- Call it from workflow finally and from every acquisition fallback that abandons an askpass file.
- Extract nested archives into a new temporary sibling and rename it to the stable directory only after success. Remove a failed temporary directory.

Must not change: the askpass path remains alive while sudo timestamp refresh needs it. Nested archives remain limited to one level.

Risk: low.

Manual verification: complete and fail a sudo-backed build and confirm no matching askpass file remains. Force one nested extraction failure, retry in the same work directory, and confirm the second attempt runs.

## Dead code and stale text

### P17 Remove confirmed dead interfaces

Findings: F18

Files: builder/staging/packages.py, builder/pipeline/install_packages.py, builder/workflow.py, gui/workers.py, gui/widgets/partition_bar.py, gui/tabs/partitions.py, gui/tabs/kickstart.py, gui/main_window.py, pyproject.toml

Change:

- Remove PackageInstaller's unused version inputs, stored catalogue, progress callback, and _apply_install_rule pkg parameter.
- Remove BuildWorkflow.gui_mode and its caller argument.
- Remove PartitionBar.set_data disk_size and its caller argument.
- Remove KickstartTab.get_config wb_version.
- Remove the pytest configuration that points at the deleted suite.

Must not change: do not remove persisted schema fields or defaulted public parameters that still need a compatibility decision.

Risk: low.

Manual verification: run Ruff, load the package catalogue, construct the main window offscreen, and start a manual build through package installation.

### P18 Correct stale guidance and trim narration

Findings: F19

Files: builder/host/hst_runner.py, builder/pipeline/install_workbench.py, config/schema.py, docs/usage.md, config/loader.py, builder/pipeline/download.py, builder/workflow.py, builder/staging/scripts/injector.py, builder/host/downloads.py, builder/staging/packages.py

Change:

- Point missing-tool errors at the Start tab.
- Use current package IDs in the schema example.
- Make the documented default image size match the chosen product default.
- Correct the validator, download-failure, pipeline, and injection-order text.
- Remove comments that only narrate the next statement and fix nearby spelling errors.

Must not change: keep comments about elevation, raw path types, script encoding and order, binary formats, icon behavior, archive safety, and full 7-Zip selection.

Risk: low. No runtime behavior should change.

Manual verification: render the docs page, inspect the generated schema example, trigger a missing-tool error, and generate Startup-Sequence to compare the stated and actual order.

### P19 Share the case-insensitive source resolver

Findings: F20

Files: builder/staging/files.py, builder/staging/packages.py, builder/pipeline/relocate.py

Change:

- Add one miss-on-any-component source resolver beside ci_match_child.
- Replace both private copies.
- Keep resolve_staging_path separate because destination append-on-miss is intentional.

Must not change: source lookup returns None on a missing component; destination lookup appends missing components with caller-provided case.

Risk: low.

Manual verification: install and relocate files whose source path casing differs from the host tree, then confirm a missing source still installs nothing.

## Structural work

P20 and later depend on P1 through P19. Moving code first would make the safety fixes harder to review.

### P20 Split configuration domains

Findings: F17

Files: config/schema.py, config/defaults.py, config/partition_helpers.py, new config/constants.py, config/partition_models.py, config/display_models.py, config/network_models.py

Change:

- Move disk constants to constants.py.
- Move Filesystem, AmigaPartition, MBRPartition, and PartitionConfig to partition_models.py.
- Move CustomScreenMode and DisplayConfig to display_models.py.
- Move NetworkStack, WifiConfig, IpMode, InterfaceIp, and NetworkSettings to network_models.py.
- Keep BuildConfig, output models, version models, and compatibility re-exports in schema.py.
- Update defaults.py and partition_helpers.py to import concrete modules rather than using local imports back into schema.py.

Must not change: old import paths continue to work, serialized field names stay the same, and migration behavior from P13 remains intact.

Risk: medium.

Manual verification: load and save current and legacy configs, compare JSON keys, then construct the main window offscreen.

### P21 Create one stage registry and neutral state module

Findings: F16

Files: builder/workflow.py, all builder/pipeline stage modules, gui/dialogs/build_progress_dialog.py, new builder/state.py, builder/stage_registry.py

Change:

- Move BuildStage, BuildState, BuildResult, and callback aliases to state.py.
- Define the ordered stage ID, label, function, and progress inclusion in stage_registry.py.
- Execute the registry in workflow.py and read its labels and order in the progress dialog.
- Give setup_workspace its own stage ID.

Must not change: validate stays before workspace setup because it acquires elevation and the macOS claim. Final output move stays after the loop and only on success. Flash progress value zero still selects the indeterminate bar.

Risk: medium.

Manual verification: run a manual build and confirm every stage appears once, the overall bar stays monotonic, and final move and cleanup ordering are unchanged.

### P22 Replace optional phase state with explicit outputs

Findings: F16

Files: builder/state.py, builder/workflow.py, builder/pipeline modules

Change:

- Add typed ValidatedInputs, Workspace, DownloadedArtifacts, ExtractedArtifacts, and CreatedImage records.
- Have each stage receive the prior record and return the next one.
- Keep only live progress, cancel state, elevation, and disk claim on the workflow object.
- Remove hand-written "stage may have failed" guards made impossible by the record types.

Must not change: resolution remains cached for the build, device image paths remain strings, and no stage reads a work directory after finalize removes it.

Risk: high.

Manual verification: complete image, direct-device, and image-plus-flash builds. Cancel after each long stage and confirm cleanup still has the elevation and disk-claim state it needs.

### P23 Split elevation by platform

Findings: F17

Files: builder/host/elevation.py, builder/host/elevated_helper.py, new builder/host/_elevation_common.py, _elevation_unix.py, _elevation_windows.py

Change:

- Keep acquire_elevation, run_elevated, wrap_for_elevation, token types, and errors re-exported from elevation.py.
- Move token data, quoting, wrappers, and common process work to _elevation_common.py.
- Move sudo, askpass, pkexec, and macOS acquisition to _elevation_unix.py.
- Move Windows helper acquisition to _elevation_windows.py.
- Make elevated_helper import quoting from the common module, removing the import cycle.

Must not change: one prompt per build, long-lived Windows and headless-macOS helpers, no per-call Windows RunAs fallback, and host-tool environment propagation.

Risk: high. This is elevation and subprocess code.

Manual verification: image-only build without elevation, then acquire, cancel, and clean up a physical-device build on each supported host OS.

### P24 Split disk enumeration by platform

Findings: F17

Files: builder/host/disk_enum.py, new builder/host/disk_info.py, _disk_linux.py, _disk_macos.py, _disk_windows.py

Change:

- Move DiskInfo and normalization helpers to disk_info.py.
- Move each platform enumerator and disk operation to its platform module.
- Keep list_removable_disks, find_disk, unmount_disk, online_disk, and eject_disk as facade functions at the old path.

Must not change: removable and system-disk filters, Windows PhysicalDrive normalization, macOS whole-disk selection, and the checked unmount behavior from P1.

Risk: medium.

Manual verification: enumerate, unmount or offline, restore, and eject a removable card on each supported OS. Confirm the system disk never appears as a writable target.

### P25 Split validation domains

Findings: F17

Files: builder/pipeline/validate.py, new builder/pipeline/validate_output.py, validate_archives.py

Change:

- Move output target checks, size checks, elevation acquisition, and disk claim work to validate_output.py.
- Move Roadshow and Picasso96 file and directory classifiers to validate_archives.py.
- Keep stage ordering, asset directory checks, media checks, and calls to both helpers in validate.py.

Must not change: validation runs before workspace setup and must not touch work directories. It must acquire elevation once and retain a successful disk claim.

Risk: medium.

Manual verification: validate image, raw-device, and image-plus-flash configs, plus each accepted commercial archive layout. Confirm no work directory is created by validation.

### P26 Split preference configuration domains

Findings: F17

Files: builder/pipeline/configure_prefs.py, new builder/pipeline/configure_network.py, configure_hardware.py, configure_icons.py

Change:

- Move wireless, interface, route, and DNS writers to configure_network.py.
- Move WHDLoad ROM staging, VideoCore, Poseidon, and HDToolBox changes to configure_hardware.py.
- Move icon-set drawer and new-folder application to configure_icons.py.
- Keep the ordered coordinator and arrange_icons call in configure_prefs.py.

Must not change: icon-set drawer matching runs before position patching, generated text keeps its existing encoding and LF policy, and the icon positioning implementation stays unchanged.

Risk: medium.

Manual verification: build with DHCP and static network settings, both supported display families, Poseidon, and each icon set. Compare staged preference files and icon counts.

### P27 Split Workbench ADF installation

Findings: F17

Files: builder/pipeline/install_workbench.py, new builder/pipeline/adf_mapping.py, adf_extract.py

Change:

- Move ADF name mapping and case resolution to adf_mapping.py.
- Move rule selection, source resolution, extraction, rename handling, and per-rule progress to adf_extract.py.
- Keep stage order, required-media checks, staging setup, and compressed-file follow-up in install_workbench.py.

Must not change: ADF rule sequence order, mandatory zero-ADF failure, case-insensitive source matching, UNC localization, Amiga metadata, and Startup-Sequence production.

Risk: medium.

Manual verification: build every supported Workbench family and compare extraction logs, file counts, Startup-Sequence presence, and decompressed .Z outputs.

### P28 Split KickstartTab scan ownership

Findings: F17

Files: gui/tabs/kickstart.py, gui/workers.py, new gui/widgets/asset_scan_panel.py

Change:

- Move directory list controls, ROM and ADF worker ownership, scan state, row building, status labels, and details dialog to AssetScanPanel.
- Expose directories, set_version, results, and worker shutdown as a small panel API.
- Keep version choice, icon sets, locales, and config translation in KickstartTab.

Must not change: version changes start both scans, the 3.9 to 3.1 ROM mapping, icon filtering by version, and worker lifetime rules from P7.

Risk: medium.

Manual verification: repeatedly change version, add and remove directories, rescan before a prior scan ends, open details, and round-trip config.

### P29 Move partition edits into a model

Findings: F17

Files: gui/tabs/partitions.py, new gui/partition_editor_model.py, optionally new gui/widgets/partition_table.py

Change:

- Put disk size, boot size, partition collection, add, remove, resize, field updates, boot selection, validation, and fresh PartitionConfig construction in PartitionEditorModel.
- Make PartitionsTab bind widgets to model operations.
- If the tab remains over 400 lines, move table row rendering and typed edit signals to PartitionTable.

Must not change: cylinder rounding, free-space calculations, maximum partition count, exact-device sizing, bootable selection, and extra-content directory persistence.

Risk: medium.

Manual verification: exercise presets, exact card sizing, add and remove, drag resize, filesystem changes, boot selection, invalid names, extras, and config round-trip.

### P30 Decompose the package resolver without changing graph behavior

Findings: F17

Files: data/package_resolver.py

Change:

- Add a private resolver context holding normalized package, provider, mandatory, requested, and disabled indexes.
- Move provider choice, dependency closure, conflict component construction, and conflict pruning into separate private functions or methods.
- Keep resolve as the short fixed-point coordinator and retain _topological_order.

Must not change: provider priority, symmetric conflicts, component pruning, mandatory conflict failure, cycle warning, or install ordering.

Risk: medium.

Manual verification: compare resolved sets and order for every supported version, both MUI choices, disabled recommendations, virtual providers, conflicts, missing requirements, and a cycle.

### P31 Break up the longest local procedures

Findings: F17

Files: gui/widgets/partition_bar.py, builder/pipeline/download.py, builder/pipeline/finalize.py, builder/staging/packages.py

Change:

- In PartitionBar, separate geometry, boot, RDB children, handles, drag, and hover into private methods without adding another module.
- In download.py, separate boot downloads, package downloads, and failure classification.
- In finalize.py, separate device-map construction, staging inventory, and one-device copy.
- In packages.py, separate wildcard, exact-path, and common copy work.

Must not change: drawing geometry, progress percentages, required-versus-optional policy from P4, hst path construction, package glob semantics, stack patch rules, or case-insensitive destination behavior.

Risk: medium.

Manual verification: compare screenshots of the partition bar and compare build logs and resulting file counts for normal, wildcard, nested archive, and multi-partition installs.

## Execution order

- [x] P1 disk exclusion
- [x] P2 saved target and partition load order
- [x] P3 direct flash control
- [x] P4 required artifact status
- [x] P5 partition contract
- [x] P6 tree-copy cycles
- [x] P7 worker lifetime
- [x] P8 worker error reporting
- [x] P9 download body and cache origin
- [x] P10 transactional startup edits
- [x] P11 archive size ceiling
- [x] P12 package selection round-trip
- [x] P13 config assembly and version handling
- [x] P14 package catalogue identity
- [x] P15 disk-claim timeout
- [x] P16 temporary resource cleanup
- [x] P17 dead interfaces
- [x] P18 stale text and comments
- [x] P19 shared source resolver
- [x] P20 configuration split
- [x] P21 stage registry
- [x] P22 typed phase outputs
- [x] P23 elevation split
- [x] P24 disk enumeration split
- [x] P25 validation split
- [x] P26 preference split
- [x] P27 Workbench installation split
- [x] P28 Kickstart tab split
- [x] P29 partition editor model
- [x] P30 package resolver decomposition
- [x] P31 local procedure decomposition
