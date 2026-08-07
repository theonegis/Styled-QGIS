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

source_app="$(find "${mount_point}" -type d -name 'QGIS.app' -print -quit)"
if [[ -z "${source_app}" ]]; then
    source_pkg="$(find "${mount_point}" -type f -name '*.pkg' -print -quit)"
    if [[ -z "${source_pkg}" ]]; then
        echo "Official QGIS DMG contains neither QGIS.app nor a PKG." >&2
        exit 1
    fi
    pkgutil --expand-full "${source_pkg}" "${expanded_pkg}"
    source_app="$(find "${expanded_pkg}" -type d -name 'QGIS.app' -print -quit)"
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
