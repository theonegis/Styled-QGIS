#!/usr/bin/env bash

set -euo pipefail

: "${QGIS_SOURCE:?QGIS_SOURCE is required}"
: "${QGIS_BUILD:?QGIS_BUILD is required}"
: "${VCPKG_TARGET_TRIPLET:?VCPKG_TARGET_TRIPLET is required}"
: "${QGISPLUS_MACOS_ARCH:?QGISPLUS_MACOS_ARCH is required}"
: "${QGISPLUS_MACOS_DEPLOYMENT_TARGET:?QGISPLUS_MACOS_DEPLOYMENT_TARGET is required}"

# Autotools, Meson and Python wheel builds do not necessarily inherit CMake's
# deployment target. Exporting the conventional Apple variable makes every
# compiler invocation in the vcpkg dependency graph target Monterey as well.
export MACOSX_DEPLOYMENT_TARGET="${QGISPLUS_MACOS_DEPLOYMENT_TARGET}"

cmake_arguments=(
  -S "${QGIS_SOURCE}"
  -B "${QGIS_BUILD}"
  -G Ninja
)
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
  cmake_arguments+=(
    -D "VCPKG_INSTALL_OPTIONS=--only-binarycaching;--no-downloads"
  )
fi

# Oracle's prebuilt macOS client requires macOS 13 and cannot be rebuilt for
# the QGIS+ Monterey deployment target.
cmake "${cmake_arguments[@]}" \
  -D QGIS_APP_NAME="QGIS+" \
  -D CMAKE_BUILD_TYPE=Release \
  -D WITH_VCPKG=ON \
  -D WITH_3D=OFF \
  -D WITH_PDAL=OFF \
  -D WITH_DRACO=OFF \
  -D WITH_QTWEBENGINE=OFF \
  -D WITH_BINDINGS=ON \
  -D WITH_ORACLE=OFF \
  -D WITH_GEOGRAPHICLIB=OFF \
  -D WITH_SFCGAL=ON \
  -D WITH_PROJ_DATA=ON \
  -D WITH_QSCIAPI=OFF \
  -D ENABLE_TESTS=OFF \
  -D VCPKG_TARGET_TRIPLET="${VCPKG_TARGET_TRIPLET}" \
  -D VCPKG_HOST_TRIPLET="${VCPKG_TARGET_TRIPLET}" \
  -D CMAKE_OSX_DEPLOYMENT_TARGET="${QGISPLUS_MACOS_DEPLOYMENT_TARGET}" \
  -D CMAKE_OSX_ARCHITECTURES="${QGISPLUS_MACOS_ARCH}" \
  -D ENABLE_UNITY_BUILDS=ON \
  -D CMAKE_UNITY_BUILD_BATCH_SIZE=4
