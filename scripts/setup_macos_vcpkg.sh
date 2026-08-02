#!/usr/bin/env bash

set -euo pipefail

: "${QGIS_SOURCE:?QGIS_SOURCE is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
: "${GITHUB_ENV:?GITHUB_ENV is required}"
: "${GITHUB_PATH:?GITHUB_PATH is required}"

manifest="${QGIS_SOURCE}/vcpkg/vcpkg.json"
if [[ ! -f "${manifest}" ]]; then
  echo "Missing QGIS vcpkg manifest: ${manifest}" >&2
  exit 1
fi

# 使用所选 QGIS Release 自己声明的 baseline，而不是每天变化的
# aka.ms/vcpkg-init.sh latest。这样端口、ABI 计算和 vcpkg 工具保持同一快照。
vcpkg_commit="$({
  python3 - "${manifest}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    manifest = json.load(stream)
print(manifest["vcpkg-configuration"]["default-registry"]["baseline"])
PY
})"

if [[ ! "${vcpkg_commit}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid vcpkg baseline: ${vcpkg_commit}" >&2
  exit 1
fi

vcpkg_root="${RUNNER_TEMP}/qgisplus-vcpkg"
case "${vcpkg_root}" in
  "${RUNNER_TEMP}"/*) ;;
  *)
    echo "Refusing to prepare vcpkg outside RUNNER_TEMP" >&2
    exit 1
    ;;
esac

fetched=false
for attempt in 1 2 3; do
  rm -rf -- "${vcpkg_root}"
  git init --quiet "${vcpkg_root}"
  git -C "${vcpkg_root}" remote add origin \
    https://github.com/microsoft/vcpkg.git
  if git -C "${vcpkg_root}" fetch --quiet --depth 1 \
      origin "${vcpkg_commit}"; then
    git -C "${vcpkg_root}" checkout --quiet --detach FETCH_HEAD
    fetched=true
    break
  fi
  echo "::warning::vcpkg fetch attempt ${attempt}/3 failed"
  sleep "$((attempt * 5))"
done

if [[ "${fetched}" != true ]]; then
  echo "Unable to fetch vcpkg ${vcpkg_commit} after three attempts" >&2
  exit 1
fi

"${vcpkg_root}/bootstrap-vcpkg.sh" -disableMetrics
test -x "${vcpkg_root}/vcpkg"

echo "VCPKG_ROOT=${vcpkg_root}" >> "${GITHUB_ENV}"
echo "${vcpkg_root}" >> "${GITHUB_PATH}"
echo "Pinned vcpkg commit: ${vcpkg_commit}" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
"${vcpkg_root}/vcpkg" version
