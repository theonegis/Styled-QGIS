#!/usr/bin/env bash

set -euo pipefail

# Intel GitHub runner 把 Homebrew 安装在 /usr/local。部分上游 Python
# 构建脚本会自动探测该系统前缀，从而绕过 vcpkg 清单并链接到 runner
# 自带、最低仅支持 macOS 14/15 的库。先解除这些非声明库的前缀链接，
# 让配置过程只看到 vcpkg 提供的依赖；Cellar 内容不会被删除。
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Homebrew isolation is only required on macOS"
  exit 0
fi

target_arch="${QGISPLUS_MACOS_ARCH:-$(uname -m)}"
if [[ "${target_arch}" != "x86_64" ]]; then
  echo "Homebrew isolation is unnecessary for ${target_arch}"
  exit 0
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required on the Intel build runner" >&2
  exit 1
fi

brew_prefix="$(brew --prefix)"
if [[ "${brew_prefix}" != "/usr/local" ]]; then
  echo "Unexpected Intel Homebrew prefix: ${brew_prefix}" >&2
  exit 1
fi

formulae=(
  gdbm
  libavif
  aom
  dav1d
  libvmaf
  libyaml
)

for formula in "${formulae[@]}"; do
  if brew list --formula "${formula}" >/dev/null 2>&1; then
    echo "Unlinking undeclared Homebrew dependency: ${formula}"
    brew unlink "${formula}"
  fi
done

# brew unlink 应移除 include/lib 中的公开链接。这里立即失败可以避免在
# 数小时后的 DMG 校验阶段才发现 runner 镜像再次引入了同类污染。
for pattern in \
  "${brew_prefix}/include/gdbm*.h" \
  "${brew_prefix}/include/ndbm.h" \
  "${brew_prefix}/include/avif/avif.h" \
  "${brew_prefix}/include/yaml.h" \
  "${brew_prefix}/lib/libgdbm*.dylib" \
  "${brew_prefix}/lib/libavif*.dylib" \
  "${brew_prefix}/lib/libaom*.dylib" \
  "${brew_prefix}/lib/libdav1d*.dylib" \
  "${brew_prefix}/lib/libvmaf*.dylib" \
  "${brew_prefix}/lib/libyaml*.dylib"; do
  if compgen -G "${pattern}" >/dev/null; then
    echo "Homebrew dependency remains visible after unlink: ${pattern}" >&2
    exit 1
  fi
done

echo "Intel Homebrew dependency isolation passed"
