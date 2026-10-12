"""Execute the firmware clock-only retry policy on the host, without sleeps."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_wifi_retry_policy_executes_with_virtual_time(tmp_path):
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("host C compiler is unavailable; CI requires GCC")
    source = tmp_path / "retry.c"
    source.write_text(r'''
#include <assert.h>
#include "provisioning_retry.h"
int main(void) {
    provisioning_retry_t r;
    provisioning_retry_start(&r, 7, 0);
    assert(provisioning_retry_poll(&r, 0, 0) == PROVISION_RETRY_CONNECT);
    assert(provisioning_retry_poll(&r, 1, 0) == 0);
    provisioning_retry_failed(&r, 100, false, 0);
    assert(r.next_attempt_ms == 5100);
    provisioning_retry_failed(&r, 200, false, 0); /* duplicate */
    assert(r.next_attempt_ms == 5100);
    assert(provisioning_retry_poll(&r, 5100, 0) == PROVISION_RETRY_CONNECT);
    provisioning_retry_failed(&r, 5200, false, 0);
    assert(r.next_attempt_ms == 20200);
    assert(provisioning_retry_poll(&r, 20200, 0) == PROVISION_RETRY_CONNECT);
    provisioning_retry_failed(&r, 20300, false, 0);
    assert(r.next_attempt_ms == 50300);
    assert(provisioning_retry_poll(&r, 45000, 0) == PROVISION_RETRY_OPEN_AP);
    assert(r.enabled); /* AP recovery is never a permanent STA stop. */
    assert(provisioning_retry_poll(&r, 50300, 0) == PROVISION_RETRY_CONNECT);
    provisioning_retry_connected(&r, 51000);
    assert(provisioning_retry_poll(&r, 70300, 0) == 0); /* old timeout */
    assert(r.online && !r.in_flight && r.next_attempt_ms == 0);
    assert(r.backoff == 3);
    provisioning_retry_poll(&r, 81000, 0);
    assert(r.backoff == 0);
    provisioning_retry_failed(&r, 82000, false, 0);
    assert(provisioning_retry_poll(&r, 82000, 0) == PROVISION_RETRY_CONNECT);
    provisioning_retry_pause(&r);
    assert(!provisioning_retry_matches(&r, 7));
    assert(provisioning_retry_poll(&r, 999999, 0) == 0);
    provisioning_retry_start(&r, 8, 1000000);
    assert(!provisioning_retry_matches(&r, 7));
    assert(provisioning_retry_matches(&r, 8));
    provisioning_retry_stop(&r);
    assert(provisioning_retry_poll(&r, UINT64_MAX, 0) == 0);

    /* Boot without AP / five-minute outage: keep trying, bounded jitter. */
    provisioning_retry_start(&r, 9, 0);
    for (uint64_t t = 0; t <= 300000; t += 250) {
        unsigned a = provisioning_retry_poll(&r, t, UINT32_MAX);
        assert(!(a & PROVISION_RETRY_CONNECT) || r.in_flight);
        if (!r.in_flight) assert(provisioning_retry_remaining_ms(&r, t) <= 65000);
    }
    assert(r.enabled && r.attempts >= 5 && r.recovery_announced);
    provisioning_retry_connected(&r, 300001);
    assert(provisioning_retry_poll(&r, 900000, 0) == 0);

    /* Three authentication errors are throttled, not erased or rebooted. */
    provisioning_retry_start(&r, 10, 0);
    for (int i = 0; i < 3; ++i) {
        uint64_t t = r.next_attempt_ms;
        assert(provisioning_retry_poll(&r, t, 0) & PROVISION_RETRY_CONNECT);
        provisioning_retry_failed(&r, t + 1, true, 0);
    }
    assert(r.auth_failures == 3);
    assert(provisioning_retry_remaining_ms(&r, 20003) == 300000);
    return 0;
}
''', encoding="utf-8")
    exe = tmp_path / "retry"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "components/provisioning/include"),
                    str(ROOT / "components/provisioning/provisioning_retry.c"),
                    str(source), "-o", str(exe)], check=True, capture_output=True, text=True)
    subprocess.run([str(exe)], check=True, capture_output=True, text=True)
