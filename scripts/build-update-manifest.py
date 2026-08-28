#!/usr/bin/env python3
"""Add the latest release artifacts to a manifest payload."""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from emu68hatcher.data.update_manifest import UpdateManifest

_ARTIFACT_RE = re.compile(
    r"^emu68hatcher-(?P<version>.+)-(?P<platform>"
    r"(?:windows|linux|macos)-(?:x64|arm64))\.(?:exe|deb|dmg)$"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_from_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data.get("release"), dict):
        return data["release"]
    return data


def _release_payload(release: dict, asset_dir: Path) -> dict:
    tag = release.get("tag_name", "")
    version = tag.removeprefix("v")
    release_url = release.get("html_url")
    if not version or not release_url:
        raise ValueError("release JSON has no tag_name or html_url")

    urls = {
        asset.get("name"): asset.get("browser_download_url")
        for asset in release.get("assets", [])
        if asset.get("name") and asset.get("browser_download_url")
    }
    artifacts = {}
    for path in sorted(asset_dir.iterdir()):
        if not path.is_file():
            continue
        match = _ARTIFACT_RE.fullmatch(path.name)
        if not match or match.group("version") != version:
            continue
        url = urls.get(path.name)
        if not url:
            raise ValueError(f"release JSON has no URL for {path.name}")
        artifacts[match.group("platform")] = {
            "url": url,
            "filename": path.name,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
    if not artifacts:
        raise ValueError(f"no installer artifacts found for {tag}")
    return {
        "version": version,
        "release_url": release_url,
        "artifacts": artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--release-json", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--revision", type=int)
    args = parser.parse_args()

    payload = json.loads(args.source.read_text(encoding="utf-8"))
    payload["revision"] = args.revision or int(time.time())
    payload["hatcher"] = _release_payload(_release_from_json(args.release_json), args.asset_dir)
    manifest = UpdateManifest.model_validate(payload)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n"
    args.output.write_text(content, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
