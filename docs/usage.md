# Usage

## Build an image

1. **Launch the app.** It will check whether some required tools are installed.

2. **Start tab - install missing tools.** If required tools are shown as missing, click **Download Missing Tools** and wait for green checkmarks.

3. **Amiga Files tab - pick the Workbench version, icon set, and languages.** Add one or more directories that contain your Kickstart ROMs and Workbench ADFs. Click **Add...** to point at a folder; the list re-scans after each add/remove. Files are identified by hash, so filenames don't matter. Pick the **icon set** (GlowIcons on 3.2+, or Standard) next to the Workbench version, and tick any **language** disks you want installed. **Show details...** opens a tabbed view of what was detected: the boot ROM picked, the WHDLoad ROM inventory that gets staged to **DEVS:Kickstarts/**, and the per-ADF breakdown. Automatic ROM selection follows Emu68 Imager and prefers a matching A1200 ROM when available; this does not restrict the image to A1200 hardware. For **AmigaOS 3.9**, add your OS 3.9 CD image (**.iso**, do not mount it) and a Kickstart 3.1 ROM instead of ADFs - the BoingBag updates download automatically.

4. **Emu68 tab - select the Emu68 release and boot behaviour.** Pick 1.0.7 stable for pistorm32-lite / classic or 1.1.0-alpha.1 for PiStorm16 support and the consolidated Pi4/CM4 driver stack. The basic view contains the CM4 antenna and storage timing. **Show Advanced** adds boot, memory, storage, compatibility, bus-test, and manual override settings. The right pane shows the generated **config.txt** and **cmdline.txt**, including values from the Display and Software tabs. With one-time diagnostics enabled, the affected file is split into first-boot and later-boot previews; the BAK file replaces the active file after the first boot.

5. **Display tab - configure HDMI and Workbench output.** Pick the Pi HDMI mode and Workbench screen mode, choose the Picasso96 source, and configure Framethrower / Unicam. A VideoCore Workbench mode is written to **ScreenMode.prefs** during the build; native mode keeps the first-boot screen mode setup. Framethrower requires a VideoCore mode. **Show Advanced** contains the HDMI hotplug setting.

6. **Software tab - enable/disable optional packages.** Pick MUI 3.8 or 5.0, plus any applications and commodities you want. Mandatory system packages are always included and not shown here. The first build downloads everything (with caching, subsequent builds are faster).

7. **Network tab - set up TCP/IP (optional).** Choose Roadshow, MiamiDX, or AmiTCP_NG. Roadshow uses the bundled demo unless you select your own **Roadshow.lha**. Roadshow and AmiTCP_NG support DHCP or static addresses, DNS, and a default gateway. MiamiDX installs its main and MUI archives from Aminet with DHCP profiles for genet, wifipi, and uaenet. Its optional registration folder must contain **MIAMI.KEY1**, **MIAMI.KEY2**, and **MIAMIDX.KEY** together. Enter WiFi credentials for the selected stack. Networking starts from the **Connect WiFi** or **Connect Ethernet** Workbench tools; MiamiDX does not connect automatically at boot.

8. **Output tab.** Pick how to deliver the build:
    - **Image file** - writes a regular **.img** file to disk. Sparse files are enabled by default, so a large image only uses as much disk space as the actual data.
    - **Image file + flash to SD card** - same as above, then writes the image to the SD card you pick block-by-block. Requires admin/sudo. Faster for large builds: file copy hits local-disk speed and the SD card is only written once at hardware speed.
    - **Direct to SD card** - skips the **.img** file and writes each Amiga file through hst-imager's PFS3 layer over the SD card interface. Useful when you don't need to keep the image around, but several times slower than the image+flash path once partitions get into multi-GB territory.

    !!! danger "Double-check the target!"
        **Picking the wrong disk will wipe it.** Emu68 Hatcher will refuse to write to mounted root partitions (=your operating system) but has no problem with wiping anything else you have connected.

9. **Partitions tab - configure disk size and partition layout.** Default is an 8 GB image with a ~512 MB Workbench partition (disk size / 15) and a "Work" partition filling the rest. You can add/remove/resize partitions, drag the borders on the partition bar to resize them or type exact sizes. With an SD card selected on the Output tab, the disk size matches the card.

    Selecting a partition shows an **Extra content directory** picker below the table. Point it at a local folder and its contents get mirrored into that partition during the build (e.g. pre-load a Work partition with WHDLoad games, demos, or backups). The extras mirror runs last, so any file you drop in there overrides the generated one.

10. **Click "Build image".** On first run downloads a bunch of packages (uses cache after that). Progress and a build log are shown in the dialog. The log is also written to **buildlog.txt** next to the output image.

Both flashing modes prompt for admin access once at the start of the build. After a flash completes, an **Eject** button lets you safely remove the card (macOS / Linux). On macOS, full disk access for hst-imager must be granted/setup on first install - see [Installation](installation.md#macos).

## Save / load configuration

You can save the current configuration to a JSON file via **Save Config...** (bottom left) and load it later with **Load Config...**.
