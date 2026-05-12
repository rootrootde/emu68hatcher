# Usage

## Build an image

1. **Launch the app.** It will check whether some required tools are installed.

2. **Start tab - install missing tools.** If required tools are shown as missing, click **Download missing tools** and wait for green checkmarks.

3. **Amiga Files tab - pick the Workbench version to install.** Select the folder containing your ROMs. Emu68 Hatcher will automatically look in the same folder for the Workbench ADF files, but you can also point it somewhere else. ROMs and ADFs are identified by hash, so the filenames don't matter.

4. **Emu68 tab - pick the HDMI output mode** for your monitor and the Emu68 release to bundle (1.0.7 stable for pistorm32-lite / classic, or 1.1.0-alpha.1 for PiStorm16 support).

5. **Software tab - enable/disable optional packages and pick the icon set** (GlowIcons on 3.2+, or Standard). Mandatory system packages are always included and not shown here. The first build downloads everything (with caching, subsequent builds are faster).

6. **Output tab.** Pick how to deliver the build:
    - **Image file** - writes a regular **.img** file to disk. Sparse files are enabled by default, so a large image only uses as much disk space as the actual data.
    - **Image file + flash to SD card** - same as above, then writes the image to the SD card you pick. Requires admin/sudo.
    - **Direct to SD card** - skips the **.img** file and builds directly on the SD card. Fastest path; requires admin/sudo. Useful when you don't need to keep the image around.
    
!!! danger "Double-check the target!"
    **Picking the wrong disk will wipe it.** Emu68 Hatcher will refuse to write to mounted root partitions (=your operating system) but has no problem with wiping anything else you have connected.

7. **Partitions tab - configure disk size and partition layout.** Default is 64 GB image with 1 GB Workbench partition and a "Work" partition. You can add/remove/resize partitions, drag the borders on the partition bar to resize them or type exact sizes. With an SD card selected on the Output tab, the disk size matches the card.

8. **Click "Build image".** On first run downloads a bunch of packages (uses cache after that). Progress and a build log are shown in the dialog. The log is also written to **buildlog.txt** next to the output image.

Both flashing modes prompt for admin access once at the start of the build. On macOS, full disk access for hst-imager must be granted/setup on first install - see [Installation](installation.md#macos).

## Save / load configuration

You can save the current configuration to a JSON file via **Save config** (bottom left) and load it later with **Load config**.
