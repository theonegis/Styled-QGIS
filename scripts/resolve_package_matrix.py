#!/usr/bin/env python3
"""Create the small cross-platform binary repackaging matrix."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PLATFORMS = {
    "windows": {
        "platform": "windows",
        "name": "Windows x64 installer",
        "os": "windows-2022",
        "arch": "x64",
        "package_host": "windows",
        "artifact": "QGISPlus-Windows-x64",
    },
    "macos_intel": {
        "platform": "macos-intel",
        "name": "macOS Intel DMG",
        "os": "macos-15-intel",
        "arch": "x86_64",
        "package_host": "mac",
        "artifact": "QGISPlus-macOS-Intel",
    },
    "macos_arm64": {
        "platform": "macos-arm64",
        "name": "macOS Apple Silicon DMG",
        "os": "macos-15",
        "arch": "arm64",
        "package_host": "mac",
        "artifact": "QGISPlus-macOS-Apple-Silicon",
    },
}


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"Expected true or false, received {value!r}")
    return normalized == "true"


def resolve_matrix(
    event_name: str,
    build_windows: str,
    build_macos_intel: str,
    build_macos_arm64: str,
) -> dict[str, list[dict[str, str]]]:
    if event_name == "workflow_dispatch":
        selected = {
            "windows": _boolean(build_windows),
            "macos_intel": _boolean(build_macos_intel),
            "macos_arm64": _boolean(build_macos_arm64),
        }
    else:
        selected = {name: True for name in PLATFORMS}
    include = [PLATFORMS[name] for name in PLATFORMS if selected[name]]
    if not include:
        raise ValueError("At least one platform must be selected")
    return {"include": include}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--build-windows", default="true")
    parser.add_argument("--build-macos-intel", default="true")
    parser.add_argument("--build-macos-arm64", default="true")
    parser.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"])
        if os.environ.get("GITHUB_OUTPUT")
        else None,
    )
    args = parser.parse_args()
    try:
        matrix = resolve_matrix(
            args.event_name,
            args.build_windows,
            args.build_macos_intel,
            args.build_macos_arm64,
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    rendered = json.dumps(matrix, separators=(",", ":"))
    print(rendered)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"package_matrix={rendered}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
