#!/usr/bin/env python3
"""Prepare deterministic Qt Installer Framework metadata for QGIS+."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


PACKAGE_ID = "org.qgisplus.desktop"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _write_xml(path: Path, root: ET.Element) -> None:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _add_text(parent: ET.Element, name: str, value: str) -> None:
    ET.SubElement(parent, name).text = value


def validate_runtime(runtime: Path) -> None:
    qgisplus_launcher = runtime / "QGIS+.exe"
    if not qgisplus_launcher.is_file():
        raise RuntimeError(
            f"Required QGIS+ launcher is missing: {qgisplus_launcher}"
        )
    launcher_config = runtime / "qgisplus-launcher.txt"
    if not launcher_config.is_file():
        raise RuntimeError(
            f"QGIS launcher configuration is missing: {launcher_config}"
        )
    global_settings = runtime / "qgisplus-global-settings.ini"
    if not global_settings.is_file():
        raise RuntimeError(
            f"QGIS+ global settings are missing: {global_settings}"
        )

    qgis_launchers = (
        tuple(runtime.rglob("qgis.bat"))
        + tuple(runtime.rglob("qgis-ltr.bat"))
        + tuple(runtime.rglob("qgis-bin.exe"))
    )
    if not qgis_launchers:
        raise RuntimeError("The staged runtime does not contain official QGIS")

    theme_candidates = tuple(runtime.rglob("QGISPlus Material/style.qss"))
    if not theme_candidates:
        raise RuntimeError(
            "QGISPlus Material theme is missing from the staged QGIS runtime"
        )

    theme_plugin_candidates = tuple(
        runtime.rglob("qgisplus_theme/metadata.txt")
    )
    if not theme_plugin_candidates:
        raise RuntimeError(
            "QGISPlus Material theme registrar is missing from the staged runtime"
        )


def prepare_ifw_package(
    runtime: Path,
    output: Path,
    version: str,
    release_date: str,
    license_path: Path,
    install_script: Path,
) -> None:
    runtime = runtime.resolve()
    output = output.resolve()
    if not VERSION_RE.fullmatch(version):
        raise RuntimeError(f"Invalid QGIS version for QtIFW: {version}")
    try:
        date.fromisoformat(release_date)
    except ValueError as error:
        raise RuntimeError(
            f"Release date must use YYYY-MM-DD: {release_date}"
        ) from error
    if not license_path.is_file():
        raise RuntimeError(f"License file is missing: {license_path}")
    if not install_script.is_file():
        raise RuntimeError(f"QtIFW component script is missing: {install_script}")

    validate_runtime(runtime)

    package_root = output / "packages" / PACKAGE_ID
    data_directory = package_root / "data"
    if data_directory.resolve() != runtime:
        raise RuntimeError(
            "The downloaded runtime must be placed directly in the QtIFW "
            f"package data directory: {data_directory}"
        )

    config_directory = output / "config"
    metadata_directory = package_root / "meta"
    config_directory.mkdir(parents=True, exist_ok=True)
    metadata_directory.mkdir(parents=True, exist_ok=True)

    installer = ET.Element("Installer")
    for name, value in (
        ("Name", "QGIS+"),
        ("Version", version),
        ("Title", "QGIS+ Installer"),
        ("Publisher", "QGIS+ Community Build"),
        ("ProductUrl", "https://github.com/theonegis/Styled-QGIS"),
        ("StartMenuDir", "QGIS+"),
        ("TargetDir", "@ApplicationsDirX64@/QGIS+"),
        ("MaintenanceToolName", "QGISPlusMaintenanceTool"),
        ("AllowNonAsciiCharacters", "true"),
    ):
        _add_text(installer, name, value)
    _write_xml(config_directory / "config.xml", installer)

    package = ET.Element("Package")
    for name, value in (
        ("DisplayName", "QGIS+"),
        ("Description", "QGIS with the compact QGISPlus Material UI theme"),
        ("Version", version),
        ("ReleaseDate", release_date),
        ("Default", "true"),
        ("Essential", "true"),
        ("ForcedInstallation", "true"),
        ("Script", "installscript.qs"),
    ):
        _add_text(package, name, value)
    licenses = ET.SubElement(package, "Licenses")
    ET.SubElement(
        licenses,
        "License",
        {"name": "GPL-2.0-or-later", "file": "LICENSE.txt"},
    )
    _write_xml(metadata_directory / "package.xml", package)

    shutil.copy2(license_path, metadata_directory / "LICENSE.txt")
    shutil.copy2(install_script, metadata_directory / "installscript.qs")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-date", default=date.today().isoformat())
    parser.add_argument("--license", required=True, type=Path)
    parser.add_argument("--install-script", required=True, type=Path)
    args = parser.parse_args()

    try:
        prepare_ifw_package(
            args.runtime,
            args.output,
            args.version,
            args.release_date,
            args.license,
            args.install_script,
        )
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Prepared QtIFW package metadata for QGIS+ {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
