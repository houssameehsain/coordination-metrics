"""Navisworks Clash Detective XML parser.

Parses the XML export format from Autodesk Navisworks Manage's Clash
Detective tool. Supports both summary-level counts and individual clash
point extraction.

Typical XML structure:
    <exchange>
      <batchtest>
        <clashtests>
          <clashtest name="MEP-Structure">
            <clashresults>
              <clashresult name="Clash1" status="new">
                <clashpoint><pos3f x="1200" y="3400" z="5600"/></clashpoint>
              </clashresult>
            </clashresults>
          </clashtest>
        </clashtests>
      </batchtest>
    </exchange>
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Union


def parse_navisworks_xml(xml_path: Union[str, Path]) -> dict:
    """Parse a Navisworks Clash Detective XML export into summary counts.

    Args:
        xml_path: Path to the XML file.

    Returns:
        Dictionary with:
            tests: list of dicts, each with {name, new, active, reviewed,
                   resolved, total}
            totals: aggregate counts across all tests
    """
    xml_path = Path(xml_path)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    tests = []
    grand = {"new": 0, "active": 0, "reviewed": 0, "resolved": 0, "total": 0}

    for test in root.iter("clashtest"):
        name = test.get("name", "Unknown")
        counts = {"new": 0, "active": 0, "reviewed": 0, "resolved": 0}

        for result in test.iter("clashresult"):
            status = (result.get("status") or "new").lower()
            if status in counts:
                counts[status] += 1
            else:
                counts["active"] += 1

        total = sum(counts.values())
        test_result = {"name": name, **counts, "total": total}
        tests.append(test_result)

        for key in grand:
            if key == "total":
                grand["total"] += total
            else:
                grand[key] += counts[key]

    return {"tests": tests, "totals": grand}
