#!/bin/bash

set -euo pipefail

if (( $# != 5 )); then
    echo "Usage: $0 QGIS.app LAUNCHER ARCH VERSION OUTPUT.dmg" >&2
    exit 2
fi

official_app="$1"
launcher="$2"
target_arch="$3"
version="$4"
output_dmg="$5"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
theme_source="${repo_root}/themes/QGISPlus Material"
theme_plugin_source="${repo_root}/plugins/qgisplus_theme"
work_root="$(mktemp -d "${TMPDIR:-/tmp}/qgisplus-package.XXXXXX")"
outer_app="${work_root}/QGIS+.app"

cleanup() {
    if [[ "${QGISPLUS_KEEP_PACKAGE_WORK:-0}" == "1" ]]; then
        echo "Preserved package work directory: ${work_root}" >&2
    else
        rm -rf "${work_root}"
    fi
}
trap cleanup EXIT

case "${target_arch}" in
    x86_64|arm64) ;;
    *) echo "Unsupported macOS architecture: ${target_arch}" >&2; exit 2 ;;
esac

test -f "${official_app}/Contents/Info.plist"
test -x "${launcher}"
test -f "${theme_source}/style.qss"
test -f "${theme_source}/variables.qss"
test -f "${theme_source}/palette.txt"
test -f "${theme_plugin_source}/__init__.py"
test -f "${theme_plugin_source}/plugin.py"
test -f "${theme_plugin_source}/metadata.txt"

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

mkdir -p "${outer_app}/Contents/MacOS" "${outer_app}/Contents/Resources"
inner_app="${outer_app}/Contents/Resources/QGIS.app"
ditto "${official_app}" "${inner_app}"
# 允许用旧 QGIS+ 包作为本地测试输入，但最终包中绝不保留旧 Style 插件。
find "${inner_app}/Contents/PlugIns/styles" -maxdepth 1 -type f \
    -iname '*qgisplusstyle*' -delete 2>/dev/null || true
ditto "${official_icon}" "${outer_app}/Contents/Resources/QGISPlus.icns"
ditto "${repo_root}/packaging/qgisplus-global-settings.ini" \
    "${outer_app}/Contents/Resources/qgisplus-global-settings.ini"
printf '%s\n' "${official_executable}" \
    > "${outer_app}/Contents/Resources/qgisplus-executable.txt"

# QGIS 原生 UI Theme 目录由 QGIS 自己加载。这里只复制 QSS/Palette/SVG，
# 不注入 QStylePlugin，也不改变 Qt library path。
qgis_theme_root="${inner_app}/Contents/Resources/qgis/resources/themes"
if [[ ! -d "${qgis_theme_root}" ]]; then
    echo "Official QGIS UI theme root is missing: ${qgis_theme_root}" >&2
    exit 1
fi
ditto "${theme_source}" "${qgis_theme_root}/QGISPlus Material"

# QGIS 在 Python 插件加载前已经完成初次主题扫描。这个极小插件只将上述
# 静态 QSS 目录注册进 QGIS 原生主题注册表，并按全局设置启用它。
qgis_python_plugin_root="${inner_app}/Contents/Resources/qgis/python/plugins"
if [[ ! -d "${qgis_python_plugin_root}" ]]; then
    echo "Official QGIS Python plugin root is missing: ${qgis_python_plugin_root}" >&2
    exit 1
fi
ditto "${theme_plugin_source}" \
    "${qgis_python_plugin_root}/qgisplus_theme"

ditto "${launcher}" "${outer_app}/Contents/MacOS/QGISPlusLauncher"
chmod 755 "${outer_app}/Contents/MacOS/QGISPlusLauncher"
sed "s/@VERSION@/${version}/g" \
    "${repo_root}/packaging/macos/Info.plist.in" \
    > "${outer_app}/Contents/Info.plist"

qgis_binary="${inner_app}/Contents/MacOS/${official_executable}"
lipo "${outer_app}/Contents/MacOS/QGISPlusLauncher" \
    -verify_arch "${target_arch}"
lipo "${qgis_binary}" -verify_arch "${target_arch}"

# 新增主题改变了内层 Bundle 的资源封装，因此重新执行 ad-hoc 签名。
codesign --force --sign - --timestamp=none "${inner_app}"
codesign --verify --deep --strict "${inner_app}"
# 外层 App 在 Resources 中嵌套完整 QGIS.app。使用 --deep 让 codesign 先
# 处理所有嵌套代码，再封装外层资源，避免仅重签外壳时返回非零。
codesign --force --deep --sign - --timestamp=none "${outer_app}"
codesign --verify --deep --strict "${outer_app}"

python3 "${repo_root}/scripts/verify_qgis_theme.py" \
    --launcher "${outer_app}/Contents/MacOS/QGISPlusLauncher" \
    --probe "${repo_root}/scripts/qgis_theme_probe.py" \
    --work-dir "${work_root}/theme-probe"

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
