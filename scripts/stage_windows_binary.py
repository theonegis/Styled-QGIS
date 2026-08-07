#!/usr/bin/env python3
"""Add the QGIS+ launcher and style plugin to an extracted official QGIS MSI."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _find_qgis_launcher(runtime: Path) -> Path:
    candidates: list[tuple[int, Path]] = []
    ranks = {"qgis.bat": 0, "qgis-ltr.bat": 1, "qgis-bin.exe": 2}
    for path in runtime.rglob("*"):
        if path.is_file() and path.name.lower() in ranks:
            candidates.append((ranks[path.name.lower()], path))
    if not candidates:
        raise RuntimeError("Official MSI does not contain a QGIS launcher")
    return min(candidates, key=lambda candidate: candidate[0])[1]


def _plugin_roots(runtime: Path) -> list[Path]:
    roots = {
        platform.parent.parent
        for platform in runtime.rglob("qwindows.dll")
        if platform.parent.name.lower() == "platforms"
        and "qt5" not in {part.lower() for part in platform.parts}
    }
    if not roots:
        raise RuntimeError(
            "Official MSI does not contain a Qt platforms/qwindows.dll plugin"
        )
    return sorted(roots)


def stage(runtime: Path, launcher: Path, style_plugin: Path) -> list[Path]:
    runtime = runtime.resolve()
    if not runtime.is_dir():
        raise RuntimeError(f"Extracted MSI runtime is missing: {runtime}")
    for path, label in ((launcher, "QGIS+ launcher"), (style_plugin, "style plugin")):
        if not path.is_file():
            raise RuntimeError(f"{label} is missing: {path}")

    official_launcher = _find_qgis_launcher(runtime)
    installed_launcher = runtime / "QGIS+.exe"
    shutil.copy2(launcher, installed_launcher)
    launcher_config = runtime / "qgisplus-launcher.txt"
    launcher_config.write_text(
        str(official_launcher.relative_to(runtime)), encoding="utf-8"
    )

    installed_plugins: list[Path] = []
    for root in _plugin_roots(runtime):
        destination = root / "styles" / "qgisplusstyle.dll"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(style_plugin, destination)
        installed_plugins.append(destination)

    if not installed_launcher.is_file() or not installed_plugins:
        raise RuntimeError("QGIS+ staging validation failed")
    print(f"Official QGIS launcher: {official_launcher.relative_to(runtime)}")
    print(f"Installed QGIS+ launcher: {installed_launcher.relative_to(runtime)}")
    for plugin in installed_plugins:
        print(f"Installed style plugin: {plugin.relative_to(runtime)}")
    return installed_plugins


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--style-plugin", required=True, type=Path)
    args = parser.parse_args()
    try:
        stage(args.runtime, args.launcher, args.style_plugin)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
