#!/bin/bash

set -euo pipefail

if (( $# != 6 )); then
    echo "Usage: $0 QGIS.app STYLE_PLUGIN LAUNCHER ARCH VERSION OUTPUT.dmg" >&2
    exit 2
fi

official_app="$1"
style_plugin="$2"
launcher="$3"
target_arch="$4"
version="$5"
output_dmg="$6"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work_root="$(mktemp -d "${TMPDIR:-/tmp}/qgisplus-package.XXXXXX")"
outer_app="${work_root}/QGIS+.app"

cleanup() {
    rm -rf "${work_root}"
}
trap cleanup EXIT

case "${target_arch}" in
    x86_64|arm64) ;;
    *) echo "Unsupported macOS architecture: ${target_arch}" >&2; exit 2 ;;
esac

test -f "${official_app}/Contents/Info.plist"
test -f "${style_plugin}"
test -x "${launcher}"
official_executable="$(/usr/libexec/PlistBuddy -c \
    'Print :CFBundleExecutable' "${official_app}/Contents/Info.plist")"
official_icon_name="$(/usr/libexec/PlistBuddy -c \
    'Print :CFBundleIconFile' "${official_app}/Contents/Info.plist")"
if [[ "${official_icon_name}" != *.icns ]]; then
    official_icon_name="${official_icon_name}.icns"
fi
official_binary="${official_app}/Contents/MacOS/${official_executable}"
official_icon="${official_app}/Contents/Resources/${official_icon_name}"
if [[ ! -x "${official_binary}" ]]; then
    echo "Official QGIS CFBundleExecutable is missing: ${official_executable}" >&2
    exit 1
fi
if [[ ! -f "${official_icon}" ]]; then
    echo "Official QGIS CFBundleIconFile is missing: ${official_icon_name}" >&2
    exit 1
fi
mkdir -p \
    "${outer_app}/Contents/MacOS" \
    "${outer_app}/Contents/PlugIns/styles" \
    "${outer_app}/Contents/Resources"

ditto "${official_app}" "${outer_app}/Contents/Resources/QGIS.app"
ditto "${official_icon}" "${outer_app}/Contents/Resources/QGISPlus.icns"
printf '%s\n' "${official_executable}" \
    > "${outer_app}/Contents/Resources/qgisplus-executable.txt"
ditto "${style_plugin}" \
    "${outer_app}/Contents/PlugIns/styles/$(basename "${style_plugin}")"
ditto "${launcher}" \
    "${outer_app}/Contents/MacOS/QGISPlusLauncher"
chmod 755 "${outer_app}/Contents/MacOS/QGISPlusLauncher"
sed "s/@VERSION@/${version}/g" \
    "${repo_root}/packaging/macos/Info.plist.in" \
    > "${outer_app}/Contents/Info.plist"

plugin_path="${outer_app}/Contents/PlugIns/styles/$(basename "${style_plugin}")"
qgis_binary="${outer_app}/Contents/Resources/QGIS.app/Contents/MacOS/${official_executable}"

# lipo 的输入文件必须位于命令之前，否则它会把文件路径当成额外架构名。
lipo "${plugin_path}" -verify_arch "${target_arch}"
lipo "${outer_app}/Contents/MacOS/QGISPlusLauncher" \
    -verify_arch "${target_arch}"
lipo "${qgis_binary}" -verify_arch "${target_arch}"
if ! otool -l "${plugin_path}" | grep -Fq \
        '@loader_path/../../Resources/QGIS.app/Contents/Frameworks'; then
    install_name_tool -add_rpath \
        '@loader_path/../../Resources/QGIS.app/Contents/Frameworks' \
        "${plugin_path}"
fi

# Qt SDK 的 framework install name 在某些发行方式中是绝对路径。统一改为
# @rpath，使插件只加载内层官方 QGIS.app 自带的 Qt，而不会引用 Runner SDK。
while IFS= read -r dependency; do
    case "${dependency}" in
        /*/Qt*.framework/*)
            framework_suffix="$(printf '%s\n' "${dependency}" | \
                sed -E 's|^.*/(Qt[^/]+\.framework/.*)$|\1|')"
            install_name_tool -change "${dependency}" \
                "@rpath/${framework_suffix}" "${plugin_path}"
            ;;
    esac
done < <(otool -L "${plugin_path}" | tail -n +2 | awk '{print $1}')

if otool -L "${plugin_path}" | tail -n +2 | awk '{print $1}' | \
        grep -Eq '^/.*Qt[^/]+\.framework/'; then
    echo "Style plugin still references an absolute Qt framework path." >&2
    otool -L "${plugin_path}" >&2
    exit 1
fi

# install_name_tool 会改变插件签名；重新执行 ad-hoc 签名并签署外层 App。
# 内层官方 QGIS.app 保持原样，不使用 --deep 重签名。
codesign --force --sign - --timestamp=none "${plugin_path}"
codesign --force --sign - --timestamp=none "${outer_app}"
codesign --verify --strict "${outer_app}"

mkdir -p "$(dirname "${output_dmg}")"
rm -f "${output_dmg}"
hdiutil create -volname "QGIS+ ${version}" -srcfolder "${outer_app}" \
    -ov -format UDZO "${output_dmg}"
hdiutil verify "${output_dmg}"
echo "Created QGIS+ macOS package: ${output_dmg}"
