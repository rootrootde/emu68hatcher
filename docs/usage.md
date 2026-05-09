# Usage

## Build an image

1. **Launch the app.** It will check whether some required tools are installed.

2. **Start tab - install missing tools.** If required tools are shown as missing, click **Download missing tools** and wait for green checkmarks. If 7z fails to download on macOS, try **brew install p7zip** and hit refresh.

3. **Amiga Files tab - pick the Workbench version to install.** Select the folder containing your ROMs. emu68hatcher will automatically look in the same folder for the Workbench ADF files, but you can also point it somewhere else. ROMs and ADFs are identified by hash, so the filenames don't matter.

4. **Emu68 tab - pick the HDMI output mode** for your monitor and the Emu68 release to bundle (1.0.7 stable for pistorm32-lite / classic, or 1.1.0-alpha.1 for PiStorm16 support).

5. **Software tab - enable/disable optional packages and pick the icon set** (GlowIcons on 3.2+, or Standard). Mandatory system packages are always included and not shown here. The first build downloads everything (with caching, subsequent builds are faster).

6. **Output tab.** Pick how to deliver the build:
    - **Image file** - writes a regular **.img** file to disk. **Sparse** is on by default, so a 64 GB image only uses the few hundred MB of actual data, not 64 GB of host disk.
    - **Image file + flash to SD card** - same as above, then writes the image to the SD card you pick. Requires admin/sudo.
    - **Direct to SD card** - skips the **.img** file and builds straight onto the SD card. Fastest path; requires admin/sudo. Useful when you don't need to keep the image around.
    
!!! danger "Double-check the target!"
    Whichever tool you use, verify the target device twice before confirming. **Picking the wrong disk will wipe it** - including your system disk. Emu68 Hatcher refuses to flash any disk that holds a mounted root partition, but external tools won't.

7. **Partitions tab - configure disk size and partition layout.** Default is 64 GB image with 4 GB Workbench partition and a "Work" partition. You can add/remove/resize partitions, drag the borders on the partition bar to resize them or type exact sizes. Whenever the Output tab targets a real SD card (Image file + flash, or Direct to SD card) the total disk size is locked to the size of the chosen card.

8. **Click "Build image".** On first run downloads a bunch of packages (uses cache after that). Progress and a build log are shown in the dialog. The log is also written to **buildlog.txt** next to the output image.

Both flashing modes will prompt for admin access once at the start of the flash.

## Save / load configuration

You can save the current configuration to a JSON file via **Save config** (bottom left) and load it later with **Load config**.
