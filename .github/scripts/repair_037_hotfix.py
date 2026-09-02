from pathlib import Path

path = Path(__file__).with_name("repair_037.py")
content = path.read_text(encoding="utf-8")
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
path.write_text(content.replace(old, new, 1), encoding="utf-8", newline="\n")
print("repair script cleanup patch scoped to cleanup_init_resources")
