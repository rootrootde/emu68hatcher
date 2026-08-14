"""TCP/IP stack and wireless configuration."""

from __future__ import annotations

import base64
import hashlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from emu68hatcher.builder.errors import BuildError
from emu68hatcher.config.schema import NetworkStack
from emu68hatcher.data.package_loader import get_local_packages_dir

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow

_MANAGED_TAG = "# emu68hatcher: managed by Network Config"
_MIAMI_PROFILE_HASHES = {
    "Genet.default": "2c0798ace1242d2023921cdcb137c59a43c288c253bd2f3e50c3fe872fad543e",
    "Genet.default.info": "16bb164496e0103d283012f96385f40a336cf99f14dbf4dba611124af76bce12",
    "Uaenet.default": "d704a8c7005146dac7c03d8c19138d2ea0151a89630f2de299855cfc6102e22a",
    "Uaenet.default.info": "660fa90fd0342b7d873ccf99bcca0bd044e422283c6366c3d18a34118e4b46d3",
    "Wifipi.default": "7e4f0047d17e35a71f6a7bf54d0a08e34f00df9e74e5e82718fa2182613cfd9e",
    "Wifipi.default.info": "48d1ba993376ebead20041845c45e4d30ebdc94aa8ce45082ce5b63965db0c19",
}
_MIAMI_KEY_SIZES = {"MIAMI.KEY1": 2048, "MIAMI.KEY2": 2048, "MIAMIDX.KEY": 4096}


def generate_wireless_prefs(ssid: str, password: str) -> str:
    body = f'   ssid="{_wpa_escape(ssid)}"\n'
    body += f'   psk="{_wpa_escape(password)}"\n' if password else "   key_mgmt=NONE\n"
    body += "   scan_ssid=1\n"
    return f"network={{\n{body}}}\n"


def configure_network(workflow: BuildWorkflow, boot_staging: Path) -> None:
    if workflow.config.network_stack == NetworkStack.MIAMIDX:
        _configure_miamidx(workflow, boot_staging)
        return
    _configure_roadshow(workflow, boot_staging)


def _configure_roadshow(workflow: BuildWorkflow, boot_staging: Path) -> None:
    network = workflow.config.network
    devs = boot_staging / "Devs"
    for name, settings in (("genet", network.ethernet), ("wifipi", network.wifi)):
        path = devs / "NetInterfaces" / name
        if not path.exists():
            workflow.logger.warning(f"NetInterfaces/{name} not staged; skipping its IP config")
            continue
        _write_netinterface(
            path,
            settings.mode.value,
            settings.address,
            settings.netmask,
        )
    if network.gateway:
        _write_default_route(devs / "Internet" / "routes", network.gateway)
    if network.dns_servers:
        _write_name_resolution(devs / "Internet" / "name_resolution", network.dns_servers)
    workflow.logger.info(
        f"Configured network: ethernet={network.ethernet.mode.value} "
        f"wifi={network.wifi.mode.value} gateway={network.gateway or '-'} "
        f"dns={network.dns_servers or '-'}"
    )


def _configure_miamidx(workflow: BuildWorkflow, boot_staging: Path) -> None:
    source_dir = get_local_packages_dir() / "System" / "Programs" / "Miami"
    target_dir = boot_staging / "Programs" / "Miami"
    target_dir.mkdir(parents=True, exist_ok=True)

    for filename, expected_hash in _MIAMI_PROFILE_HASHES.items():
        encoded_path = source_dir / f"{filename}.b64"
        try:
            encoded = "".join(encoded_path.read_text(encoding="ascii").split())
            profile = base64.b64decode(encoded, validate=True)
        except (OSError, ValueError) as exc:
            raise BuildError(f"MiamiDX profile is invalid: {encoded_path.name}: {exc}") from exc
        if hashlib.sha256(profile).hexdigest() != expected_hash:
            raise BuildError(f"MiamiDX profile checksum mismatch: {encoded_path.name}")
        (target_dir / filename).write_bytes(profile)

    copied_keys = _copy_miamidx_keys(
        workflow.config.miamidx_key_directory,
        target_dir,
        workflow.logger,
    )
    key_status = f", {copied_keys} registration key(s)" if copied_keys else ""
    workflow.logger.info(f"Configured MiamiDX DHCP profiles{key_status}")


def _copy_miamidx_keys(source_dir: Path | None, target_dir: Path, logger) -> int:
    if source_dir is None:
        return 0
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        logger.warning(f"MiamiDX keys folder not found: {source_dir}")
        return 0

    entries = {entry.name.upper(): entry for entry in source_dir.iterdir() if entry.is_file()}
    copied = 0
    for filename, expected_size in _MIAMI_KEY_SIZES.items():
        source = entries.get(filename)
        if source is None:
            continue
        if source.stat().st_size != expected_size:
            logger.warning(
                f"Ignoring {source.name}: expected {expected_size} bytes, "
                f"got {source.stat().st_size}"
            )
            continue
        shutil.copyfile(source, target_dir / filename)
        copied += 1
    if not copied:
        logger.warning(f"No valid MiamiDX registration keys found in {source_dir}")
    return copied


def _wpa_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_netinterface(
    path: Path,
    mode: str,
    address: str | None,
    netmask: str | None,
) -> None:
    kept: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="iso-8859-1").splitlines():
            stripped = line.strip()
            key = stripped.split("=", 1)[0].strip().lower() if stripped[:1] not in ("", "#") else ""
            if key not in ("configure", "address", "netmask", "gateway"):
                kept.append(line)
    kept.append(_MANAGED_TAG)
    if mode == "static" and address and netmask:
        kept += [f"address={address}", f"netmask={netmask}"]
    else:
        kept.append("configure=dhcp")
    _write_lines(path, kept)


def _write_default_route(path: Path, gateway: str) -> None:
    kept: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="iso-8859-1").splitlines():
            stripped = line.strip()
            if stripped[:1] not in ("", "#") and stripped.split()[0].lower() == "default":
                continue
            kept.append(line)
    _write_lines(path, [*kept, _MANAGED_TAG, f"default {gateway}"])


def _write_name_resolution(path: Path, dns_servers: list[str]) -> None:
    _write_lines(path, [_MANAGED_TAG, *(f"nameserver {ip}" for ip in dns_servers)])


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="iso-8859-1", newline="\n")
