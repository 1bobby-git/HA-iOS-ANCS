#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
idf_path="${IDF_PATH:-}"

if [[ -z "${idf_path}" ]]; then
    bundled_idf="$(cd "${project_root}/../.." && pwd)/work/sdk/esp-idf-6.0.2"
    if [[ -f "${bundled_idf}/export.sh" ]]; then
        idf_path="${bundled_idf}"
    fi
fi

if [[ -z "${idf_path}" || ! -f "${idf_path}/export.sh" ]]; then
    echo "ESP-IDF v6.0.2 경로를 IDF_PATH로 지정하십시오." >&2
    exit 2
fi

# shellcheck disable=SC1090
source "${idf_path}/export.sh"
cd "${project_root}"
idf.py --version
idf.py set-target esp32c6
idf.py fullclean
idf.py build
