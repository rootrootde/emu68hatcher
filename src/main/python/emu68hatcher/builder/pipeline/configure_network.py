"""Roadshow and wireless configuration."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emu68hatcher.builder.workflow import BuildWorkflow

_MANAGED_TAG = "# emu68hatcher: managed by Network Config"


def generate_wireless_prefs(ssid: str, password: str) -> str:
    body = f'   ssid="{_wpa_escape(ssid)}"\n'
    body += f'   psk="{_wpa_escape(password)}"\n' if password else "   key_mgmt=NONE\n"
    body += "   scan_ssid=1\n"
    return f"network={{\n{body}}}\n"


def configure_network(workflow: BuildWorkflow, boot_staging: Path) -> None:
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
