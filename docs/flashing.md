# Flashing SD cards

The build output is a plain disk image. Use any general-purpose SD card writer to flash it:

- [balena Etcher](https://etcher.balena.io/) - macOS, Linux, Windows
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/) - macOS, Linux, Windows (use "Use custom" → select the '.img')
- 'dd' / 'pv' directly on Linux/macOS for the command-line crowd

!!! danger "Double-check the target!"
    Whichever tool you use, verify the target device twice before confirming. **Picking the wrong disk will wipe it** - including your system disk.
