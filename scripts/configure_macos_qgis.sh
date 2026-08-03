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

# Oracle's prebuilt macOS client requires macOS 13 and cannot be rebuilt for
# the QGIS+ Monterey deployment target.
cmake -S "${QGIS_SOURCE}" -B "${QGIS_BUILD}" -G Ninja \
  -D QGIS_APP_NAME="QGIS+" \
  -D CMAKE_BUILD_TYPE=Release \
  -D WITH_VCPKG=ON \
  -D WITH_QTWEBENGINE=OFF \
  -D WITH_BINDINGS=ON \
  -D WITH_ORACLE=OFF \
  -D WITH_GEOGRAPHICLIB=OFF \
  -D WITH_SFCGAL=ON \
  -D WITH_PROJ_DATA=ON \
  -D WITH_QSCIAPI=OFF \
  -D VCPKG_TARGET_TRIPLET="${VCPKG_TARGET_TRIPLET}" \
  -D VCPKG_HOST_TRIPLET="${VCPKG_TARGET_TRIPLET}" \
  -D CMAKE_OSX_DEPLOYMENT_TARGET="${QGISPLUS_MACOS_DEPLOYMENT_TARGET}" \
  -D CMAKE_OSX_ARCHITECTURES="${QGISPLUS_MACOS_ARCH}" \
  -D ENABLE_UNITY_BUILDS=ON \
  -D CMAKE_UNITY_BUILD_BATCH_SIZE=4
