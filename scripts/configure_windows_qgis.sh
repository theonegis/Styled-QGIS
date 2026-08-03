#!/usr/bin/env bash

set -euo pipefail

# Windows 上所有会生成临时文件的目录必须与源码同盘。Versioneer 会对
# tempfile.TemporaryDirectory() 与当前源码目录计算相对路径，跨盘会直接失败。
required_variables=(
  QGIS_SOURCE
  QGIS_BUILD
  VCPKG_TRIPLET
  VCPKG_BUILDTREES_ROOT
  GITHUB_WORKSPACE
)
for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "Missing required environment variable: ${variable_name}" >&2
    exit 1
  fi
done

vcpkg_install_options="--x-buildtrees-root=${VCPKG_BUILDTREES_ROOT}"
if [[ "${QGISPLUS_OFFLINE:-0}" == "1" ]]; then
  required_offline_variables=(
    VCPKG_BINARY_SOURCES
    X_VCPKG_ASSET_SOURCES
    X_VCPKG_REGISTRIES_CACHE
  )
  for variable_name in "${required_offline_variables[@]}"; do
    if [[ -z "${!variable_name:-}" ]]; then
      echo "Offline build requires ${variable_name}" >&2
      exit 1
    fi
  done
  IFS=';' read -r -a binary_sources <<< "${VCPKG_BINARY_SOURCES}"
  if (( ${#binary_sources[@]} < 2 )) || [[ "${binary_sources[0]}" != "clear" ]]; then
    echo "Offline build only accepts local files binary caches" >&2
    exit 1
  fi
  for binary_source in "${binary_sources[@]:1}"; do
    if [[ "${binary_source}" != files,* ]]; then
      echo "Offline build rejected non-local binary source: ${binary_source}" >&2
      exit 1
    fi
  done
  if [[ "${X_VCPKG_ASSET_SOURCES}" != "clear;x-block-origin" ]]; then
    echo "Offline build requires exactly clear;x-block-origin" >&2
    exit 1
  fi
  vcpkg_install_options+=";--only-binarycaching;--no-downloads"
fi

cmake -S "${QGIS_SOURCE}" -B "${QGIS_BUILD}" -G Ninja \
  -D CMAKE_BUILD_TYPE=Release \
  -D QGIS_APP_NAME="QGIS+" \
  -D WITH_VCPKG=ON \
  -D VCPKG_TARGET_TRIPLET="${VCPKG_TRIPLET}" \
  -D VCPKG_HOST_TRIPLET="${VCPKG_TRIPLET}" \
  -D WITH_DESKTOP=ON \
  -D WITH_3D=OFF \
  -D WITH_PDAL=OFF \
  -D WITH_BINDINGS=ON \
  -D WITH_GEOGRAPHICLIB=OFF \
  -D WITH_SFCGAL=ON \
  -D ENABLE_TESTS=OFF \
  -D WITH_QTWEBENGINE=OFF \
  -D WITH_QSCIAPI=OFF \
  -D ENABLE_UNITY_BUILDS=ON \
  -D CMAKE_UNITY_BUILD_BATCH_SIZE=4 \
  -D FLEX_EXECUTABLE="${GITHUB_WORKSPACE}/win_flex.exe" \
  -D BISON_EXECUTABLE="${GITHUB_WORKSPACE}/win_bison.exe" \
  -D VCPKG_INSTALL_OPTIONS="${vcpkg_install_options}"
