# Troubleshooting

## Emu68 Hatcher (host)

If the build itself fails (=errors during SD card creation), Emu68 Hatcher writes a **buildlog.txt** to the **output directory**, next to your **.img** file. For direct-to-SD-card builds (no image file) it lands in the app's cache directory instead - the exact path is printed near the top of the build log window. Please attach it when reporting build issues, it helps a lot to speed things up!

### macOS: build fails with "Operation not permitted" on /dev/disk\*

hst-imager needs Full Disk Access. See [Installation → macOS](installation.md#macos).

### Corrupted downloads or tools

**Reset App Data** on the Start tab deletes all cached downloads, temporary files and downloaded tools - everything is re-downloaded on the next build. Saved build configs are not touched.

## AmigaOS / Workbench

The Amiga-side tools run in CON windows: **SYS:Utilities/Network Config** keeps its window open after it exits so the output can be read or copied, while the Connect WiFi / Connect Ethernet launchers close their window automatically when they finish.

Issue tracker: <https://github.com/rootrootde/emu68hatcher/issues>
