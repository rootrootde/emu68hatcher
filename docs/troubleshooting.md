# Troubleshooting

## Emu68 Hatcher (host)

If the build itself fails (=errors during SD card creation), Emu68 Hatcher writes a **buildlog.txt** to the **output directory**, next to your **.img** file. Please attach it when reporting build issues, it helps a lot to speed things up!

### macOS: build fails with "Operation not permitted" on /dev/disk\*

hst-imager needs Full Disk Access. See [Installation → macOS](installation.md#macos).

## AmigaOS / Workbench

The Amiga-side scripts (Tools menu, **SYS:Utilities/Network Config**, ...) run in a CON window that stays open after the script exits, so the output can be read or copied before closing it.

Issue tracker: <https://github.com/rootrootde/emu68hatcher/issues>
