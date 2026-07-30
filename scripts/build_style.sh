#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="${1:-${project_dir}/build-style}"
qlementine_tag="${QLEMENTINE_TAG:-v1.4.2}"

cmake -S "${project_dir}" -B "${build_dir}" -G Ninja \
  -D CMAKE_BUILD_TYPE=Release \
  -D QGISPLUS_QLEMENTINE_TAG="${qlementine_tag}"
cmake --build "${build_dir}"
ctest --test-dir "${build_dir}" --output-on-failure
cmake --install "${build_dir}" --prefix "${build_dir}/stage"

echo "Style plugin: ${build_dir}/stage/styles"

