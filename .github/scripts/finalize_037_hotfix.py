from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "tools/tests/test_documentation_contract.py"
content = path.read_text(encoding="utf-8")
old = '    "123456",\n'
new = '    "장치별 6자리 코드",\n'
if content.count(old) != 1:
    raise RuntimeError("obsolete fixed pairing PIN contract was not found exactly once")
content = content.replace(old, new, 1)
needle = "    for fact in INSTALLER_FACTS:\n        assert fact in index, fact\n"
replacement = (
    "    for fact in INSTALLER_FACTS:\n"
    "        assert fact in index, fact\n"
    "    assert \"123456\" not in index\n"
)
if content.count(needle) != 1:
    raise RuntimeError("installer fact assertion block was not found exactly once")
path.write_text(content.replace(needle, replacement, 1), encoding="utf-8", newline="\n")
print("documentation contract now requires device-specific enrollment codes")
