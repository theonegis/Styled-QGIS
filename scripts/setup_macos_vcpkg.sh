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

# QGIS 的 manifest 继续固定端口快照；vcpkg-tool 则单独固定到已验证版本。
# QGIS 4.2.1 的 registry baseline 自带 2026-05-27 工具，该工具在 macOS
# 动态 triplet 下会让已安装的 Python 从 packages/ 路径运行，进而找不到
# 相邻 triplet lib/ 中的 libintl.8.dylib。2026-07-27 standalone 工具与
# 上一次能够越过 Python 依赖阶段的官方 setup-vcpkg 路径一致。
registry_baseline="$({
  python3 - "${manifest}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    manifest = json.load(stream)
print(manifest["vcpkg-configuration"]["default-registry"]["baseline"])
PY
})"

if [[ ! "${registry_baseline}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid vcpkg baseline: ${registry_baseline}" >&2
  exit 1
fi

vcpkg_tool_version="2026-07-27"
vcpkg_tool_sha256="352a52151f57e51b0298bdd6f6a825cd4413d3b88d258f456193daf783b3ceec"
vcpkg_root="${RUNNER_TEMP}/qgisplus-vcpkg"
case "${vcpkg_root}" in
  "${RUNNER_TEMP}"/*) ;;
  *)
    echo "Refusing to prepare vcpkg outside RUNNER_TEMP" >&2
    exit 1
    ;;
esac

rm -rf -- "${vcpkg_root}"
mkdir -p "${vcpkg_root}"
vcpkg_executable="${vcpkg_root}/vcpkg"
vcpkg_download="${vcpkg_executable}.download"
vcpkg_url="https://github.com/microsoft/vcpkg-tool/releases/download/${vcpkg_tool_version}/vcpkg-macos"

curl --fail --location --show-error --silent \
  --retry 3 --retry-all-errors --retry-delay 5 \
  --output "${vcpkg_download}" "${vcpkg_url}"

actual_sha256="$(shasum -a 256 "${vcpkg_download}" | awk '{print $1}')"
if [[ "${actual_sha256}" != "${vcpkg_tool_sha256}" ]]; then
  echo "vcpkg-tool checksum mismatch: ${actual_sha256}" >&2
  exit 1
fi

mv "${vcpkg_download}" "${vcpkg_executable}"
chmod +x "${vcpkg_executable}"
"${vcpkg_executable}" bootstrap-standalone
test -x "${vcpkg_executable}"

echo "VCPKG_ROOT=${vcpkg_root}" >> "${GITHUB_ENV}"
echo "${vcpkg_root}" >> "${GITHUB_PATH}"
{
  echo "Pinned vcpkg-tool: ${vcpkg_tool_version}"
  echo "QGIS registry baseline: ${registry_baseline}"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
"${vcpkg_executable}" version
