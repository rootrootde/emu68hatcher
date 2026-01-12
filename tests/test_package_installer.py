"""tests for PackageInstaller and YAML-based package installation"""

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


@pytest.fixture
def mock_extracted_dir(tmp_path):
    """create mock extracted package structure like MUI38"""
    extracted = tmp_path / "extracted"
    extracted.mkdir()

    # create MUI38 package structure matching real layout
    mui_pkg = extracted / "mui38"
    libs_dir = mui_pkg / "MUI" / "Libs"
    libs_dir.mkdir(parents=True)

    # create library files
    (libs_dir / "muimaster.library").write_text("muimaster library content")

    # create MUI subdirectory with classes (the key test for directory copying)
    mui_classes = libs_dir / "MUI"
    mui_classes.mkdir()
    (mui_classes / "Window.mui").write_text("window class content")
    (mui_classes / "Button.mui").write_text("button class content")
    (mui_classes / "Scrollbar.mui").write_text("scrollbar class content")

    # nested subdirectory to test deep recursion
    nested = mui_classes / "Nested"
    nested.mkdir()
    (nested / "deep.mui").write_text("deep nested content")

    # create another package for testing - DOpus
    dopus_pkg = extracted / "directory_opus"
    dopus_c = dopus_pkg / "DOpus" / "C"
    dopus_c.mkdir(parents=True)
    (dopus_c / "dopus").write_text("dopus executable")
    (dopus_c / "dopuscfg").write_text("dopus config tool")

    return extracted


@pytest.fixture
def mock_staging_dir(tmp_path):
    """create mock staging directory with device subdirs"""
    staging = tmp_path / "staging"
    (staging / "SDH0").mkdir(parents=True)
    (staging / "SDH1").mkdir(parents=True)
    (staging / "EMU68BOOT").mkdir(parents=True)
    return staging


@pytest.fixture
def mock_packages_dir(tmp_path):
    """create mock YAML package files"""
    packages = tmp_path / "packages"
    packages.mkdir()

    # MUI38 package (group is Libraries, not System, to test mandatory flag properly)
    mui_yaml = {
        "name": "mui38",
        "friendly_name": "MUI 3.8",
        "group": "Libraries",
        "description": "Magic User Interface",
        "versions": ["3.1", "3.2", "3.2.3"],
        "default": True,
        "download": {
            "source": "aminet",
            "path": "util/libs/mui38usr.lha",
        },
        "install": [
            {"from": "MUI/Libs/*", "to": "Libs/", "recursive": True},
        ],
    }
    with open(packages / "mui38.yaml", "w") as f:
        yaml.dump(mui_yaml, f)

    # DirectoryOpus package
    dopus_yaml = {
        "name": "directory_opus",
        "friendly_name": "Directory Opus",
        "group": "Applications",
        "description": "File Manager",
        "versions": ["3.1", "3.2", "3.2.3"],
        "download": {
            "source": "aminet",
            "path": "util/dopus/DOpus416JRbin.lha",
        },
        "install": [
            {"from": "DOpus/C/*", "to": "C/", "recursive": True},
        ],
    }
    with open(packages / "directory_opus.yaml", "w") as f:
        yaml.dump(dopus_yaml, f)

    # mandatory package
    mandatory_yaml = {
        "name": "test_mandatory",
        "friendly_name": "Test Mandatory",
        "group": "System",
        "description": "Required package",
        "versions": ["3.1", "3.2", "3.2.3"],
        "mandatory": True,
        "default": True,
        "download": {
            "source": "local",
            "path": "test.txt",
        },
        "install": [],
    }
    with open(packages / "test_mandatory.yaml", "w") as f:
        yaml.dump(mandatory_yaml, f)

    return packages


class TestPackageSchema:
    """tests for Package Pydantic schema"""

    def test_load_package_basic(self):
        """test loading a basic package"""
        from emu68hatcher.data.package_schema import Package, SourceType

        data = {
            "name": "test_pkg",
            "friendly_name": "Test Package",
            "group": "System",
            "description": "A test package",
            "versions": ["3.1", "3.2"],
            "mandatory": True,
            "download": {
                "source": "aminet",
                "path": "util/test.lha",
            },
            "install": [
                {"from": "*.library", "to": "Libs/"},
            ],
        }

        pkg = Package.model_validate(data)

        assert pkg.name == "test_pkg"
        assert pkg.versions == ["3.1", "3.2"]
        assert pkg.mandatory is True
        assert pkg.download.source == SourceType.AMINET
        assert len(pkg.install) == 1

    def test_package_github_source(self):
        """test GitHub source configuration"""
        from emu68hatcher.data.package_schema import Package, SourceType

        data = {
            "name": "github_pkg",
            "friendly_name": "GitHub Package",
            "group": "System",
            "description": "From GitHub",
            "download": {
                "source": "github",
                "repo": "owner/repo",
                "asset_pattern": ".*\\.lha",
            },
        }

        pkg = Package.model_validate(data)

        assert pkg.download.source == SourceType.GITHUB
        assert pkg.download.repo == "owner/repo"

    def test_package_matches_version(self):
        """test version matching"""
        from emu68hatcher.data.package_schema import Package

        data = {
            "name": "version_test",
            "friendly_name": "Version Test",
            "group": "System",
            "description": "Test",
            "versions": ["3.1", "3.2.3"],
        }

        pkg = Package.model_validate(data)

        assert pkg.matches_version("3.1") is True
        assert pkg.matches_version("3.2.3") is True
        assert pkg.matches_version("3.9") is False

    def test_package_no_version_matches_all(self):
        """test package with no versions matches all"""
        from emu68hatcher.data.package_schema import Package

        data = {
            "name": "universal",
            "friendly_name": "Universal",
            "group": "System",
            "description": "Works everywhere",
        }

        pkg = Package.model_validate(data)

        assert pkg.matches_version("3.1") is True
        assert pkg.matches_version("3.9") is True


class TestPackageLoader:
    """tests for YAML package loading"""

    def test_load_all_packages(self, mock_packages_dir, monkeypatch):
        """test loading all packages"""
        from emu68hatcher.data import package_loader

        # patch the packages directory
        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        packages = package_loader.load_all_packages()

        assert len(packages) == 3
        names = [p.name for p in packages]
        assert "mui38" in names
        assert "directory_opus" in names

    def test_get_packages_for_version(self, mock_packages_dir, monkeypatch):
        """test filtering packages by version"""
        from emu68hatcher.data import package_loader

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        packages = package_loader.get_packages_for_version("3.2.3")

        assert len(packages) == 3
        for pkg in packages:
            assert pkg.matches_version("3.2.3")

    def test_get_mandatory_packages(self, mock_packages_dir, monkeypatch):
        """test getting mandatory packages"""
        from emu68hatcher.data import package_loader

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        mandatory = package_loader.get_mandatory_packages("3.2.3")

        assert len(mandatory) == 1
        assert mandatory[0].name == "test_mandatory"

    def test_get_default_packages(self, mock_packages_dir, monkeypatch):
        """test getting default packages"""
        from emu68hatcher.data import package_loader

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        defaults = package_loader.get_default_packages("3.2.3")

        names = [p.name for p in defaults]
        assert "mui38" in names
        assert "test_mandatory" in names


class TestPackageInstallerBasics:
    """tests for basic PackageInstaller functionality"""

    def test_drive_mapping(self, mock_extracted_dir, mock_staging_dir, mock_packages_dir, monkeypatch):
        """test drive name to device mapping"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        assert installer.drive_map["System"] == "SDH0"
        assert installer.drive_map["Work"] == "SDH1"
        assert installer.drive_map["Emu68Boot"] == "EMU68BOOT"

    def test_get_mandatory_packages(
        self, mock_extracted_dir, mock_staging_dir, mock_packages_dir, monkeypatch
    ):
        """test getting mandatory packages"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        mandatory = installer.get_mandatory_packages()

        assert "test_mandatory" in mandatory

    def test_get_default_packages(
        self, mock_extracted_dir, mock_staging_dir, mock_packages_dir, monkeypatch
    ):
        """test getting default packages"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        defaults = installer.get_default_packages()

        assert "mui38" in defaults


class TestFileInstallation:
    """tests for file installation"""

    def test_install_single_file(self, tmp_path, monkeypatch):
        """test installing a single file"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.data.package_schema import Package, DownloadInfo, InstallRule, SourceType
        from emu68hatcher.builder.package_installer import PackageInstaller

        # setup directories
        extracted = tmp_path / "extracted"
        staging = tmp_path / "staging"
        packages = tmp_path / "packages"
        packages.mkdir()
        (staging / "SDH0" / "C").mkdir(parents=True)

        # create package with single file
        pkg_dir = extracted / "test_pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "testcmd").write_text("command content")

        # create YAML
        pkg_yaml = {
            "name": "test_pkg",
            "friendly_name": "Test Package",
            "group": "System",
            "description": "Test",
            "download": {"source": "web", "url": "http://example.com/test.lha"},
            "install": [{"from": "testcmd", "to": "C/"}],
        }
        with open(packages / "test_pkg.yaml", "w") as f:
            yaml.dump(pkg_yaml, f)

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", packages)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=staging,
            extracted_packages_dir=extracted,
        )

        count = installer.install_package("test_pkg")

        assert count == 1
        assert (staging / "SDH0" / "C" / "testcmd").exists()
        assert (staging / "SDH0" / "C" / "testcmd").read_text() == "command content"

    def test_install_with_glob_pattern(self, tmp_path, monkeypatch):
        """test glob pattern matching for files"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        # setup
        extracted = tmp_path / "extracted"
        staging = tmp_path / "staging"
        packages = tmp_path / "packages"
        packages.mkdir()
        (staging / "SDH0" / "Libs").mkdir(parents=True)

        pkg_dir = extracted / "lib_pkg" / "Libs"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "lib1.library").write_text("lib1")
        (pkg_dir / "lib2.library").write_text("lib2")
        (pkg_dir / "readme.txt").write_text("readme")  # should not match

        pkg_yaml = {
            "name": "lib_pkg",
            "friendly_name": "Library Package",
            "group": "System",
            "description": "Test",
            "download": {"source": "web", "url": "http://example.com/lib.lha"},
            "install": [{"from": "Libs/*.library", "to": "Libs/"}],
        }
        with open(packages / "lib_pkg.yaml", "w") as f:
            yaml.dump(pkg_yaml, f)

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", packages)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=staging,
            extracted_packages_dir=extracted,
        )

        count = installer.install_package("lib_pkg")

        assert count == 2
        assert (staging / "SDH0" / "Libs" / "lib1.library").exists()
        assert (staging / "SDH0" / "Libs" / "lib2.library").exists()
        assert not (staging / "SDH0" / "Libs" / "readme.txt").exists()


class TestDirectoryCopying:
    """tests for directory copying (the key fix)"""

    def test_install_copies_directories_recursively(
        self, mock_extracted_dir, mock_staging_dir, mock_packages_dir, monkeypatch
    ):
        """verify glob pattern copies subdirectories, not just files"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        count = installer.install_package("mui38")

        # should have installed the library file
        assert (mock_staging_dir / "SDH0" / "Libs" / "muimaster.library").exists()

        # CRITICAL: Should have installed the MUI subdirectory
        mui_classes = mock_staging_dir / "SDH0" / "Libs" / "MUI"
        assert mui_classes.exists(), "MUI subdirectory should be copied"
        assert mui_classes.is_dir()

        # and all its contents
        assert (mui_classes / "Window.mui").exists()
        assert (mui_classes / "Button.mui").exists()
        assert (mui_classes / "Scrollbar.mui").exists()

    def test_nested_directories_copied(
        self, mock_extracted_dir, mock_staging_dir, mock_packages_dir, monkeypatch
    ):
        """test that deeply nested directories are copied correctly"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        installer.install_package("mui38")

        # check nested directory was copied
        nested = mock_staging_dir / "SDH0" / "Libs" / "MUI" / "Nested"
        assert nested.exists(), "Nested subdirectory should be copied"
        assert (nested / "deep.mui").exists()

    def test_directory_contents_preserved(
        self, mock_extracted_dir, mock_staging_dir, mock_packages_dir, monkeypatch
    ):
        """test that all files in subdirectories are preserved"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        installer.install_package("mui38")

        # verify file contents are preserved
        mui_classes = mock_staging_dir / "SDH0" / "Libs" / "MUI"
        assert (mui_classes / "Window.mui").read_text() == "window class content"
        assert (mui_classes / "Button.mui").read_text() == "button class content"

    def test_existing_directory_merged(
        self, mock_extracted_dir, mock_staging_dir, mock_packages_dir, monkeypatch
    ):
        """test that existing directories are merged (not replaced) on install

        PFS3 is case-insensitive, so directory copies must merge to avoid
        data loss when archives use different casing than Workbench ADFs.
        """
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        # create pre-existing directory with additional content
        existing = mock_staging_dir / "SDH0" / "Libs" / "MUI"
        existing.mkdir(parents=True)
        (existing / "old_file.mui").write_text("old content")

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        installer.install_package("mui38")

        # existing file should be preserved (merge, not replace)
        assert (existing / "old_file.mui").exists()

        # new files should also exist
        assert (existing / "Window.mui").exists()

    def test_case_insensitive_directory_merge(self, tmp_path):
        """directories differing only by case must merge via resolve_staging_path

        workbench ADFs use 'Classes/Gadgets/' while some packages use
        'Classes/gadgets/'. on a case-sensitive host FS these are separate
        directories, but PFS3 is case-insensitive so they must be merged.
        """
        from emu68hatcher.builder.amiga_files import resolve_staging_path

        staging = tmp_path / "staging" / "SDH0"
        staging.mkdir(parents=True)

        # simulate workbench extraction creating uppercase directory
        gadgets_dir = staging / "Classes" / "Gadgets"
        gadgets_dir.mkdir(parents=True)
        (gadgets_dir / "layout.gadget").write_text("layout")
        (gadgets_dir / "button.gadget").write_text("button")

        # resolve same-case path - must find the existing dir
        resolved = resolve_staging_path(staging, "Classes/Gadgets")
        assert resolved.exists()
        assert resolved.samefile(gadgets_dir)

        # resolve lowercase path - must resolve to the same physical dir
        resolved_lower = resolve_staging_path(staging, "classes/gadgets")
        assert resolved_lower.exists()
        assert resolved_lower.samefile(gadgets_dir)

        # write via resolved lowercase path - file must land in existing dir
        target = resolve_staging_path(
            staging, "Classes/gadgets/progress.gadget"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("progress")

        # all files should be accessible from the original directory
        assert (gadgets_dir / "layout.gadget").exists()
        assert (gadgets_dir / "button.gadget").exists()
        assert (gadgets_dir / "progress.gadget").exists()


class TestScriptModifications:
    """tests for script modification"""

    def test_script_modifications_queued(
        self, mock_extracted_dir, mock_staging_dir, tmp_path, monkeypatch
    ):
        """test script modifications are queued correctly"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        packages = tmp_path / "packages"
        packages.mkdir()

        pkg_yaml = {
            "name": "script_test",
            "friendly_name": "Script Test",
            "group": "System",
            "description": "Test",
            "download": {"source": "local", "path": "test"},
            "scripts": [
                {
                    "target": "S/User-Startup",
                    "action": "append",
                    "content": "; Test content\nEcho Hello",
                }
            ],
        }
        with open(packages / "script_test.yaml", "w") as f:
            yaml.dump(pkg_yaml, f)

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", packages)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        installer.install_package("script_test")

        assert len(installer.pending_scripts) == 1
        pkg, mod = installer.pending_scripts[0]
        assert mod.target == "S/User-Startup"
        assert "Test content" in mod.content


class TestPackageDownloadability:
    """tests that mandatory packages are configured for reliable download"""

    def test_mandatory_aminet_packages_have_direct_path(self):
        """mandatory Aminet packages must have a direct path, not just search

        aminet search-based downloads silently fail (the code just logs
        "needs resolution" and skips). if a mandatory package like iconlib
        only has search:, its files never get installed. for optional packages
        this is tolerable; for mandatory ones it causes boot failures.

        regression test for: WB 3.1 boot failing with "please insert volume
        containing LIBS/icon.library" because iconlib used search: instead
        of path: and the download was silently skipped.
        """
        from emu68hatcher.data.package_loader import load_all_packages
        from emu68hatcher.data.package_schema import SourceType

        packages = load_all_packages()
        assert len(packages) > 0

        failures = []
        for pkg in packages:
            if not pkg.mandatory:
                continue
            if not pkg.download or pkg.download.source != SourceType.AMINET:
                continue
            if not pkg.download.path:
                failures.append(
                    f"{pkg.name}: mandatory Aminet package has no direct path "
                    f"(only search={pkg.download.search!r})"
                )

        assert not failures, (
            "Mandatory Aminet packages must use path: (not search:) "
            "because search-based downloads silently fail:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )


class TestPackageInstallation:
    """integration tests for full package installation"""

    def test_install_package_full(
        self, mock_extracted_dir, mock_staging_dir, mock_packages_dir, monkeypatch
    ):
        """test installing a complete package"""
        from emu68hatcher.data import package_loader
        from emu68hatcher.builder.package_installer import PackageInstaller

        monkeypatch.setattr(package_loader, "_PACKAGES_DIR", mock_packages_dir)

        installer = PackageInstaller(
            kickstart_version="3.2.3",
            staging_dir=mock_staging_dir,
            extracted_packages_dir=mock_extracted_dir,
        )

        count = installer.install_package("mui38")

        # should have installed files
        assert count > 0

        # MUI classes directory should exist (key fix verification)
        mui_dir = mock_staging_dir / "SDH0" / "Libs" / "MUI"
        assert mui_dir.exists()
