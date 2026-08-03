#!/usr/bin/env python3
"""Prove that every dependency shard can be restored without network access."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from prepare_vcpkg_shard import SHARDS, create_shard_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vcpkg", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--triplet", required=True)
    parser.add_argument("--binary-cache", required=True, action="append", type=Path)
    parser.add_argument("--registries-cache", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--feature", action="append", default=[])
    args = parser.parse_args()

    vcpkg = args.vcpkg.resolve()
    manifest = args.manifest.resolve()
    caches = [path.resolve() for path in args.binary_cache]
    registries = args.registries_cache.resolve()
    for path in (vcpkg, manifest, registries, *caches):
        if not path.exists():
            print(f"Offline input does not exist: {path}", file=sys.stderr)
            return 2

    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    sources = "clear;" + ";".join(f"files,{path},read" for path in caches)
    environment = os.environ.copy()
    environment.update(
        {
            "VCPKG_BINARY_SOURCES": sources,
            "X_VCPKG_ASSET_SOURCES": "clear;x-block-origin",
            "X_VCPKG_REGISTRIES_CACHE": str(registries),
        }
    )

    for shard in SHARDS:
        shard_root = work_dir / shard
        if shard_root.exists():
            shutil.rmtree(shard_root)
        manifest_root = shard_root / "manifest"
        install_root = shard_root / "installed"
        buildtrees_root = shard_root / "buildtrees"
        manifest_root.mkdir(parents=True)
        shard_manifest = create_shard_manifest(manifest, shard, args.feature)
        (manifest_root / "vcpkg.json").write_text(
            json.dumps(shard_manifest, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        command = [
            str(vcpkg),
            "install",
            f"--x-manifest-root={manifest_root}",
            f"--x-install-root={install_root}",
            f"--x-buildtrees-root={buildtrees_root}",
            f"--triplet={args.triplet}",
            f"--host-triplet={args.triplet}",
            "--only-binarycaching",
            "--no-downloads",
        ]
        result = subprocess.run(command, env=environment, check=False)
        if result.returncode != 0:
            print(
                f"Offline cache is incomplete for the {shard} shard",
                file=sys.stderr,
            )
            return result.returncode

    print("Offline vcpkg cache verified for all dependency shards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
