#!/usr/bin/env python3
"""Run a command and stop its process tree after prolonged output silence."""

from __future__ import annotations

import argparse
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence


TIMEOUT_EXIT_CODE = 124


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run(command: Sequence[str], idle_timeout: float) -> int:
    if not command:
        raise ValueError("A command is required")
    if idle_timeout <= 0:
        raise ValueError("Idle timeout must be greater than zero")

    popen_options: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "bufsize": 0,
    }
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True

    process = subprocess.Popen(list(command), **popen_options)
    assert process.stdout is not None
    output: queue.Queue[bytes | None] = queue.Queue()

    def read_output() -> None:
        while True:
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                break
            output.put(chunk)
        output.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    last_output = time.monotonic()

    while True:
        remaining = idle_timeout - (time.monotonic() - last_output)
        if remaining <= 0:
            completed_status = process.poll()
            if completed_status is not None:
                reader.join(timeout=1)
                return completed_status
            print(
                f"::error::Command produced no output for {idle_timeout:g}s; "
                "terminating its process tree",
                file=sys.stderr,
                flush=True,
            )
            _terminate_process_tree(process)
            reader.join(timeout=10)
            return TIMEOUT_EXIT_CODE
        try:
            chunk = output.get(timeout=min(1.0, remaining))
        except queue.Empty:
            continue
        if chunk is None:
            break
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        last_output = time.monotonic()

    return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--idle-timeout", required=True, type=float)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        return run(command, args.idle_timeout)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
