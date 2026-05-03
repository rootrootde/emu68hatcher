# Usage

## Build an image

1. **Launch the app.** It will check whether some required tools are installed.

2. **Start tab - install missing tools.** If required tools are shown as missing, click **Download missing tools** and wait for green checkmarks. If 7z fails to download on macOS, try 'brew install p7zip' and hit refresh.

3. **Amiga Files tab - pick the Workbench version to install.** Select the folder containing your ROMs. emu68hatcher will automatically look in the same folder for the Workbench ADF files, but you can also point it somewhere else. ROMs and ADFs are identified by hash, so the filenames don't matter.

4. **Emu68 tab - pick the HDMI output mode** for your monitor and the Emu68 release to bundle (1.0.7 stable for pistorm32-lite / classic, or 1.1.0-alpha.1 for PiStorm16 support).

5. **Software tab - enable/disable optional packages and pick the icon set** (GlowIcons on 3.2+, or Standard). Mandatory system packages are always included and not shown here. The first build downloads everything (with caching, subsequent builds are faster).

6. **Partitions tab - configure disk size and partition layout.** Default is 64 GB image with 4 GB Workbench partition and a "Work" partition. You can add/remove/resize partitions, drag the borders on the partition bar to resize them or type exact sizes.

7. **Output tab.** Pick destination folder and filename for the image file.

8. **Click "Build image".** On first run downloads a bunch of packages (uses cache after that). Progress and a build log are shown in the dialog. The log is also written to 'buildlog.txt' next to the output image.

9. **Flash the image to the SD card** - see [Flashing](flashing.md).

## Save / load configuration

You can save the current configuration to a JSON file via **Save config** (bottom left) and load it later with **Load config**.
