#!/usr/bin/env bash

# Validate the complete application bundle and report every problem found in a
# single run. Do not use `set -e`: individual checks intentionally accumulate.
set -uo pipefail

if (( $# != 3 )); then
  echo "Usage: $0 APP_PATH ARCH MAX_DEPLOYMENT_TARGET" >&2
  exit 2
fi

app_path="$1"
required_arch="$2"
max_deployment_target="$3"
main_binary="${app_path}/Contents/MacOS/QGIS+"
error_count=0
macho_count=0

if [[ ! "${max_deployment_target}" =~ ^([0-9]+)\.([0-9]+)(\.[0-9]+)?$ ]]; then
  echo "Invalid maximum deployment target: ${max_deployment_target}" >&2
  exit 2
fi
max_major="${BASH_REMATCH[1]}"
max_minor="${BASH_REMATCH[2]}"

report_error() {
  echo "::error::$*" >&2
  ((error_count += 1))
}

if [[ ! -d "${app_path}" ]]; then
  report_error "QGIS+ application bundle was not found: ${app_path}"
  exit 1
fi
if [[ ! -x "${main_binary}" ]]; then
  report_error "QGIS+ executable was not found: ${main_binary}"
fi

style_plugin="$(find "${app_path}/Contents/PlugIns/styles" \
  -maxdepth 1 -type f -iname '*qgisplusstyle*' -print -quit 2>/dev/null)"
if [[ -z "${style_plugin}" ]]; then
  report_error "QGIS+ style plugin was not found in the application bundle"
fi

for binary in "${main_binary}" "${style_plugin}"; do
  [[ -n "${binary}" && -f "${binary}" ]] || continue
  min_os="$(xcrun vtool -show-build "${binary}" 2>/dev/null | \
    awk '$1 == "minos" { print $2; exit }')"
  if [[ "${min_os}" != "${max_deployment_target}" ]]; then
    report_error \
      "Unexpected deployment target ${min_os:-<missing>} in ${binary}; expected ${max_deployment_target}"
  fi
done

while IFS= read -r -d '' binary; do
  file_description="$(file -b "${binary}" 2>/dev/null)" || {
    report_error "Unable to inspect file type: ${binary}"
    continue
  }
  [[ "${file_description}" == *Mach-O* ]] || continue
  ((macho_count += 1))

  archs="$(lipo -archs "${binary}" 2>/dev/null)" || {
    report_error "Unable to inspect architectures: ${binary}"
    continue
  }
  if [[ " ${archs} " != *" ${required_arch} "* ]]; then
    report_error "Missing ${required_arch} slice in ${binary}: ${archs}"
  fi

  minos_count=0
  while IFS= read -r min_os; do
    [[ -n "${min_os}" ]] || continue
    ((minos_count += 1))
    if [[ ! "${min_os}" =~ ^([0-9]+)\.([0-9]+)(\.[0-9]+)?$ ]]; then
      report_error "Unrecognized deployment target ${min_os} in ${binary}"
      continue
    fi
    min_major="${BASH_REMATCH[1]}"
    min_minor="${BASH_REMATCH[2]}"
    if (( min_major > max_major || \
          (min_major == max_major && min_minor > max_minor) )); then
      report_error \
        "macOS ${max_deployment_target} incompatible binary ${binary}: minos ${min_os}"
    fi
  done < <(otool -l "${binary}" 2>/dev/null | awk '
    $1 == "cmd" {
      deployment_command = ($2 == "LC_BUILD_VERSION" || $2 == "LC_VERSION_MIN_MACOSX")
      next
    }
    deployment_command && ($1 == "minos" || $1 == "version") {
      print $2
      deployment_command = 0
    }
  ')

  if (( minos_count == 0 )); then
    report_error "Missing macOS deployment target in ${binary}"
  fi
done < <(find "${app_path}" -type f -print0)

if (( macho_count == 0 )); then
  report_error "No Mach-O files found in ${app_path}"
else
  echo "Inspected ${macho_count} Mach-O files for ${required_arch} on macOS ${max_deployment_target}."
fi

if [[ -x "${main_binary}" ]]; then
  if ! version_output="$(QT_QPA_PLATFORM=offscreen \
    "${main_binary}" --version 2>&1)"; then
    report_error "QGIS+ failed its offscreen version smoke test"
    echo "${version_output}" >&2
    echo "Main executable dependencies:" >&2
    otool -L "${main_binary}" >&2 || true
  else
    echo "${version_output}"
  fi
fi

if (( error_count != 0 )); then
  echo "macOS bundle verification found ${error_count} problem(s)." >&2
  exit 1
fi

echo "macOS bundle verification passed."
