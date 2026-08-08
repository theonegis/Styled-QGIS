#!/usr/bin/env python3
"""Launch a staged QGIS+ runtime and reject packages not using Qlementine."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def verify(launcher: Path, probe: Path, work_dir: Path, timeout: int) -> dict:
    launcher = launcher.resolve()
    probe = probe.resolve()
    work_dir = work_dir.resolve()
    if not launcher.is_file():
        raise RuntimeError(f"QGIS+ launcher is missing: {launcher}")
    if not probe.is_file():
        raise RuntimeError(f"QGIS style probe is missing: {probe}")

    work_dir.mkdir(parents=True, exist_ok=True)
    profiles = work_dir / "profiles"
    result_path = work_dir / "qgisplus-style-probe.json"
    result_path.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["QGISPLUS_STYLE_PROBE_OUTPUT"] = str(result_path)
    command = [
        str(launcher),
        "--nologo",
        "--noversioncheck",
        "--noplugins",
        "--profiles-path",
        str(profiles),
        "--code",
        str(probe),
    ]
    deadline = time.monotonic() + timeout
    try:
        completed = subprocess.run(
            command,
            cwd=launcher.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"QGIS+ style probe timed out after {timeout}s") from error

    # 某些官方 Windows qgis.bat 会在真正的 qgis-bin.exe 完成前退出。
    # 保留总超时上限，等待由 QGIS 内部探针写出的结果文件。
    while not result_path.is_file() and time.monotonic() < deadline:
        time.sleep(0.2)

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if not result_path.is_file():
        raise RuntimeError(
            f"QGIS+ did not write the style probe result (exit {completed.returncode})"
        )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if completed.returncode != 0 or not result.get("passed", False):
        raise RuntimeError(
            f"QGIS+ runtime verification failed (exit {completed.returncode}): "
            + json.dumps(result, ensure_ascii=False)
        )
    print("Verified QGIS+ runtime style: Qlementine")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    try:
        verify(args.launcher, args.probe, args.work_dir, args.timeout)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
