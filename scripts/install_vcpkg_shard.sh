#!/usr/bin/env bash

set -euo pipefail

if (( $# == 0 )); then
    echo "usage: install_vcpkg_shard.sh <vcpkg-command> [arguments ...]" >&2
    exit 2
fi

max_attempts="${VCPKG_INSTALL_MAX_ATTEMPTS:-3}"
retry_delay="${VCPKG_INSTALL_RETRY_DELAY_SECONDS:-15}"
restored_cache="${VCPKG_RESTORED_BINARY_CACHE:-}"
writable_cache="${VCPKG_WRITABLE_BINARY_CACHE:-}"
install_root="${VCPKG_INSTALL_ROOT_TO_RESET:-}"
buildtrees_root="${VCPKG_BUILDTREES_ROOT_TO_RESET:-}"
idle_timeout="${VCPKG_IDLE_TIMEOUT_SECONDS:-0}"
asset_cache_idle_timeout="${VCPKG_ASSET_CACHE_IDLE_TIMEOUT_SECONDS:-0}"
watchdog_python="${VCPKG_WATCHDOG_PYTHON:-python3}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! "$max_attempts" =~ ^[1-9][0-9]*$ ]]; then
    echo "VCPKG_INSTALL_MAX_ATTEMPTS must be a positive integer" >&2
    exit 2
fi
if [[ ! "$retry_delay" =~ ^[0-9]+$ ]]; then
    echo "VCPKG_INSTALL_RETRY_DELAY_SECONDS must be a non-negative integer" >&2
    exit 2
fi
if [[ ! "$idle_timeout" =~ ^[0-9]+$ ]]; then
    echo "VCPKG_IDLE_TIMEOUT_SECONDS must be a non-negative integer" >&2
    exit 2
fi
if [[ ! "$asset_cache_idle_timeout" =~ ^[0-9]+$ ]]; then
    echo "VCPKG_ASSET_CACHE_IDLE_TIMEOUT_SECONDS must be a non-negative integer" >&2
    exit 2
fi

run_install() {
    if (( idle_timeout > 0 )); then
        if ! command -v "$watchdog_python" >/dev/null 2>&1; then
            echo "Watchdog Python executable not found: ${watchdog_python}" >&2
            return 2
        fi
        watchdog_arguments=(--idle-timeout "$idle_timeout")
        if (( asset_cache_idle_timeout > 0 )); then
            watchdog_arguments+=(
                --asset-cache-idle-timeout "$asset_cache_idle_timeout"
            )
        fi
        "$watchdog_python" "${script_dir}/run_with_idle_timeout.py" \
            "${watchdog_arguments[@]}" -- "$@"
    else
        "$@"
    fi
}

cache_has_files() {
    [[ -n "$restored_cache" && -d "$restored_cache" ]] &&
        [[ -n "$(find "$restored_cache" -mindepth 1 -print -quit 2>/dev/null)" ]]
}

validate_reset_path() {
    local path="$1"
    local variable_name="$2"
    if [[ -z "$path" || "$path" == "/" || "$path" == "\\" || ${#path} -lt 4 ]]; then
        echo "Refusing unsafe cache fallback path from ${variable_name}: '${path}'" >&2
        exit 2
    fi
}

disable_restored_cache() {
    validate_reset_path "$install_root" "VCPKG_INSTALL_ROOT_TO_RESET"
    validate_reset_path "$buildtrees_root" "VCPKG_BUILDTREES_ROOT_TO_RESET"
    validate_reset_path "$writable_cache" "VCPKG_WRITABLE_BINARY_CACHE"

    # 恢复缓存可能损坏时，隔离它并重建安装目录；本次已经生成的可靠二进制包仍保留。
    export VCPKG_BINARY_SOURCES="clear;files,${writable_cache},readwrite"
    rm -rf -- "$install_root" "$buildtrees_root"
    mkdir -p "$install_root" "$buildtrees_root" "$writable_cache"
    restored_cache=""
    echo "::warning::The restored vcpkg cache may be unusable; disabled it and reset the install state for a source-build fallback"
}

merge_restored_cache() {
    cache_has_files || return 0
    validate_reset_path "$writable_cache" "VCPKG_WRITABLE_BINARY_CACHE"
    mkdir -p "$writable_cache"

    # 只补充缺失文件，绝不让旧缓存覆盖本次构建产生的新归档。
    while IFS= read -r -d '' source; do
        relative="${source#"${restored_cache}/"}"
        destination="${writable_cache}/${relative}"
        if [[ -d "$source" ]]; then
            mkdir -p "$destination"
        elif [[ ! -e "$destination" ]]; then
            mkdir -p "$(dirname "$destination")"
            cp "$source" "$destination"
        fi
    done < <(find "$restored_cache" -mindepth 1 -print0)
}

attempt=1
while (( attempt <= max_attempts )); do
    set +e
    run_install "$@"
    status=$?
    set -e

    if (( status == 0 )); then
        merge_restored_cache
        exit 0
    fi
    if (( attempt == max_attempts )); then
        echo "vcpkg install failed after ${max_attempts} attempts" >&2
        exit "$status"
    fi

    if (( status == 125 )) && [[ -n "${X_VCPKG_ASSET_SOURCES:-}" ]]; then
        unset X_VCPKG_ASSET_SOURCES
        echo "::warning::The vcpkg asset cache became idle; disabled it so the next attempt uses authoritative sources"
    fi

    if cache_has_files; then
        disable_restored_cache
    fi

    delay=$((retry_delay * attempt))
    echo "::warning::vcpkg install attempt ${attempt}/${max_attempts} failed with exit code ${status}; retrying in ${delay}s from the existing build state"
    sleep "$delay"
    attempt=$((attempt + 1))
done
