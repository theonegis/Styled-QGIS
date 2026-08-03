#!/usr/bin/env python3
"""Apply the small, version-auditable QGIS+ integration patch."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


MAIN_MARKER = "// QGIS+ default style"
CMAKE_MARKER = "# QGIS+ style plugin"
WINDOWS_TRIPLET_MARKER = "# QGIS+ hosted-runner Fortran guard"
WINDOWS_FORTRAN_SWITCH = "set(VCPKG_PROVIDED_FORTRAN ON)"
MACOS_TRIPLET_MARKER = "# QGIS+ minimum deployment target"
MACOS_DEPLOYMENT_TARGET = "12.0"
SIP_OVERLAY_MARKER = "# QGIS+ idempotent SIP entry-point wrappers"
SIP_REGISTRY_BASELINE = "efa37f71edf9c676686040ffc4b7edaf2327e4d0"
PYTHON_RUNTIME_OVERLAY_MARKER = "# QGIS+ reviewed Python runtime dependencies"


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


def patch_macos_triplets(source: Path) -> None:
    """Compile QGIS and every vcpkg dependency for macOS Monterey or newer."""

    triplets = (
        "x64-osx-dynamic-release.cmake",
        "arm64-osx-dynamic-release.cmake",
    )
    pattern = re.compile(
        r"^set\(VCPKG_OSX_DEPLOYMENT_TARGET [^)]+\)$", re.MULTILINE
    )

    for filename in triplets:
        path = source / "vcpkg/triplets" / filename
        content = path.read_text(encoding="utf-8")
        expected = (
            f"{MACOS_TRIPLET_MARKER}\n"
            f"set(VCPKG_OSX_DEPLOYMENT_TARGET {MACOS_DEPLOYMENT_TARGET})"
        )
        if MACOS_TRIPLET_MARKER in content:
            if expected not in content:
                raise RuntimeError(
                    f"{path}: QGIS+ macOS deployment target was modified"
                )
            continue

        matches = pattern.findall(content)
        if len(matches) != 1:
            raise RuntimeError(
                f"{path}: expected exactly one macOS deployment target, "
                f"found {len(matches)}"
            )
        path.write_text(pattern.sub(expected, content, count=1), encoding="utf-8")


def patch_sip_overlay_port(source: Path) -> None:
    """Override the non-idempotent SIP wrapper from python-registry.

    The upstream helper rewrites any first-line shebang.  On macOS the wheel
    installer can already produce a ``/bin/sh`` wrapper, so a second rewrite
    treats ``/bin/sh`` as if it were the Python interpreter and creates a path
    such as ``../../../../../../bin/sh``.  PyQt then fails only after most of
    the dependency graph has compiled.  A narrow overlay keeps Windows on the
    proven upstream implementation and writes relocatable module wrappers on
    Unix platforms.
    """

    port_dir = source / "vcpkg/ports/py-sip"
    portfile = port_dir / "portfile.cmake"
    manifest = port_dir / "vcpkg.json"

    already_patched = False
    if port_dir.exists():
        if portfile.is_file() and SIP_OVERLAY_MARKER in portfile.read_text(
            encoding="utf-8"
        ):
            already_patched = True
        else:
            raise RuntimeError(
                f"{port_dir}: upstream now provides a py-sip overlay; "
                "review it instead of overwriting it"
            )

    qgis_manifest = source / "vcpkg/vcpkg.json"
    try:
        manifest_data = json.loads(qgis_manifest.read_text(encoding="utf-8"))
        registries = manifest_data["vcpkg-configuration"]["registries"]
    except (KeyError, ValueError) as error:
        raise RuntimeError(
            f"{qgis_manifest}: cannot resolve the Python registry baseline"
        ) from error
    python_registries = [
        registry
        for registry in registries
        if registry.get("repository", "").rstrip("/")
        == "https://github.com/open-vcpkg/python-registry"
    ]
    if len(python_registries) != 1:
        raise RuntimeError(
            f"{qgis_manifest}: expected one open-vcpkg Python registry"
        )
    actual_baseline = python_registries[0].get("baseline")
    if actual_baseline != SIP_REGISTRY_BASELINE:
        raise RuntimeError(
            f"{qgis_manifest}: Python registry changed from the reviewed "
            f"{SIP_REGISTRY_BASELINE} baseline to {actual_baseline}; "
            "review py-sip before updating the overlay"
        )

    if already_patched:
        return

    port_dir.mkdir(parents=True)
    portfile.write_text(
        f'''vcpkg_from_pythonhosted(
    OUT_SOURCE_PATH SOURCE_PATH
    PACKAGE_NAME    sip
    VERSION         ${{VERSION}}
    SHA512          4c071ddcd6a16003d825cf6f2951472cb9be1505119eda96371c6a4270ae6ce9f5c7c5cf290316bd9c8006961858d9783a1604478659255057b99374632d4571
)

vcpkg_python_build_and_install_wheel(SOURCE_PATH "${{SOURCE_PATH}}")

vcpkg_install_copyright(FILE_LIST "${{SOURCE_PATH}}/LICENSE")

# Shiver ... where do they come from
file(REMOVE_RECURSE
     "${{CURRENT_PACKAGES_DIR}}/lib/${{python_versioned}}/site-packages/pyqtbuild/bundle/dlls/")

{SIP_OVERLAY_MARKER}
function(qgisplus_fixup_sip_entry_point script module)
  if(VCPKG_TARGET_IS_WINDOWS)
    vcpkg_fixup_shebang(SCRIPT "${{script}}" MODULE "${{module}}")
    return()
  endif()

  # 不保留 wheel 生成的绝对解释器路径；脚本安装到 <triplet>/bin，
  # Python 位于相邻的 <triplet>/tools/python3，因此安装和缓存迁移后仍有效。
  set(script_path "${{CURRENT_PACKAGES_DIR}}/bin/${{script}}")
  set(wrapper [=[#!/bin/sh
exec "$(dirname "$0")/../tools/python3/python3" -m @MODULE@ "$@"
]=])
  string(REPLACE "@MODULE@" "${{module}}" wrapper "${{wrapper}}")
  file(WRITE "${{script_path}}" "${{wrapper}}")
  file(CHMOD "${{script_path}}" PERMISSIONS
       OWNER_READ OWNER_WRITE OWNER_EXECUTE
       GROUP_READ GROUP_EXECUTE
       WORLD_READ WORLD_EXECUTE)
endfunction()

qgisplus_fixup_sip_entry_point("sip-build" "sipbuild.tools.build")
qgisplus_fixup_sip_entry_point("sip-distinfo" "sipbuild.tools.distinfo")
qgisplus_fixup_sip_entry_point("sip-install" "sipbuild.tools.install")
qgisplus_fixup_sip_entry_point("sip-module" "sipbuild.tools.module")
qgisplus_fixup_sip_entry_point("sip-sdist" "sipbuild.tools.sdist")
qgisplus_fixup_sip_entry_point("sip-wheel" "sipbuild.tools.wheel")

set(VCPKG_POLICY_EMPTY_INCLUDE_FOLDER enabled)
''',
        encoding="utf-8",
    )
    manifest.write_text(
        '''{
  "name": "py-sip",
  "version": "6.15.3",
  "description": "A tool that makes it easy to create Python bindings for C and C++ libraries",
  "homepage": "https://www.riverbankcomputing.com/software/sip",
  "dependencies": [
    {
      "name": "py-setuptools",
      "host": true
    },
    {
      "name": "vcpkg-python-scripts",
      "host": true
    }
  ]
}
''',
        encoding="utf-8",
    )


def patch_python_runtime_overlays(source: Path) -> None:
    """Repair reviewed runtime dependencies missing from Python registry ports.

    These overlays deliberately pin the complete upstream port definitions,
    not just manifest ordering.  vcpkg can therefore resolve the dependency
    edge before it starts building and package tests never depend on which
    direct manifest entry happened to be installed first.
    """

    qgis_manifest = source / "vcpkg/vcpkg.json"
    try:
        manifest_data = json.loads(qgis_manifest.read_text(encoding="utf-8"))
        registries = manifest_data["vcpkg-configuration"]["registries"]
    except (KeyError, ValueError) as error:
        raise RuntimeError(
            f"{qgis_manifest}: cannot resolve the Python registry baseline"
        ) from error
    python_registries = [
        registry
        for registry in registries
        if registry.get("repository", "").rstrip("/")
        == "https://github.com/open-vcpkg/python-registry"
    ]
    if len(python_registries) != 1:
        raise RuntimeError(
            f"{qgis_manifest}: expected one open-vcpkg Python registry"
        )
    actual_baseline = python_registries[0].get("baseline")
    if actual_baseline != SIP_REGISTRY_BASELINE:
        raise RuntimeError(
            f"{qgis_manifest}: Python registry changed from the reviewed "
            f"{SIP_REGISTRY_BASELINE} baseline to {actual_baseline}; "
            "review Python runtime overlays before updating"
        )

    overlays = {
        "py-referencing": {
            "portfile": f'''{PYTHON_RUNTIME_OVERLAY_MARKER}
set(VCPKG_BUILD_TYPE release)

vcpkg_from_pythonhosted(
    OUT_SOURCE_PATH SOURCE_PATH
    PACKAGE_NAME    referencing
    VERSION         ${{VERSION}}
    SHA512          8882ac50849e66da6829772bb6140fbd4c853c7fd7410bedd61b29afe071d3c631382f624f203b446887a86cb0885fbdb946092c2d2ecc1907433fd2ef7cb426
    FILENAME        referencing
)

vcpkg_python_build_and_install_wheel(SOURCE_PATH "${{SOURCE_PATH}}")
vcpkg_install_copyright(FILE_LIST "${{SOURCE_PATH}}/COPYING")
vcpkg_python_test_import(MODULE "referencing")
set(VCPKG_POLICY_EMPTY_INCLUDE_FOLDER enabled)
''',
            "manifest": {
                "name": "py-referencing",
                "version": "0.37.0",
                "description": "JSON reference resolution.",
                "homepage": "https://github.com/python-jsonschema/referencing",
                "dependencies": [
                    {"name": "py-attrs", "host": True},
                    {"name": "py-hatchling", "host": True},
                    {"name": "py-rpds", "host": True},
                    {"name": "py-setuptools", "host": True},
                    "py-typing-extensions",
                    "python3",
                    {"name": "vcpkg-python-scripts", "host": True},
                ],
            },
        },
        "py-libpysal": {
            "portfile": f'''{PYTHON_RUNTIME_OVERLAY_MARKER}
vcpkg_from_pythonhosted(
    OUT_SOURCE_PATH SOURCE_PATH
    PACKAGE_NAME    libpysal
    VERSION         ${{VERSION}}
    SHA512          eaab85b8ce83bccd9cb22671f5e27a1db245db850bef7e80f37ce667876bbed91224a20d72ee976f9fbdc9d3f3a90d58343bde1cd0b6f9a2fe1bbf5abd23be3a
    FILENAME        libpysal
)

vcpkg_python_build_and_install_wheel(SOURCE_PATH "${{SOURCE_PATH}}")
vcpkg_install_copyright(FILE_LIST "${{SOURCE_PATH}}/LICENSE.txt")
vcpkg_python_test_import(MODULE "libpysal")
set(VCPKG_POLICY_EMPTY_INCLUDE_FOLDER enabled)
''',
            "manifest": {
                "name": "py-libpysal",
                "version": "4.14.1",
                "description": (
                    "Core components of PySAL - A library of spatial "
                    "analysis functions."
                ),
                "homepage": "https://pysal.org/libpysal",
                "license": "BSD-3-Clause",
                "dependencies": [
                    "py-beautifulsoup4",
                    "py-geopandas",
                    "py-jinja2",
                    "py-numpy",
                    "py-packaging",
                    "py-pandas",
                    "py-platformdirs",
                    "py-requests",
                    "py-scikit-learn",
                    "py-scipy",
                    {"name": "py-setuptools", "host": True},
                    {"name": "py-setuptools-scm", "host": True},
                    "py-shapely",
                    "python3",
                    {"name": "vcpkg-python-scripts", "host": True},
                ],
            },
        },
    }

    for port_name, overlay in overlays.items():
        port_dir = source / "vcpkg/ports" / port_name
        portfile = port_dir / "portfile.cmake"
        manifest = port_dir / "vcpkg.json"
        if port_dir.exists():
            if (
                portfile.is_file()
                and manifest.is_file()
                and PYTHON_RUNTIME_OVERLAY_MARKER
                in portfile.read_text(encoding="utf-8")
            ):
                continue
            raise RuntimeError(
                f"{port_dir}: upstream now provides a {port_name} overlay; "
                "review it instead of overwriting it"
            )

        port_dir.mkdir(parents=True)
        portfile.write_text(str(overlay["portfile"]), encoding="utf-8")
        manifest.write_text(
            json.dumps(overlay["manifest"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="QGIS source directory")
    args = parser.parse_args()
    source = args.source.resolve()

    try:
        patch_main(source)
        patch_cmake(source)
        patch_windows_triplet(source)
        patch_macos_triplets(source)
        patch_sip_overlay_port(source)
        patch_python_runtime_overlays(source)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"QGIS+ patch applied to {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
