#!/usr/bin/env python3
"""Split QGIS' locked vcpkg manifest into parallel dependency shards."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


SHARDS = ("base", "geo", "python", "qt")

QT_PACKAGES = {
    "qca",
    "qscintilla",
    "qwt",
    "py-pyqt-builder",
    "py-pyqt6",
    "py-pyqt6-sip",
    "py-qscintilla",
    "py-sip",
}

GEO_PACKAGES = {
    "arrow",
    "arrow-adbc",
    "duckdb",
    "gdal",
    "geos",
    "jhasse-poly2tri",
    "libpq",
    "libspatialindex",
    "libspatialite",
    "opencl",
    "oracle-instantclient",
    "pdal",
    "proj",
    "proj-data",
    "sfcgal",
    "py-adbc-postgresql",
    "py-adbc-sqlite",
    # libpysal imports its examples module during the vcpkg package test.
    # Keep BeautifulSoup in the same isolated shard so `import libpysal`
    # succeeds before the four run-local caches are merged.
    "py-beautifulsoup4",
    "py-duckdb",
    "py-geopandas",
    "py-libpysal",
    "py-owslib",
    "py-psycopg",
    "py-psycopg-c",
    "py-psycopg2",
    "py-pyogrio",
    "py-pyproj",
    "py-pysal",
    "py-rasterio",
    "py-shapely",
}


def dependency_name(dependency: str | dict[str, Any]) -> str:
    if isinstance(dependency, str):
        return dependency
    name = dependency.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"Invalid vcpkg dependency: {dependency!r}")
    return name


def dependency_shard(name: str) -> str:
    if name.startswith("qt") or name in QT_PACKAGES:
        return "qt"
    if name in GEO_PACKAGES:
        return "geo"
    if name == "python3" or name.startswith("py-"):
        return "python"
    return "base"


def _absolute_overlay_paths(
    configuration: dict[str, Any], manifest_directory: Path
) -> dict[str, Any]:
    result = copy.deepcopy(configuration)
    for key in ("overlay-ports", "overlay-triplets"):
        paths = result.get(key, [])
        if not isinstance(paths, list):
            raise ValueError(f"vcpkg-configuration.{key} must be a list")
        result[key] = [
            str((manifest_directory / path).resolve())
            if not Path(path).is_absolute()
            else str(Path(path))
            for path in paths
        ]
    return result


def create_shard_manifest(
    source_manifest: Path,
    shard: str,
    enabled_features: list[str],
) -> dict[str, Any]:
    if shard not in SHARDS:
        raise ValueError(
            f"Unknown shard {shard!r}; expected one of {', '.join(SHARDS)}"
        )

    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    features = manifest.get("features", {})
    if not isinstance(features, dict):
        raise ValueError("vcpkg manifest features must be an object")

    dependencies = list(manifest.get("dependencies", []))
    for feature_name in enabled_features:
        feature = features.get(feature_name)
        if not isinstance(feature, dict):
            raise ValueError(f"Unknown vcpkg manifest feature: {feature_name}")
        feature_dependencies = feature.get("dependencies", [])
        if not isinstance(feature_dependencies, list):
            raise ValueError(
                f"vcpkg feature {feature_name} dependencies must be a list"
            )
        dependencies.extend(feature_dependencies)

    selected = [
        dependency
        for dependency in dependencies
        if dependency_shard(dependency_name(dependency)) == shard
    ]
    if not selected:
        raise ValueError(f"vcpkg dependency shard {shard} is empty")

    configuration = manifest.get("vcpkg-configuration")
    if not isinstance(configuration, dict):
        raise ValueError("vcpkg manifest is missing vcpkg-configuration")

    return {
        "vcpkg-configuration": _absolute_overlay_paths(
            configuration, source_manifest.parent
        ),
        "name": f"qgisplus-dependencies-{shard}",
        "version-string": str(manifest.get("version-string", "current")),
        # Keep duplicate declarations from the upstream manifest. vcpkg merges
        # their feature requests, including host/target and platform clauses.
        "dependencies": selected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--shard", required=True, choices=SHARDS)
    parser.add_argument("--feature", action="append", default=[])
    args = parser.parse_args()

    try:
        shard_manifest = create_shard_manifest(
            args.manifest.resolve(), args.shard, args.feature
        )
        args.output.mkdir(parents=True, exist_ok=True)
        output_manifest = args.output / "vcpkg.json"
        output_manifest.write_text(
            json.dumps(shard_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 1

    names = sorted(
        {dependency_name(item) for item in shard_manifest["dependencies"]}
    )
    print(
        f"Prepared {args.shard} shard with {len(names)} direct packages: "
        + ", ".join(names)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
