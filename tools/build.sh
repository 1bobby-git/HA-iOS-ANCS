#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
idf_path="${IDF_PATH:-}"
target="${TARGET:-esp32c6}"
version="${VERSION:-0.3.4}"

if [[ -z "${idf_path}" ]]; then
    bundled_idf="$(cd "${project_root}/../.." && pwd)/work/sdk/esp-idf-6.0.2"
    if [[ -f "${bundled_idf}/export.sh" ]]; then
        idf_path="${bundled_idf}"
    fi
fi

if [[ -z "${idf_path}" || ! -f "${idf_path}/export.sh" ]]; then
    echo "ESP-IDF v6.0.2 was not found. Set IDF_PATH." >&2
    exit 2
fi

# shellcheck disable=SC1090
source "${idf_path}/export.sh"
cd "${project_root}"
idf.py --version
idf.py \
  -B "build-${target}" \
  "-DIDF_TARGET=${target}" \
  "-DSDKCONFIG=${project_root}/sdkconfig.${target}" \
  build
echo "Build complete for ${target}; use tools/build_matrix.ps1 to generate v${version} web-flasher binaries."
