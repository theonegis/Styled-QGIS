#!/usr/bin/env python3
"""Apply the small, version-auditable QGIS+ integration patch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


MAIN_MARKER = "// QGIS+ default style"
CMAKE_MARKER = "# QGIS+ style plugin"


def _replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    count = content.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one integration anchor, found {count}"
        )
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def patch_main(source: Path) -> None:
    path = source / "src/app/main.cpp"
    content = path.read_text(encoding="utf-8")
    if MAIN_MARKER in content:
        return

    first_anchor = (
        '  QString desiredStyle = settings.value( u"qgis/style"_s ).toString();\n'
        '  const QString theme = settings.value( u"UI/UITheme"_s ).toString();'
    )
    first_replacement = (
        '  QString desiredStyle = settings.value( u"qgis/style"_s ).toString();\n'
        "  const bool hasUserSelectedStyle = !desiredStyle.isEmpty();\n"
        '  const QString theme = settings.value( u"UI/UITheme"_s ).toString();'
    )
    _replace_once(path, first_anchor, first_replacement)

    second_anchor = "  if ( !desiredStyle.isEmpty() )\n  {"
    second_replacement = (
        f"  {MAIN_MARKER}\n"
        "  // 放在 QGIS 自身的 Theme/Adwaita 回退之后，避免默认值被 Fusion 覆盖。\n"
        "  // 用户明确选择的 Style 始终优先；插件缺失时安全使用 QGIS 回退值。\n"
        "  if ( !hasUserSelectedStyle && "
        'QStyleFactory::keys().contains( u"Qlementine"_s, '
        "Qt::CaseInsensitive ) )\n"
        "  {\n"
        '    desiredStyle = u"Qlementine"_s;\n'
        "  }\n"
        "\n"
        "  if ( !desiredStyle.isEmpty() )\n"
        "  {"
    )
    _replace_once(path, second_anchor, second_replacement)


def patch_cmake(source: Path) -> None:
    path = source / "CMakeLists.txt"
    content = path.read_text(encoding="utf-8")
    if CMAKE_MARKER in content:
        return

    anchor = """if (WITH_CORE)
  include(VcpkgInstallDeps)
  include(Bundle)
endif()
"""
    replacement = """if (WITH_CORE)
  include(VcpkgInstallDeps)

  # QGIS+ style plugin
  # 插件与 QGIS 使用同一套 vcpkg/Qt 构建，在 CMake 安装阶段进入 Qt styles 目录。
  set(QGISPLUS_STYLE_PLUGIN "" CACHE FILEPATH
      "Absolute path to the externally built QGIS+ QStyle plugin")
  if(QGISPLUS_STYLE_PLUGIN)
    if(APPLE)
      install(FILES "${QGISPLUS_STYLE_PLUGIN}"
              DESTINATION "${APP_PLUGINS_DIR}/styles")
    elseif(MSVC)
      # Qt6 的 vcpkg bundle 使用 bin/Qt6/plugins；保留 qtplugins 副本以兼容
      # QGIS 在 Windows 上显式添加的历史插件搜索路径。
      install(FILES "${QGISPLUS_STYLE_PLUGIN}"
              DESTINATION "${QGIS_BIN_SUBDIR}/Qt6/plugins/styles")
      install(FILES "${QGISPLUS_STYLE_PLUGIN}"
              DESTINATION "${QGIS_BIN_SUBDIR}/qtplugins/styles")
    endif()
  endif()

  include(Bundle)
endif()
"""
    _replace_once(path, anchor, replacement)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="QGIS source directory")
    args = parser.parse_args()
    source = args.source.resolve()

    try:
        patch_main(source)
        patch_cmake(source)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"QGIS+ patch applied to {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
