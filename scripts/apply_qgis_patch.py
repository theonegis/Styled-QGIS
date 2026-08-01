#!/usr/bin/env python3
"""Apply the small, version-auditable QGIS+ integration patch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


MAIN_MARKER = "// QGIS+ default style"
CMAKE_MARKER = "# QGIS+ style plugin"
WINDOWS_TRIPLET_MARKER = "# QGIS+ hosted-runner Fortran guard"
WINDOWS_FORTRAN_SWITCH = "set(VCPKG_PROVIDED_FORTRAN ON)"


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


def patch_windows_triplet(source: Path) -> None:
    """Prevent an unusable runner Flang from disabling vcpkg-gfortran.

    vcpkg's ``vcpkg_find_fortran`` intentionally downloads a matching MSYS2
    gfortran toolchain when ``VCPKG_PROVIDED_FORTRAN`` is enabled.  Older
    vcpkg tool versions instead infer that fallback when no external compiler
    is available.  The GitHub Windows image also exposes LLVM tools, and CMake
    can select ``flang`` even when it cannot compile the LAPACK probe.  The
    explicit switch handles current vcpkg; ignoring only those LLVM prefixes
    preserves compatibility with the older fallback and ensures that the
    ``vcpkg-gfortran`` port installs the required runtime DLLs.
    """

    path = source / "vcpkg/triplets/x64-windows-release.cmake"
    content = path.read_text(encoding="utf-8")
    if WINDOWS_TRIPLET_MARKER in content:
        if WINDOWS_FORTRAN_SWITCH in content:
            return

        # 兼容已经由旧版 QGIS+ 补丁生成的源码目录；CI 使用干净克隆，
        # 本地重复运行 prepare_source.py 时也应自动迁移而不是静默跳过。
        anchor = (
            'if(PORT STREQUAL "vcpkg-gfortran" OR '
            'PORT STREQUAL "lapack-reference")\n'
        )
        migration = (
            anchor
            + "  # Current vcpkg requires an explicit internal Fortran request.\n"
            + f"  {WINDOWS_FORTRAN_SWITCH}\n\n"
        )
        _replace_once(path, anchor, migration)
        return

    guard = f"""

{WINDOWS_TRIPLET_MARKER}
# Windows hosted runners may place LLVM Flang on PATH although it is not a
# usable MSVC-compatible Fortran environment.  LAPACK must then fall back to
# vcpkg's own MinGW gfortran so its runtime DLLs are packaged as dependencies.
if(PORT STREQUAL "vcpkg-gfortran" OR PORT STREQUAL "lapack-reference")
  # vcpkg 2026-07 之后不再在 Windows 上自动探测并回退到内部 Fortran；
  # 必须由 triplet 明确请求。该开关会同时向 LAPACK 传入 gfortran/gcc，
  # 并让 vcpkg-gfortran 打包 libgfortran 等运行时 DLL。
  {WINDOWS_FORTRAN_SWITCH}

  # GitHub 的 windows-2022 镜像同时可能包含独立 LLVM，以及不同版本、
  # 不同 Edition 的 Visual Studio 内置 LLVM。使用 glob 避免把 Enterprise
  # 等 Runner 实现细节写死；这里只影响两个需要 Fortran 的端口。
  set(_qgisplus_llvm_prefixes "C:/Program Files/LLVM")
  file(GLOB _qgisplus_vs_llvm_prefixes LIST_DIRECTORIES true
       "C:/Program Files/Microsoft Visual Studio/*/*/VC/Tools/Llvm")
  list(APPEND _qgisplus_llvm_prefixes ${{_qgisplus_vs_llvm_prefixes}})
  foreach(_qgisplus_llvm_prefix IN LISTS _qgisplus_llvm_prefixes)
    list(APPEND CMAKE_IGNORE_PREFIX_PATH "${{_qgisplus_llvm_prefix}}")
    list(APPEND CMAKE_IGNORE_PATH
         "${{_qgisplus_llvm_prefix}}/bin"
         "${{_qgisplus_llvm_prefix}}/x64/bin")
  endforeach()
  unset(_qgisplus_llvm_prefix)
  unset(_qgisplus_llvm_prefixes)
  unset(_qgisplus_vs_llvm_prefixes)
endif()
"""
    path.write_text(content.rstrip() + guard, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="QGIS source directory")
    args = parser.parse_args()
    source = args.source.resolve()

    try:
        patch_main(source)
        patch_cmake(source)
        patch_windows_triplet(source)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"QGIS+ patch applied to {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
