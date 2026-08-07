#!/bin/bash

set -euo pipefail

if (( $# != 2 )); then
    echo "Usage: $0 OFFICIAL.dmg OUTPUT-QGIS.app" >&2
    exit 2
fi

dmg_path="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
output_app="$2"
work_root="$(mktemp -d "${TMPDIR:-/tmp}/qgisplus-extract.XXXXXX")"
mount_point="${work_root}/mount"
expanded_pkg="${work_root}/expanded-pkg"
mounted=false

find_qgis_app() {
    local search_root="$1"
    local candidate

    # 官方 QGIS 4 DMG 中的 bundle 名称包含版本号，并不固定为 QGIS.app。
    # 先找 QGIS*.app，再兼容未来只有一个普通 .app 的官方布局。
    candidate="$(find "${search_root}" -type d -name 'QGIS*.app' -print -quit)"
    if [[ -z "${candidate}" ]]; then
        candidate="$(find "${search_root}" -type d -name '*.app' -print -quit)"
    fi

    if [[ -n "${candidate}" && -f "${candidate}/Contents/Info.plist" ]]; then
        printf '%s\n' "${candidate}"
        return 0
    fi
    return 1
}

cleanup() {
    if [[ "${mounted}" == true ]]; then
        hdiutil detach "${mount_point}" -quiet || true
    fi
    rm -rf "${work_root}"
}
trap cleanup EXIT

mkdir -p "${mount_point}"
hdiutil attach "${dmg_path}" -readonly -nobrowse \
    -mountpoint "${mount_point}" -quiet
mounted=true

source_app="$(find_qgis_app "${mount_point}" || true)"
if [[ -z "${source_app}" ]]; then
    # .pkg 既可能是 flat package 文件，也可能是 bundle package 目录。
    source_pkg="$(find "${mount_point}" -name '*.pkg' -print -quit)"
    if [[ -z "${source_pkg}" ]]; then
        echo "Official QGIS DMG contains neither a QGIS application nor a PKG." >&2
        echo "Mounted DMG root contents:" >&2
        ls -la "${mount_point}" >&2
        exit 1
    fi
    pkgutil --expand-full "${source_pkg}" "${expanded_pkg}"
    source_app="$(find_qgis_app "${expanded_pkg}" || true)"
fi

if [[ -z "${source_app}" || ! -f "${source_app}/Contents/Info.plist" ]]; then
    echo "Unable to extract QGIS.app from the official DMG." >&2
    exit 1
fi

mkdir -p "$(dirname "${output_app}")"
rm -rf "${output_app}"
ditto "${source_app}" "${output_app}"
test -f "${output_app}/Contents/Info.plist"
echo "Extracted official QGIS application: ${output_app}"
