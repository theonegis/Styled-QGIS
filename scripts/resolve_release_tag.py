#!/usr/bin/env python3
"""Resolve a unique QGIS+-release tag for a successful all-platform build."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
BUILD_TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)(?:-r([1-9]\d*))?$")


def next_release_tag(
    qgis_version: str,
    existing_tags: Iterable[str],
    requested_tag: str = "",
) -> str:
    if VERSION_RE.fullmatch(qgis_version) is None:
        raise ValueError(f"Invalid QGIS version: {qgis_version!r}")

    if requested_tag:
        match = BUILD_TAG_RE.fullmatch(requested_tag)
        if match is None or match.group(1) != qgis_version:
            raise ValueError(
                "Requested release tag must match the resolved QGIS version; "
                f"received {requested_tag!r} for QGIS {qgis_version}"
            )
        return requested_tag

    revision_pattern = re.compile(
        rf"^v{re.escape(qgis_version)}-r([1-9]\d*)$"
    )
    revisions = [
        int(match.group(1))
        for tag in existing_tags
        if (match := revision_pattern.fullmatch(tag)) is not None
    ]
    return f"v{qgis_version}-r{max(revisions, default=0) + 1}"


def github_tags(repository: str) -> list[str]:
    tags: list[str] = []
    for page in range(1, 11):
        request = urllib.request.Request(
            "https://api.github.com/repos/"
            f"{repository}/tags?per_page=100&page={page}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "qgis-plus-release-tag-resolver",
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
            raise RuntimeError(f"Unable to query tags for {repository}: {error}") from error
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected GitHub tags response for {repository}")
        tags.extend(str(item.get("name", "")) for item in payload)
        if len(payload) < 100:
            return tags
    raise RuntimeError(f"Tag pagination limit exceeded for {repository}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--qgis-version", required=True)
    parser.add_argument("--requested-tag", default="")
    parser.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"])
        if os.environ.get("GITHUB_OUTPUT")
        else None,
    )
    args = parser.parse_args()

    try:
        release_tag = next_release_tag(
            args.qgis_version,
            github_tags(args.repository),
            args.requested_tag,
        )
    except (RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print(release_tag)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"release_tag={release_tag}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
