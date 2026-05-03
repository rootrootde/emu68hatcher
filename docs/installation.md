# Install

## Requirements

- **macOS 12+** (Apple Silicon, possibly Intel) - the **.app** bundle includes Python, no separate install needed
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

    Download the latest **emu68hatcher-VERSION-macos-arm64.dmg** from the [releases](https://github.com/rootrootde/emu68hatcher/releases) page, open it and drag the **Emu68 Hatcher.app** into /Applications.

    !!! danger "If you see (you most likely will) &quot;Emu68 Hatcher.app is damaged and can&#39;t be opened. You should move it to the Trash.&quot;"
        **Do NOT click &quot;Move to Trash&quot;** - the app is fine, macOS just refuses to run anything that isn&#39;t notarized by an Apple Developer ID. Click **Cancel**, open Terminal and run:

        ```bash
        sudo xattr -dr com.apple.quarantine "/Applications/Emu68 Hatcher.app"
        ```

        'sudo' will ask for your admin/root password. Then launch the app normally - it should open from then on.

    !!! note "older macOS (Sonoma 14 and earlier)"
        On macOS up to Sonoma 14 you can also right-click the app → **Open** → **Open** and click through the &quot;unidentified developer&quot; dialog, or use **System Settings → Privacy & Security → Open Anyway** after the first blocked launch. On Sequoia (15) and later, those routes don&#39;t work for the &quot;damaged&quot; dialog - the terminal command above is the only fix.

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
        The installer is unsigned, so Windows SmartScreen will likely show a "Windows protected your PC" dialog on first run. Click **More info** → **Run anyway**.

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
