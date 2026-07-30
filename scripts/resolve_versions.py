#!/usr/bin/env python3
"""Resolve the newest stable QGIS 4.x and Qlementine releases from GitHub."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


QGIS_RELEASE_RE = re.compile(r"^final-(\d+)_(\d+)_(\d+)$")
QLEMENTINE_RELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\.\d+)?$")


@dataclass(frozen=True)
class Release:
    repository: str
    tag: str
    version: str
    published_at: str


def _github_releases(repository: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "qgis-plus-version-resolver",
            **(
                {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
                if os.environ.get("GITHUB_TOKEN")
                else {}
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(
            f"Unable to query GitHub releases for {repository}: {error}"
        ) from error

    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected GitHub response for {repository}")
    return payload


def _select_release(
    repository: str,
    releases: Iterable[dict[str, Any]],
    pattern: re.Pattern[str],
    *,
    required_major: int | None = None,
) -> Release:
    candidates: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name", ""))
        match = pattern.fullmatch(tag)
        if not match:
            continue
        version_tuple = tuple(int(part) for part in match.groups()[:3])
        if required_major is not None and version_tuple[0] != required_major:
            continue
        candidates.append((version_tuple, release))

    if not candidates:
        qualifier = f" major {required_major}" if required_major else ""
        raise RuntimeError(f"No stable{qualifier} release found for {repository}")

    version_tuple, selected = max(candidates, key=lambda item: item[0])
    return Release(
        repository=repository,
        tag=str(selected["tag_name"]),
        version=".".join(str(part) for part in version_tuple),
        published_at=str(selected.get("published_at", "")),
    )


def resolve(qgis_major: int = 4) -> dict[str, Release]:
    # GitHub 的 /releases/latest 按发布时间判断；QGIS LR 与 LTR 同日发布时，
    # 它可能返回版本号更低的 LTR，因此这里显式按语义版本取最大值。
    return {
        "qgis": _select_release(
            "qgis/QGIS",
            _github_releases("qgis/QGIS"),
            QGIS_RELEASE_RE,
            required_major=qgis_major,
        ),
        "qlementine": _select_release(
            "oclero/qlementine",
            _github_releases("oclero/qlementine"),
            QLEMENTINE_RELEASE_RE,
        ),
    }


def _write_github_outputs(releases: dict[str, Release], path: Path) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name, release in releases.items():
            output.write(f"{name}_tag={release.tag}\n")
            output.write(f"{name}_version={release.version}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qgis-major", type=int, default=4)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"])
        if os.environ.get("GITHUB_OUTPUT")
        else None,
    )
    args = parser.parse_args()

    try:
        releases = resolve(args.qgis_major)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    serializable = {name: asdict(value) for name, value in releases.items()}
    rendered = json.dumps(serializable, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.github_output:
        _write_github_outputs(releases, args.github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
