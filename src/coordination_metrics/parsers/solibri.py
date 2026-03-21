"""Solibri BCF/results parser.

Solibri's recommended export format is BCF-ZIP, which is the standard
BIM Collaboration Format. This parser:

1. First attempts to parse the file as a BCF-ZIP archive (recommended).
2. Falls back to the legacy XML parser for older Solibri tabular exports.

For best results, export from Solibri as BCF (File > Export > BCF).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Union

from coordination_metrics.parsers.bcf import (
    BCFIssue,
    bcf_to_status_counts,
    parse_bcf_zip,
)


def parse_solibri_results(xml_path: Union[str, Path]) -> dict:
    """Parse a Solibri results export (BCF-ZIP or legacy XML).

    Tries BCF-ZIP first (Solibri's primary export format), then falls
    back to the legacy XML format for backward compatibility.

    Args:
        xml_path: Path to the Solibri export file (.bcf, .bcfzip, or .xml).

    Returns:
        Dictionary with:
            issues: list of dicts with {id, severity, description, status, component}
            summary: {total, critical, major, moderate, minor}
            source_format: "bcf" or "legacy_xml"
    """
    xml_path = Path(xml_path)

    # ---- Attempt 1: BCF-ZIP ----
    if _is_bcf_zip(xml_path):
        bcf_issues = parse_bcf_zip(xml_path)
        return _bcf_to_solibri_result(bcf_issues)

    # ---- Attempt 2: Legacy XML ----
    return _parse_legacy_xml(xml_path)


def _is_bcf_zip(path: Path) -> bool:
    """Check if the file is a valid ZIP archive (BCF-ZIP)."""
    try:
        return zipfile.is_zipfile(path)
    except Exception:
        return False


def _bcf_to_solibri_result(bcf_issues: list[BCFIssue]) -> dict:
    """Convert BCF issues to the legacy Solibri result format."""
    issues = []
    severity_counts = {"critical": 0, "major": 0, "moderate": 0, "minor": 0}

    for issue in bcf_issues:
        # Map BCF priority to Solibri severity
        priority = issue.priority.lower() if issue.priority else ""
        if priority in ("critical", "high"):
            severity = "critical"
        elif priority in ("major", "medium"):
            severity = "major"
        elif priority in ("minor", "low"):
            severity = "minor"
        else:
            severity = "moderate"

        issues.append({
            "id": issue.guid,
            "severity": severity,
            "description": issue.description or issue.title,
            "status": issue.status.lower(),
            "component": issue.type,
        })

        if severity in severity_counts:
            severity_counts[severity] += 1

    return {
        "issues": issues,
        "summary": {
            "total": len(issues),
            **severity_counts,
        },
        "source_format": "bcf",
    }


def _parse_legacy_xml(xml_path: Path) -> dict:
    """Parse a Solibri results XML export (legacy format).

    Args:
        xml_path: Path to the Solibri XML results file.

    Returns:
        Dictionary with issues list and severity summary.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Handle namespace if present
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    issues = []
    severity_counts = {"critical": 0, "major": 0, "moderate": 0, "minor": 0}

    for issue in root.iter(f"{ns}issue"):
        issue_id = issue.get("id", issue.get("guid", ""))
        severity = (issue.findtext(f"{ns}severity") or "moderate").lower()
        description = issue.findtext(f"{ns}description") or ""
        status = issue.findtext(f"{ns}status") or "open"
        component = issue.findtext(f"{ns}component") or ""

        issues.append(
            {
                "id": issue_id,
                "severity": severity,
                "description": description,
                "status": status,
                "component": component,
            }
        )
        if severity in severity_counts:
            severity_counts[severity] += 1

    return {
        "issues": issues,
        "summary": {
            "total": len(issues),
            **severity_counts,
        },
        "source_format": "legacy_xml",
    }
