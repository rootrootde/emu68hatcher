from emu68hatcher.data.package_loader import get_local_packages_dir


def test_firstboot_does_not_open_env_as_a_volume():
    startup = get_local_packages_dir() / "System" / "S" / "Startup-Sequence_FirstBoot"
    assert ">ENV:" not in startup.read_text(encoding="iso-8859-1")
