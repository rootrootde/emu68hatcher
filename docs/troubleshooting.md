# Troubleshooting

## Emu68 Hatcher (host)

If the build itself fails (=errors during SD card creation), Emu68 Hatcher writes a **buildlog.txt** to the **output directory**, next to your **.img** file. Please attach it when reporting build issues, it helps a lot to speed things up!

## AmigaOS / Workbench

When something goes wrong on the Amiga side, log output and error messages are essential for troubleshooting. The problem: how do you get that output from the Amiga into a Discord message or a GitHub issue? Writing it down by hand is tedious, taking photos of the screen isnt much better.

From version 0.1.1, Emu68 Hatcher writes the log output of some tools/scripts (like **Network Manager** and **Wifi Config**) to two places at once: the RAM disk (**RAM:**) and the **EMU68BOOT:** partition. That means that even if the system has crashed and reset itself, the logs can be read directly from the SD card on any PC or Mac.

The files live on the EMU68BOOT partition in the **Logs** folder.

### Currently available log files

- **EMU68BOOT:Logs/NetworkManager-\<timestamp\>.log** - from Network Manager
- **EMU68BOOT:Logs/WifiConfig-\<timestamp\>.log** - from Wifi Config

Issue tracker: <https://github.com/rootrootde/emu68hatcher/issues>
