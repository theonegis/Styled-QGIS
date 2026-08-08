#!/usr/bin/env python3
"""启动真实 QGIS Options，拒绝文字低对比度或下拉框截断的安装包。"""

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
        raise RuntimeError(f"QGIS Options probe is missing: {probe}")

    work_dir.mkdir(parents=True, exist_ok=True)
    result_path = work_dir / "qgisplus-options-probe.json"
    screenshot_path = work_dir / "qgisplus-options.png"
    combo_screenshot_path = work_dir / "qgisplus-style-combo.png"
    for path in (result_path, screenshot_path, combo_screenshot_path):
        path.unlink(missing_ok=True)

    environment = os.environ.copy()
    environment.update(
        {
            "QGISPLUS_OPTIONS_PROBE_OUTPUT": str(result_path),
            "QGISPLUS_OPTIONS_SCREENSHOT": str(screenshot_path),
            "QGISPLUS_COMBO_SCREENSHOT": str(combo_screenshot_path),
        }
    )
    command = [
        str(launcher),
        "--nologo",
        "--noversioncheck",
        "--noplugins",
        "--profiles-path",
        str(work_dir / "profiles"),
        "--code",
        str(probe),
    ]
    deadline = time.monotonic() + timeout
    completed = subprocess.run(
        command,
        cwd=launcher.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    # 某些 Windows 启动脚本会先于 qgis-bin.exe 返回；继续等待 QGIS 内部
    # 探针写出结果，但仍受同一个总超时限制。
    while not result_path.is_file() and time.monotonic() < deadline:
        time.sleep(0.2)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if not result_path.is_file():
        raise RuntimeError(
            "QGIS+ did not write the Options UI probe result "
            f"(exit {completed.returncode})"
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    if completed.returncode != 0 or not result.get("passed", False):
        raise RuntimeError(
            f"QGIS+ Options UI verification failed (exit {completed.returncode}): "
            + json.dumps(result, ensure_ascii=False)
        )
    print(
        "Verified QGIS+ Options UI: readable text and full ComboBox labels"
    )
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
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
