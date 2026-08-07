#!/usr/bin/env python3
"""Resolve official QGIS binary installer URLs for a stable release."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DOWNLOAD_ROOT = "https://download.qgis.org/downloads"


def resolve_packages(version: str) -> dict[str, dict[str, str]]:
    if VERSION_RE.fullmatch(version) is None:
        raise ValueError(f"Invalid QGIS release version: {version}")

    windows_name = f"QGIS-OSGeo4W-{version}-1.msi"
    macos_stem = f"qgis_pr_final-{version.replace('.', '_')}"
    return {
        "windows": {
            "name": windows_name,
            "url": f"{DOWNLOAD_ROOT}/{windows_name}",
            "checksum_url": f"{DOWNLOAD_ROOT}/{windows_name[:-4]}.sha256sum",
        },
        "macos": {
            "name": f"{macos_stem}.dmg",
            "url": f"{DOWNLOAD_ROOT}/macos/pr/{macos_stem}.dmg",
            "checksum_url": (
                f"{DOWNLOAD_ROOT}/macos/pr/{macos_stem}.sha256sum"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qgis-version", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    packages = resolve_packages(args.qgis_version)
    payload = json.dumps(packages, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")

    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            for platform, values in packages.items():
                for name, value in values.items():
                    stream.write(f"{platform}_{name}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
