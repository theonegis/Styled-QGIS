#!/usr/bin/env bash

set -euo pipefail

: "${GCC_VERSION:?GCC_VERSION is required}"

# GitHub 镜像预装内容可能随镜像更新而变化。始终通过 Homebrew 的稳定
# opt 前缀定位 gfortran，避免依赖 Cellar 内的版本通配符或芯片架构路径。
formula="gcc@${GCC_VERSION}"
gcc_prefix="$(brew --prefix "${formula}")"
gfortran_executable="${gcc_prefix}/bin/gfortran-${GCC_VERSION}"
gfortran_library="${gcc_prefix}/lib/gcc/${GCC_VERSION}"

if [[ ! -x "${gfortran_executable}" ]]; then
  echo "Missing ${formula} compiler: ${gfortran_executable}" >&2
  exit 1
fi
if [[ ! -d "${gfortran_library}" ]]; then
  echo "Missing ${formula} runtime libraries: ${gfortran_library}" >&2
  exit 1
fi

sudo mkdir -p /usr/local/bin /usr/local/gfortran
sudo ln -sfn "${gfortran_executable}" /usr/local/bin/gfortran
sudo ln -sfn "${gfortran_library}" /usr/local/gfortran/lib

/usr/local/bin/gfortran --version
test -d /usr/local/gfortran/lib
