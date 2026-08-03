#!/usr/bin/env python3
"""Audit Python registry ports against locked PyPI runtime metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ImportError:  # pragma: no cover - standard pip installations
    try:
        from pip._vendor.packaging.markers import default_environment
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.utils import canonicalize_name
    except ImportError as error:  # pragma: no cover - actionable CLI guard
        raise SystemExit(
            "The Python 'packaging' module or a standard pip installation "
            "is required"
        ) from error

from prepare_vcpkg_shard import dependency_name


PACKAGE_NAME_RE = re.compile(r"^\s*PACKAGE_NAME\s+([^\s)]+)", re.MULTILINE)
PACKAGE_NAME_OVERRIDES = {"py-dateutil": "python-dateutil"}


def _load_ports(
    registry: Path, overlay_directories: list[Path] | None = None
) -> dict[str, dict[str, Any]]:
    ports: dict[str, dict[str, Any]] = {}
    manifest_paths = list(sorted((registry / "ports").glob("py-*/vcpkg.json")))
    for overlay_directory in overlay_directories or []:
        manifest_paths.extend(sorted(overlay_directory.glob("py-*/vcpkg.json")))

    # Overlay manifests are appended after registry manifests and therefore
    # replace the same port name exactly as vcpkg overlay resolution does.
    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        port_name = str(manifest["name"])
        portfile = manifest_path.with_name("portfile.cmake")
        package_name = PACKAGE_NAME_OVERRIDES.get(
            port_name, port_name.removeprefix("py-")
        )
        if portfile.is_file():
            match = PACKAGE_NAME_RE.search(portfile.read_text(encoding="utf-8"))
            if match and "${" not in match.group(1):
                package_name = match.group(1)
        ports[port_name] = {
            "manifest": manifest,
            "distribution": canonicalize_name(package_name),
        }
    return ports


def _manifest_roots(manifest_path: Path, features: list[str]) -> set[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dependencies = list(manifest.get("dependencies", []))
    feature_table = manifest.get("features", {})
    for feature_name in features:
        feature = feature_table.get(feature_name)
        if not isinstance(feature, dict):
            raise ValueError(f"Unknown vcpkg feature: {feature_name}")
        dependencies.extend(feature.get("dependencies", []))
    return {
        dependency_name(dependency)
        for dependency in dependencies
        if dependency_name(dependency).startswith("py-")
    }


def _closure(ports: dict[str, dict[str, Any]], roots: set[str]) -> set[str]:
    result: set[str] = set()
    pending = deque(sorted(roots))
    while pending:
        port_name = pending.popleft()
        if port_name in result or port_name not in ports:
            continue
        result.add(port_name)
        dependencies = ports[port_name]["manifest"].get("dependencies", [])
        for dependency in dependencies:
            name = dependency_name(dependency)
            if name.startswith("py-") and name not in result:
                pending.append(name)
    return result


def _load_or_refresh_metadata(
    ports: dict[str, dict[str, Any]],
    closure: set[str],
    lock_path: Path,
    refresh: bool,
) -> dict[str, dict[str, Any]]:
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    else:
        lock = {"schema": 1, "packages": {}}
    packages = lock.setdefault("packages", {})

    def save_lock() -> None:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    for port_name in sorted(closure):
        port = ports[port_name]
        manifest = port["manifest"]
        version_key, version = next(
            (
                (key, str(value))
                for key, value in manifest.items()
                if key.startswith("version") and key != "version-string"
            ),
            ("version-string", str(manifest.get("version-string", ""))),
        )
        pypi_version = version.replace("-", ".") if version_key == "version-date" else version
        distribution = port["distribution"]
        cached = packages.get(distribution)
        if cached and cached.get("version") == version:
            continue
        if not refresh:
            raise RuntimeError(
                f"Metadata lock is missing {distribution} {version}; "
                "run again with --refresh"
            )

        encoded_name = urllib.parse.quote(distribution, safe="")
        encoded_version = urllib.parse.quote(pypi_version, safe="")
        url = f"https://pypi.org/pypi/{encoded_name}/{encoded_version}/json"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                metadata = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise RuntimeError(f"Cannot fetch {url}: {error}") from error
            print(
                f"warning: {distribution} {pypi_version} has no PyPI metadata; "
                "recording an empty runtime requirement set",
                file=sys.stderr,
            )
            packages[distribution] = {
                "version": version,
                "requires_dist": [],
                "metadata": "unavailable",
            }
            save_lock()
            continue
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(f"Cannot fetch {url}: {error}") from error
        packages[distribution] = {
            "version": version,
            "requires_dist": metadata["info"].get("requires_dist") or [],
        }
        save_lock()

    # A normal audit is deliberately read-only and can run from a mounted,
    # immutable dependency bundle. Only the explicit online refresh updates it.
    if refresh:
        save_lock()
    return packages


def _requirement_applies(requirement: Requirement, platform: str) -> bool:
    if requirement.marker is None:
        return True
    environment = default_environment()
    environment.update(
        {
            "extra": "",
            "python_version": "3.12",
            "python_full_version": "3.12.0",
            "sys_platform": "darwin" if platform == "macos" else "win32",
            "platform_system": "Darwin" if platform == "macos" else "Windows",
        }
    )
    return requirement.marker.evaluate(environment)


def audit(
    ports: dict[str, dict[str, Any]],
    closure: set[str],
    metadata: dict[str, dict[str, Any]],
) -> list[str]:
    distribution_to_port = {
        data["distribution"]: name for name, data in ports.items()
    }
    errors: list[str] = []
    for port_name in sorted(closure):
        port = ports[port_name]
        declared = {
            dependency_name(item)
            for item in port["manifest"].get("dependencies", [])
        }
        package_metadata = metadata[port["distribution"]]
        for requirement_text in package_metadata.get("requires_dist", []):
            requirement = Requirement(requirement_text)
            if not any(
                _requirement_applies(requirement, platform)
                for platform in ("macos", "windows")
            ):
                continue
            required_distribution = canonicalize_name(requirement.name)
            required_port = distribution_to_port.get(required_distribution)
            if required_port is None:
                errors.append(
                    f"{port_name}: PyPI requires {required_distribution}, "
                    "but the locked registry has no mapped port"
                )
            elif required_port not in declared:
                errors.append(
                    f"{port_name}: missing runtime dependency {required_port} "
                    f"({requirement_text})"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument(
        "--overlay-ports", action="append", default=[], type=Path
    )
    parser.add_argument("--feature", action="append", default=[])
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    try:
        ports = _load_ports(
            args.registry.resolve(),
            [path.resolve() for path in args.overlay_ports],
        )
        roots = _manifest_roots(args.manifest.resolve(), args.feature)
        closure = _closure(ports, roots)
        metadata = _load_or_refresh_metadata(
            ports, closure, args.lock.resolve(), args.refresh
        )
        errors = audit(ports, closure, metadata)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 2

    print(f"Audited {len(closure)} locked Python ports")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
