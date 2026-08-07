#!/usr/bin/env python3
"""Download an artifact with bounded retries and verify its SHA-256 file."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import time
import urllib.request
from pathlib import Path


SHA256_RE = re.compile(r"(?i)\b([0-9a-f]{64})\b")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_expected_checksum(url: str, retries: int) -> str:
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "Styled-QGIS binary packager"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                text = response.read().decode("utf-8", errors="replace")
            match = SHA256_RE.search(text)
            if match is None:
                raise RuntimeError(f"No SHA-256 digest found in {url}")
            return match.group(1).lower()
        except (OSError, RuntimeError) as error:
            if attempt == retries:
                raise RuntimeError(
                    f"Unable to read checksum after {retries} attempts: {error}"
                ) from error
            time.sleep(min(5 * attempt, 20))
    raise AssertionError("unreachable")


def download(url: str, destination: Path, retries: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    for attempt in range(1, retries + 1):
        try:
            temporary.unlink(missing_ok=True)
            request = urllib.request.Request(
                url, headers={"User-Agent": "Styled-QGIS binary packager"}
            )
            with urllib.request.urlopen(request, timeout=300) as response:
                with temporary.open("wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
            os.replace(temporary, destination)
            return
        except OSError as error:
            temporary.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(
                    f"Unable to download after {retries} attempts: {error}"
                ) from error
            time.sleep(min(10 * attempt, 30))


def ensure_verified(
    url: str, checksum_url: str, destination: Path, retries: int = 3
) -> bool:
    expected = read_expected_checksum(checksum_url, retries)
    if destination.is_file() and sha256(destination) == expected:
        print(f"Using verified cached download: {destination}")
        return True

    destination.unlink(missing_ok=True)
    download(url, destination, retries)
    actual = sha256(destination)
    if actual != expected:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA-256 mismatch for {url}: expected {expected}, got {actual}"
        )
    print(f"Downloaded and verified: {destination}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--checksum-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()
    if args.retries < 1:
        parser.error("--retries must be at least 1")
    ensure_verified(args.url, args.checksum_url, args.output, args.retries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
