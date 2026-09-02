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
new = '''replace_once(
    "components/ancs_client/ancs_client.c",
    "    taskENTER_CRITICAL(&s_shared_state_lock);\\n"
    "    s_client.connected = false;\\n"
    "    s_client.bonded = false;\\n",
    "    taskENTER_CRITICAL(&s_shared_state_lock);\\n"
    "    s_client.initialized = false;\\n"
    "    s_client.connected = false;\\n"
    "    s_client.bonded = false;\\n",
)
'''
if content.count(old) != 1:
    raise RuntimeError("repair_037.py cleanup anchor was not found exactly once")
path.write_text(content.replace(old, new, 1), encoding="utf-8", newline="\n")
print("repair script cleanup anchor corrected")
