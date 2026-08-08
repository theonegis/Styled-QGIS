#!/usr/bin/env python3
"""Launch a staged QGIS+ runtime and verify the bundled QSS theme is active."""

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
        raise RuntimeError(f"QGIS theme probe is missing: {probe}")

    work_dir.mkdir(parents=True, exist_ok=True)
    result_path = work_dir / "qgisplus-theme-probe.json"
    result_path.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["QGISPLUS_THEME_PROBE_OUTPUT"] = str(result_path)
    command = [
        str(launcher),
        "--nologo",
        "--noversioncheck",
        "--profiles-path",
        str(work_dir / "profiles"),
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
        raise RuntimeError(f"QGIS+ theme probe timed out after {timeout}s") from error

    # 官方 Windows 启动脚本可能先于 qgis-bin.exe 返回；等待内部探针写出结果。
    while not result_path.is_file() and time.monotonic() < deadline:
        time.sleep(0.2)

    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if not result_path.is_file():
        raise RuntimeError(
            f"QGIS+ did not write the theme probe result (exit {completed.returncode})"
        )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if completed.returncode != 0 or not result.get("passed", False):
        raise RuntimeError(
            f"QGIS+ runtime theme verification failed (exit {completed.returncode}): "
            + json.dumps(result, ensure_ascii=False)
        )
    print("Verified QGIS+ runtime theme: QGISPlus Material")
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
