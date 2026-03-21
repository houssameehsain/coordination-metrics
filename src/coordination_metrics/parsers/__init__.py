"""Parsers for common AEC data formats.

Supported sources:
    - Navisworks Clash Detective XML exports
    - BCF-ZIP archives (universal: Solibri, BIMcollab, Revizto, Trimble, etc.)
    - Solibri BCF results (BCF-ZIP preferred, legacy XML fallback)
    - BIM 360 / Autodesk Construction Cloud CSV exports
    - Generic CSV and Excel registers
"""

from coordination_metrics.parsers.bcf import (
    BCFIssue,
    bcf_issues_to_clash_points,
    bcf_to_status_counts,
    parse_bcf_zip,
)
from coordination_metrics.parsers.csv_register import read_register
from coordination_metrics.parsers.navisworks import parse_navisworks_xml

__all__ = [
    "BCFIssue",
    "bcf_issues_to_clash_points",
    "bcf_to_status_counts",
    "parse_bcf_zip",
    "parse_navisworks_xml",
    "read_register",
]
