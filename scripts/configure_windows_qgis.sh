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

cmake -S "${QGIS_SOURCE}" -B "${QGIS_BUILD}" -G Ninja \
  -D CMAKE_BUILD_TYPE=Release \
  -D QGIS_APP_NAME="QGIS+" \
  -D WITH_VCPKG=ON \
  -D VCPKG_TARGET_TRIPLET="${VCPKG_TRIPLET}" \
  -D VCPKG_HOST_TRIPLET="${VCPKG_TRIPLET}" \
  -D WITH_DESKTOP=ON \
  -D WITH_3D=ON \
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
  -D VCPKG_INSTALL_OPTIONS="--x-buildtrees-root=${VCPKG_BUILDTREES_ROOT}"
