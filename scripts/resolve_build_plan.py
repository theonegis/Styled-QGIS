#!/usr/bin/env python3
"""Resolve which release platforms must be built or reused."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SHARDS = ("base", "geo", "python", "qt")
MACOS_PLATFORMS: dict[str, dict[str, str]] = {
    "intel": {
        "name": "Intel",
        "os": "macos-15-intel",
        "arch": "x86_64",
        "triplet": "x64-osx-dynamic-release",
        "deployment_target": "12.0",
        "artifact_arch": "intel",
    },
    "arm64": {
        "name": "Apple-Silicon",
        "os": "macos-15",
        "arch": "arm64",
        "triplet": "arm64-osx-dynamic-release",
        "deployment_target": "12.0",
        "artifact_arch": "arm64",
    },
}


def _parse_boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"Expected true or false, received {value!r}")


def resolve_build_plan(
    *,
    event_name: str,
    reuse_run_id: str,
    build_windows: str,
    build_macos_intel: str,
    build_macos_arm64: str,
) -> dict[str, Any]:
    # tag push 和定时任务没有可审查的复用来源，始终执行完整构建。
    if event_name != "workflow_dispatch":
        selections = {
            "windows": True,
            "intel": True,
            "arm64": True,
        }
        reuse_run_id = ""
    else:
        selections = {
            "windows": _parse_boolean(build_windows),
            "intel": _parse_boolean(build_macos_intel),
            "arm64": _parse_boolean(build_macos_arm64),
        }
        reuse_run_id = reuse_run_id.strip()

    reused = [name for name, selected in selections.items() if not selected]
    if reused and re.fullmatch(r"[1-9][0-9]*", reuse_run_id) is None:
        raise ValueError(
            "A positive reuse_run_id is required when any platform build "
            "is disabled"
        )

    selected_macos = [
        dict(MACOS_PLATFORMS[name])
        for name in ("intel", "arm64")
        if selections[name]
    ]
    dependency_matrix = {
        "include": [
            {**platform, "shard": shard}
            for platform in selected_macos
            for shard in SHARDS
        ]
    }

    return {
        "reuse_run_id": reuse_run_id,
        "build_windows": selections["windows"],
        "build_macos": bool(selected_macos),
        "build_macos_intel": selections["intel"],
        "build_macos_arm64": selections["arm64"],
        "reuse_windows": not selections["windows"],
        "reuse_macos_intel": not selections["intel"],
        "reuse_macos_arm64": not selections["arm64"],
        "macos_matrix": {"include": selected_macos},
        "macos_dependency_matrix": dependency_matrix,
    }


def _write_github_outputs(plan: dict[str, Any], path: Path) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name, value in plan.items():
            if isinstance(value, bool):
                rendered = str(value).lower()
            elif isinstance(value, dict):
                rendered = json.dumps(value, separators=(",", ":"))
            else:
                rendered = str(value)
            output.write(f"{name}={rendered}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--reuse-run-id", default="")
    parser.add_argument("--build-windows", default="true")
    parser.add_argument("--build-macos-intel", default="true")
    parser.add_argument("--build-macos-arm64", default="true")
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
        plan = resolve_build_plan(
            event_name=args.event_name,
            reuse_run_id=args.reuse_run_id,
            build_windows=args.build_windows,
            build_macos_intel=args.build_macos_intel,
            build_macos_arm64=args.build_macos_arm64,
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    rendered = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.github_output:
        _write_github_outputs(plan, args.github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
