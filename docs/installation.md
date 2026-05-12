# Install

## Requirements

- **macOS 12+** (Apple Silicon or Intel) - the **.app** bundle includes Python, no separate install needed
- **Windows 10/11** (x64 or arm64) - the **.exe** installer includes Python, no separate install needed
- **Linux** (recent Ubuntu/Debian, Fedora, Arch, …) - **.deb** installer for Debian/Ubuntu (x64 / arm64), manual Python install everywhere else
- **a SD card**, 4 GB minimum, 32+ GB recommended
- **a Kickstart ROM** + **Workbench ADF floppy images** (3.1 / 3.2 / 3.2.2.1 / 3.2.3 - pick one):

| Workbench | Kickstart (A1200) |
|---|---|
| 3.1 | 40.068 (or Cloanto 45.064 / 45.066 from Amiga Forever) |
| 3.2 | 47.96 |
| 3.2.2.1 | 47.111 |
| 3.2.3 | 47.115 |

## Pick your OS

=== "macOS"

    <a id="macos"></a>

    ### Native installer (recommended)

    Download the latest **emu68hatcher-VERSION-macos-arm64.dmg** (Apple Silicon) or **emu68hatcher-VERSION-macos-x64.dmg** (Intel) from the [releases](https://github.com/rootrootde/emu68hatcher/releases) page, open it and drag **Emu68 Hatcher.app** into /Applications.

    !!! warning "First run: grant Full Disk Access to hst-imager"
        Open the app, click **Download Missing Tools** on the Start tab. After **hst-imager** downloads, a dialog asks to register it with macOS - click **Set Up Now**, enter your password, then enable **hst-imager** in the **Full Disk Access** list that opens. This is a one-time step and required: without it, SD card writes fail with a permission error.

    ### Install from source

    Needs Python 3.10+. Get the source tarball from the [releases](https://github.com/rootrootde/emu68hatcher/releases) page (or git clone the repository) then run **bootstrap.py**:

    ```bash
    # from a release tarball
    tar xf emu68hatcher-<version>.tar.gz && cd emu68hatcher-<version>

    # or from git
    git clone https://github.com/rootrootde/emu68hatcher.git && cd emu68hatcher

    python3 bootstrap.py
    emu68hatcher
    ```

=== "Linux"

    ### Native installer (Debian / Ubuntu)

    Download the latest **emu68hatcher-VERSION-linux-x64.deb** (or **-arm64.deb** on an ARM machine) from the [releases](https://github.com/rootrootde/emu68hatcher/releases) page and install:

    ```bash
    sudo apt install ./emu68hatcher-*-linux-*.deb
    ```

    Then run **emu68hatcher** to launch the GUI.

    !!! note "other Linux distros"
        No RPM or AUR packages available yet. On Fedora / openSUSE / Arch, use the manual install below.

    ### Install from source

    Needs Python 3.10+. Grab the source tarball from the [releases](https://github.com/rootrootde/emu68hatcher/releases) page (or **git clone** the repo if you'd rather), then run **bootstrap.py**:

    ```bash
    # from a release tarball
    tar xf emu68hatcher-<version>.tar.gz && cd emu68hatcher-<version>

    # or from git
    git clone https://github.com/rootrootde/emu68hatcher.git && cd emu68hatcher

    python3 bootstrap.py
    emu68hatcher
    ```


=== "Windows"

    !!! info "Consider using Emu68 Imager"
        Apart from testing, there's really no reason for Windows users not to use [Emu68 Imager](https://github.com/mja65/Emu68-Imager-Software) which is considerably more mature and well tested!!

    ### Native installer (recommended)

    Download the latest **emu68hatcher-VERSION-windows-x64.exe** (or **-arm64.exe** on a Windows ARM machine) from the [releases](https://github.com/rootrootde/emu68hatcher/releases) page and run it. The installer puts the app + bundled Python in **C:\Program Files\Emu68 Hatcher\\** and adds a Start menu entry

    !!! note "SmartScreen"
        On first run Windows SmartScreen may show a "Windows protected your PC" dialog. Click **More info** → **Run anyway**.

    ### Install from source

    Needs Python 3.10+ from [python.org](https://www.python.org/downloads/) (tick **Add Python to PATH** during install). Grab the source tarball from the [releases](https://github.com/rootrootde/emu68hatcher/releases) page (or **git clone** the repo if you'd rather), then run **bootstrap.py**:

    ```powershell
    # from a release tarball (Windows 10+ has tar built in)
    tar xf emu68hatcher-<version>.tar.gz; cd emu68hatcher-<version>

    # or from git
    git clone https://github.com/rootrootde/emu68hatcher.git; cd emu68hatcher

    python bootstrap.py
    emu68hatcher
    ```
