from pathlib import Path

script_path = Path(__file__).with_name("repair_037.py")
content = script_path.read_text(encoding="utf-8")
old = '''replace_once(
    "components/ancs_client/ancs_client.c",
    "    taskENTER_CRITICAL(&s_shared_state_lock);\\n"
    "    s_client.connected = false;\\n",
    "    taskENTER_CRITICAL(&s_shared_state_lock);\\n"
    "    s_client.initialized = false;\\n"
    "    s_client.connected = false;\\n",
)
'''
new = '''transform_block(
    "components/ancs_client/ancs_client.c",
    "static void cleanup_init_resources(const init_progress_t *progress)",
    "esp_err_t ancs_client_init(void)",
    lambda block: block.replace(
        "    taskENTER_CRITICAL(&s_shared_state_lock);\\n"
        "    s_client.connected = false;\\n",
        "    taskENTER_CRITICAL(&s_shared_state_lock);\\n"
        "    s_client.initialized = false;\\n"
        "    s_client.connected = false;\\n",
        1,
    ),
)
'''
if content.count(old) != 1:
    raise RuntimeError("repair_037.py cleanup patch was not found exactly once")
script_path.write_text(content.replace(old, new, 1), encoding="utf-8", newline="\n")

contract_path = script_path.parents[2] / "tools/tests/test_ble_security_contract.py"
contract = contract_path.read_text(encoding="utf-8")
old_contract = '    assert "esp_timer_start_once(\\n        s_client.enroll_timer" in source\n'
new_contract = '    assert "esp_timer_start_once(\\n        enroll_timer" in source\n'
if contract.count(old_contract) != 1:
    raise RuntimeError("BLE enrollment timer contract was not found exactly once")
contract_path.write_text(
    contract.replace(old_contract, new_contract, 1),
    encoding="utf-8",
    newline="\n",
)
print("repair script cleanup patch and guarded timer contract corrected")
