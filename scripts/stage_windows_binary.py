#!/usr/bin/env python3
"""Add the QGIS+ launcher and QSS theme to an extracted official QGIS MSI."""

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


THEME_NAME = "QGISPlus Material"
THEME_PLUGIN_NAME = "qgisplus_theme"


def _theme_roots(runtime: Path) -> list[Path]:
    """Locate QGIS resource theme roots without assuming an MSI layout."""
    roots = {
        candidate
        for candidate in runtime.rglob("themes")
        if candidate.is_dir()
        and any((child / "style.qss").is_file() for child in candidate.iterdir())
        and "resources" in {part.lower() for part in candidate.parts}
    }
    if not roots:
        raise RuntimeError(
            "Official MSI does not contain a QGIS resources/themes directory"
        )
    return sorted(roots)


def _validate_theme(theme: Path) -> None:
    required = ("style.qss", "variables.qss", "palette.txt")
    missing = [name for name in required if not (theme / name).is_file()]
    if missing:
        raise RuntimeError(
            f"QGIS+ theme is incomplete ({', '.join(missing)}): {theme}"
        )


def _python_plugin_roots(runtime: Path) -> list[Path]:
    """Locate bundled QGIS Python plugin directories across MSI layouts."""
    roots = {
        candidate
        for candidate in runtime.rglob("plugins")
        if candidate.is_dir()
        and candidate.parent.name.casefold() == "python"
        and any(
            (candidate / bundled).is_dir()
            for bundled in ("processing", "db_manager", "MetaSearch")
        )
    }
    if not roots:
        raise RuntimeError(
            "Official MSI does not contain a QGIS python/plugins directory"
        )
    return sorted(roots)


def _validate_theme_plugin(plugin: Path) -> None:
    required = ("__init__.py", "plugin.py", "metadata.txt")
    missing = [name for name in required if not (plugin / name).is_file()]
    if missing:
        raise RuntimeError(
            f"QGIS+ theme plugin is incomplete ({', '.join(missing)}): {plugin}"
        )


def stage(
    runtime: Path,
    launcher: Path,
    theme: Path,
    theme_plugin: Path,
    global_settings: Path,
) -> tuple[list[Path], list[Path]]:
    runtime = runtime.resolve()
    if not runtime.is_dir():
        raise RuntimeError(f"Extracted MSI runtime is missing: {runtime}")
    for path, label in (
        (launcher, "QGIS+ launcher"),
        (global_settings, "QGIS+ global settings"),
    ):
        if not path.is_file():
            raise RuntimeError(f"{label} is missing: {path}")
    if not theme.is_dir():
        raise RuntimeError(f"QGIS+ theme is missing: {theme}")
    _validate_theme(theme)
    if not theme_plugin.is_dir():
        raise RuntimeError(f"QGIS+ theme plugin is missing: {theme_plugin}")
    _validate_theme_plugin(theme_plugin)

    official_launcher = _find_qgis_launcher(runtime)
    installed_launcher = runtime / "QGIS+.exe"
    shutil.copy2(launcher, installed_launcher)
    installed_settings = runtime / "qgisplus-global-settings.ini"
    shutil.copy2(global_settings, installed_settings)
    launcher_config = runtime / "qgisplus-launcher.txt"
    launcher_config.write_text(
        str(official_launcher.relative_to(runtime)), encoding="utf-8"
    )

    installed_themes: list[Path] = []
    for root in _theme_roots(runtime):
        destination = root / THEME_NAME
        shutil.copytree(theme, destination, dirs_exist_ok=True)
        _validate_theme(destination)
        installed_themes.append(destination)

    installed_plugins: list[Path] = []
    for root in _python_plugin_roots(runtime):
        destination = root / THEME_PLUGIN_NAME
        shutil.copytree(theme_plugin, destination, dirs_exist_ok=True)
        _validate_theme_plugin(destination)
        installed_plugins.append(destination)

    if (
        not installed_launcher.is_file()
        or not installed_settings.is_file()
        or not installed_themes
        or not installed_plugins
    ):
        raise RuntimeError("QGIS+ staging validation failed")
    print(f"Official QGIS launcher: {official_launcher.relative_to(runtime)}")
    print(f"Installed QGIS+ launcher: {installed_launcher.relative_to(runtime)}")
    for installed_theme in installed_themes:
        print(f"Installed UI theme: {installed_theme.relative_to(runtime)}")
    for installed_plugin in installed_plugins:
        print(
            "Installed theme registrar: "
            f"{installed_plugin.relative_to(runtime)}"
        )
    return installed_themes, installed_plugins


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--theme", required=True, type=Path)
    parser.add_argument("--theme-plugin", required=True, type=Path)
    parser.add_argument("--global-settings", required=True, type=Path)
    args = parser.parse_args()
    try:
        stage(
            args.runtime,
            args.launcher,
            args.theme,
            args.theme_plugin,
            args.global_settings,
        )
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
