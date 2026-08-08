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
    "${outer_app}/Contents/Resources"

inner_app="${outer_app}/Contents/Resources/QGIS.app"
ditto "${official_app}" "${inner_app}"
ditto "${official_icon}" "${outer_app}/Contents/Resources/QGISPlus.icns"
ditto "${repo_root}/packaging/qgisplus-global-settings.ini" \
    "${outer_app}/Contents/Resources/qgisplus-global-settings.ini"
printf '%s\n' "${official_executable}" \
    > "${outer_app}/Contents/Resources/qgisplus-executable.txt"
mkdir -p "${inner_app}/Contents/PlugIns/styles"
ditto "${style_plugin}" \
    "${inner_app}/Contents/PlugIns/styles/$(basename "${style_plugin}")"
ditto "${launcher}" \
    "${outer_app}/Contents/MacOS/QGISPlusLauncher"
chmod 755 "${outer_app}/Contents/MacOS/QGISPlusLauncher"
sed "s/@VERSION@/${version}/g" \
    "${repo_root}/packaging/macos/Info.plist.in" \
    > "${outer_app}/Contents/Info.plist"

plugin_path="${inner_app}/Contents/PlugIns/styles/$(basename "${style_plugin}")"
qgis_binary="${inner_app}/Contents/MacOS/${official_executable}"
qgis_frameworks="${inner_app}/Contents/Frameworks"

# lipo 的输入文件必须位于命令之前，否则它会把文件路径当成额外架构名。
lipo "${plugin_path}" -verify_arch "${target_arch}"
lipo "${outer_app}/Contents/MacOS/QGISPlusLauncher" \
    -verify_arch "${target_arch}"
lipo "${qgis_binary}" -verify_arch "${target_arch}"
if ! otool -l "${plugin_path}" | grep -Fq \
        '@loader_path/../../Frameworks'; then
    install_name_tool -add_rpath \
        '@loader_path/../../Frameworks' \
        "${plugin_path}"
fi

# AQT/Homebrew SDK 使用 Qt*.framework，官方 QGIS 则打包为 libQt6*.dylib。
# 将每个 Qt framework 依赖重绑定到内层 QGIS 自带的同名主版本 dylib。
while IFS= read -r dependency; do
    case "${dependency}" in
        */Qt*.framework/*)
            framework_name="$(printf '%s\n' "${dependency}" | \
                sed -E 's|^.*/(Qt[^/]+)\.framework/.*$|\1|')"
            module_name="${framework_name#Qt}"
            bundled_name="libQt6${module_name}.6.dylib"
            if [[ ! -f "${qgis_frameworks}/${bundled_name}" ]]; then
                echo "Bundled QGIS Qt library is missing: ${bundled_name}" >&2
                exit 1
            fi
            install_name_tool -change "${dependency}" \
                "@rpath/${bundled_name}" "${plugin_path}"
            ;;
    esac
done < <(otool -L "${plugin_path}" | tail -n +2 | awk '{print $1}')

if otool -L "${plugin_path}" | tail -n +2 | awk '{print $1}' | \
        grep -Eq 'Qt[^/]+\.framework/'; then
    echo "Style plugin still references a Qt framework unavailable in QGIS." >&2
    otool -L "${plugin_path}" >&2
    exit 1
fi

while IFS= read -r dependency; do
    case "${dependency}" in
        @rpath/libQt6*.dylib)
            if [[ ! -f "${qgis_frameworks}/${dependency#@rpath/}" ]]; then
                echo "Rebound Qt dependency is missing: ${dependency}" >&2
                exit 1
            fi
            ;;
    esac
done < <(otool -L "${plugin_path}" | tail -n +2 | awk '{print $1}')

# install_name_tool 会改变插件签名。插件现在属于内层 QGIS 的标准 PlugIns
# 目录，因此先签插件，再重新封装内层 bundle 的资源签名，最后签外层 App。
codesign --force --sign - --timestamp=none "${plugin_path}"
codesign --force --sign - --timestamp=none "${inner_app}"
codesign --verify --deep --strict "${inner_app}"
codesign --force --sign - --timestamp=none "${outer_app}"
codesign --verify --deep --strict "${outer_app}"

# 不再以“插件文件存在”作为成功标准。启动真实 QGIS，等待其完成设置加载，
# 并确认 QgsAppStyle 的底层 QStyle 确实是 Qlementine。
python3 "${repo_root}/scripts/verify_qgis_style.py" \
    --launcher "${outer_app}/Contents/MacOS/QGISPlusLauncher" \
    --probe "${repo_root}/scripts/qgis_style_probe.py" \
    --work-dir "${work_root}/style-probe"

# 再打开真实 Options 对话框检查可读性。仅验证插件存在或 Style key 可见，
# 无法发现禁用文字接近背景、下拉项被截断等实际 UI 回归。
python3 "${repo_root}/scripts/verify_qgis_options_ui.py" \
    --launcher "${outer_app}/Contents/MacOS/QGISPlusLauncher" \
    --probe "${repo_root}/scripts/qgis_options_visual_probe.py" \
    --work-dir "${work_root}/options-ui-probe"

mkdir -p "$(dirname "${output_dmg}")"
rm -f "${output_dmg}"
hdiutil create -volname "QGIS+ ${version}" -srcfolder "${outer_app}" \
    -ov -format UDZO "${output_dmg}"
hdiutil verify "${output_dmg}"
echo "Created QGIS+ macOS package: ${output_dmg}"
