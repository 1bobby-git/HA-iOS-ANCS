#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
idf_path="${IDF_PATH:-}"
port="${1:-}"
target="${TARGET:-esp32c6}"

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

if [[ -z "${port}" ]]; then
    port="$(python3 "${project_root}/tools/detect_port.py")"
fi

# shellcheck disable=SC1090
source "${idf_path}/export.sh"
cd "${project_root}"
idf.py --version
idf.py -B "build-${target}" -p "${port}" flash

echo
echo "플래시 완료. iPhone 페어링 후 다음 명령으로 캡처를 검증하십시오:"
echo "python3 tools/verify_capture.py --target ${target} --port ${port} --baud 115200 --timeout 180 --output artifacts/ancs-capture.jsonl"
