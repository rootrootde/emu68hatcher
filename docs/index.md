# <img src="assets/emu-icon.svg" width="96" height="96" alt="logo"> Emu68 Hatcher

Build ready-to-run SD cards with pre-configured Workbench installation (+batteries included) for [PiStorm](https://github.com/captain-amygdala/pistorm)-accelerated Amigas. 

Runs on macOS, Linux and Windows.

<img src="assets/screenshot_macos.png" alt="Emu68 Hatcher main window (macOS, light + dark)" width="600">

- Bootable Emu68 install for pistorm32-lite, pistorm, pistorm16
- Workbench install from stock ADFs (3.1 / 3.2 / 3.2.2.1 / 3.2.3)
- Customizable package set: MUI, WHDLoad+WHDLoadWrapper, IBrowse, HippoPlayer, ...
- RTG via Picasso96 (shareware driver)
- Network support: Roadshow TCP/IP stack (demo), wifipi (wifi) + genet (ethernet) drivers, config tools
- Partition layout editor (PFS3 + FFS)
- Build configs as JSON (save / load)
- Build to **.img** file (sparse by default), flash to SD card after build, or write straight to SD card

## Known issues / limitations

**Still in an early stage** - Only actively tested on my A1200 + pistorm32-lite + CM4 / on macOS. If you run it on different hardware or OS, let me know on the [Discord](https://discord.com/invite/ApTbasXJPE) or open a [GitHub issue](https://github.com/rootrootde/emu68hatcher/issues) - even just "it worked" is useful.

- **Workbench 3.9 not supported yet**
- **No framethrower / unicam configuration yet**
- **mostly tested on 3.2(.3)** - expect more potential issues with 3.1

## Support + Feedback

For questions, feedback, bug reports, feature requests, and project updates:

[Join the Discord](https://discord.com/invite/ApTbasXJPE){ .md-button .md-button--primary }

!!! warning "Please don't ask for support on other Amiga Discord servers"
    I won't be able to keep up with multiple channels, and the Emu68 Hatcher server is a better place for discussions plus I can post updates there more frequently.

[Open a GitHub issue](https://github.com/rootrootde/emu68hatcher/issues){ .md-button }

!!! tip "Reporting an error"
    Attaching the right log file makes debugging way easier. See [Troubleshooting](troubleshooting.md) for which file to grab depending on whether the build itself failed or something went wrong on the AmigaOS side.

## Credits

Thanks to:

- [mja65](https://github.com/mja65)'s fantastic work on the [Emu68 Imager](https://github.com/mja65/Emu68-Imager-Software) project
- [Emu68](https://github.com/michalsc/Emu68) and [Emu68-tools](https://github.com/michalsc/Emu68-tools) by Michal Schulz (MPL-2.0) - m68k emulation and the on-Amiga companion tools (EmuControl, VideoCore.card, WiFiPi.device, ...)
- [hst-imager](https://github.com/henrikstengaard/hst-imager) and [hst-amiga](https://github.com/henrikstengaard/hst-amiga) by Henrik Stengaard (MIT) - disk image + RDB tooling

Bundled / downloaded at build time:

- [WHDLoad](http://whdload.de/)
- [Roadshow Demo](https://www.amigashop.org/product_info.php?cPath=2_34&products_id=200&language=de) bundled with permission from A. Magerl (APC&TCP)
- [7-Zip](https://github.com/ip7z/7zip) (GNU LGPL) - downloaded at install time, License.txt copied alongside the binary
- Aminet packages (MUI, HippoPlayer, IBrowse, akDatatypes, Picasso96, ...) - downloaded from [aminet.net](https://aminet.net) at build time; each ships its own readme with license