# Usage

## Build an image

1. **Launch the app.** It checks tools, updates and the package list.

2. **Start tab.** Download missing or outdated tools. App updates go to Downloads and can be opened after verification; on Linux this needs a Debian-based system.

    [![Start tab with installed tools and update status](assets/screenshot_macos.png)](assets/screenshot_macos.png){ target="_blank" }

3. **Amiga Files tab.** Add folders with a Kickstart ROM and Workbench ADFs, then pick version, icon set and languages. Files are matched by hash; **Show details...** lists what was found. AmigaOS 3.9 uses the CD **.iso** and a Kickstart 3.1 ROM instead. GlowIcons needs its matching ADF.

    [![Amiga Files tab with a detected Workbench 3.2.3 set](assets/screenshots/amiga-files.png)](assets/screenshots/amiga-files.png){ target="_blank" }

4. **Emu68 tab.** Pick 1.0.7 stable or 1.1.0-beta.1 and set boot options. The right side previews **config.txt** and **cmdline.txt**; more settings are under **Show Advanced**.

    [![Emu68 tab with release selection and generated boot files](assets/screenshots/emu68.png)](assets/screenshots/emu68.png){ target="_blank" }

5. **Display tab.** Set HDMI and Workbench modes, Picasso96, Framethrower and Unicam. Use **Browse...** for your own full **Picasso96.lha**.

    [![Display tab with HDMI, Workbench and Framethrower settings](assets/screenshots/display.png)](assets/screenshots/display.png){ target="_blank" }

6. **Software tab.** Select optional software and a MUI version. The list is filtered for the chosen Workbench and Emu68 versions. See [Packages](packages.md) for all packages.

    [![Software tab with package groups](assets/screenshots/software.png)](assets/screenshots/software.png){ target="_blank" }

7. **Network tab.** Choose Roadshow, MiamiDX or AmiTCP_NG and enter DHCP, static or wifi settings. Roadshow archives and MiamiDX registration files can be supplied here. Connections start from the Workbench tools.

    [![Network tab with Roadshow and DHCP selected](assets/screenshots/network.png)](assets/screenshots/network.png){ target="_blank" }

8. **Output tab.** Pick how to deliver the build:

    - **Image file** - writes a sparse **.img**.
    - **Image file + flash to SD card** - keeps the image and then flashes it; fastest for large builds.
    - **Direct to SD card** - skips the image, but is slower with large partitions.

    !!! danger "Double-check the target!"
        **Picking the wrong disk will wipe it.** Emu68 Hatcher will refuse to write to mounted root partitions (=your operating system) but has no problem with wiping anything else you have connected.

    [![Output tab set to build an image and flash it to SD](assets/screenshots/output.png)](assets/screenshots/output.png){ target="_blank" }

9. **Partitions tab.** Add or resize partitions and optional extra-content folders. Default is a 64 GB image with 1 GB **EMU68BOOT**, about 1/15 for Workbench and **Work** using the rest. FAT32 and RDB use two MBR entries; the listed Amiga partitions are inside the RDB.

    Extra content is copied last and can overwrite generated files.

    [![Partitions tab with three Amiga partitions](assets/screenshots/partitions.png)](assets/screenshots/partitions.png){ target="_blank" }

10. **Click "Build Image".** The first build downloads packages; later builds use the cache. The dialog and **buildlog.txt** contain the build log.

Flashing asks for admin access. On macOS, hst-imager also needs Full Disk Access; see [Installation](installation.md#macos).

## Save / load configuration

Use **Save Config...** and **Load Config...** for JSON configs. wifi credentials are not saved.
