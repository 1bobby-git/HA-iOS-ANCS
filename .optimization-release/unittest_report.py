"""Run the repository's native unittest discovery without changing its tests."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

if len(sys.argv) != 3:
    raise SystemExit("usage: unittest_report.py TEST_DIRECTORY REPORT.xml")
suite = unittest.defaultTestLoader.discover(sys.argv[1])
result = unittest.TextTestRunner(verbosity=2).run(suite)
root = ET.Element("testsuite", name="native-unittest", tests=str(result.testsRun), failures=str(len(result.failures)), errors=str(len(result.errors)), skipped=str(len(result.skipped)))
for category, items in (("failure", result.failures), ("error", result.errors)):
    for test, details in items:
        case = ET.SubElement(root, "testcase", name=str(test))
        ET.SubElement(case, category).text = details
report = Path(sys.argv[2])
report.parent.mkdir(parents=True, exist_ok=True)
ET.ElementTree(root).write(report, encoding="utf-8", xml_declaration=True)
raise SystemExit(0 if result.wasSuccessful() and result.testsRun else 1)
