#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_root}"

preflight_tmp="$(mktemp -d "${TMPDIR:-/tmp}/qgisplus-preflight.XXXXXX")"
trap 'rm -rf "${preflight_tmp}"' EXIT

echo "[1/5] Checking Bash syntax"
bash -n scripts/*.sh

echo "[2/5] Checking Python syntax"
PYTHONPYCACHEPREFIX="${preflight_tmp}/pycache" \
  python3 -m py_compile scripts/*.py tests/*.py

echo "[3/5] Checking workflow YAML"
if python3 -c "import yaml" >/dev/null 2>&1; then
  python3 - <<'PY'
from pathlib import Path
import yaml

for workflow in Path(".github/workflows").glob("*.yml"):
    yaml.safe_load(workflow.read_text(encoding="utf-8"))
    print(f"YAML OK: {workflow}")
PY
elif command -v ruby >/dev/null 2>&1; then
  ruby -e 'require "yaml"; ARGV.each { |path| YAML.load_file(path); puts "YAML OK: #{path}" }' \
    .github/workflows/*.yml
else
  echo "PyYAML or Ruby is required to validate workflow YAML" >&2
  exit 1
fi

echo "[4/5] Running script tests"
PYTHONPYCACHEPREFIX="${preflight_tmp}/pycache" \
  python3 -m unittest discover -s tests -p "test_*.py" -v

echo "[5/5] Checking whitespace errors"
git diff --check

echo "QGIS+ preflight passed"
