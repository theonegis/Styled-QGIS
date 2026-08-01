#!/usr/bin/env python3
"""Resolve releases, shallow-clone upstream sources, and patch QGIS."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from apply_qgis_patch import patch_cmake, patch_main, patch_windows_triplet
from resolve_versions import Release, resolve


def _clone(repository: str, tag: str, destination: Path) -> None:
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise RuntimeError(f"{destination} exists and is not a Git checkout")
        current = subprocess.run(
            ["git", "-C", str(destination), "describe", "--tags", "--exact-match"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if current != tag:
            raise RuntimeError(
                f"{destination} is {current}, expected {tag}; use a clean output folder"
            )
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            tag,
            f"https://github.com/{repository}.git",
            str(destination),
        ],
        check=True,
    )


def _pinned_release(repository: str, tag: str) -> Release:
    version = tag.removeprefix("final-").removeprefix("v").replace("_", ".")
    return Release(repository, tag, version, "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("upstream"))
    parser.add_argument("--qgis-tag")
    parser.add_argument("--qlementine-tag")
    parser.add_argument("--qgis-major", type=int, default=4)
    args = parser.parse_args()

    try:
        if args.qgis_tag and args.qlementine_tag:
            releases = {
                "qgis": _pinned_release("qgis/QGIS", args.qgis_tag),
                "qlementine": _pinned_release(
                    "oclero/qlementine", args.qlementine_tag
                ),
            }
        elif args.qgis_tag or args.qlementine_tag:
            raise RuntimeError("Both --qgis-tag and --qlementine-tag are required")
        else:
            releases = resolve(args.qgis_major)

        output = args.output.resolve()
        qgis_source = output / "QGIS"
        qlementine_source = output / "qlementine"
        _clone("qgis/QGIS", releases["qgis"].tag, qgis_source)
        _clone(
            "oclero/qlementine",
            releases["qlementine"].tag,
            qlementine_source,
        )
        patch_main(qgis_source)
        patch_cmake(qgis_source)
        patch_windows_triplet(qgis_source)

        versions = {name: asdict(value) for name, value in releases.items()}
        (output / "versions.json").write_text(
            json.dumps(versions, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Prepared QGIS {releases['qgis'].version}")
    print(f"Prepared Qlementine {releases['qlementine'].version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
