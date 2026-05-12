# Troubleshooting

## Emu68 Hatcher (host)

If the build itself fails (=errors during SD card creation), Emu68 Hatcher writes a **buildlog.txt** to the **output directory**, next to your **.img** file. Please attach it when reporting build issues, it helps a lot to speed things up!

### macOS: build fails with "Operation not permitted" on /dev/disk\*

The first-run dialog should have already set this up, but if **hst-imager** lost its Full Disk Access grant (macOS upgrade, hst-imager re-downloaded, you said Skip on the setup dialog), open **System Settings → Privacy & Security → Full Disk Access** and enable **hst-imager** in the list. If hst-imager isn't in the list yet, run a build once - the failed write triggers the entry to appear.

## AmigaOS / Workbench

When something goes wrong on the Amiga side, log output and error messages are essential for troubleshooting. The problem: how do you get that output from the Amiga into a Discord message or a GitHub issue? Writing it down by hand is tedious, taking photos of the screen isnt much better.

From version 0.1.1, Emu68 Hatcher writes the log output of some tools/scripts (like **Network Manager** and **Wifi Config**) to two places at once: the RAM disk (**RAM:**) and the **EMU68BOOT:** partition. That means that even if the system has crashed and reset itself, the logs can be read directly from the SD card on any PC or Mac.

The files live on the EMU68BOOT partition in the **Logs** folder.

### Currently available log files

- **EMU68BOOT:Logs/NetworkManager-\<timestamp\>.log** - from Network Manager
- **EMU68BOOT:Logs/WifiConfig-\<timestamp\>.log** - from Wifi Config

Issue tracker: <https://github.com/rootrootde/emu68hatcher/issues>
