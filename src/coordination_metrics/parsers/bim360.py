"""BIM 360 / Autodesk Construction Cloud export parser.

Handles the CSV exports from BIM 360 Model Coordination and ACC
Issues. These exports have specific column naming conventions that
differ from generic registers.

Column mappings:
    BIM 360 Clash Export:
        "Clash ID", "Status", "Assigned To", "Location",
        "Element 1 Category", "Element 2 Category"

    ACC Issues Export:
        "Issue ID", "Title", "Status", "Discipline",
        "Due Date", "Created Date", "Closed Date"
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

from coordination_metrics.parsers.csv_register import read_register


# Column name mappings from BIM 360/ACC format to our standard format
_CLASH_COLUMN_MAP = {
    "Clash ID": "clash_id",
    "clash_id": "clash_id",
    "Status": "status",
    "status": "status",
    "Assigned To": "assigned_to",
    "assigned_to": "assigned_to",
    "Location": "location",
    "location": "location",
    "Element 1 Category": "element_1_category",
    "Element 2 Category": "element_2_category",
    "Clash Point X": "x",
    "Clash Point Y": "y",
    "Clash Point Z": "z",
}

_ISSUE_COLUMN_MAP = {
    "Issue ID": "rfi_id",
    "Title": "description",
    "Status": "status",
    "Discipline": "discipline",
    "Due Date": "due_date",
    "Created Date": "date_submitted",
    "Closed Date": "date_responded",
}


def parse_bim360_clashes(path: Union[str, Path]) -> pd.DataFrame:
    """Parse a BIM 360 Model Coordination clash export.

    Args:
        path: Path to the BIM 360 clash CSV export.

    Returns:
        DataFrame with standardised column names.
    """
    df = read_register(path)
    df = df.rename(columns={c: _CLASH_COLUMN_MAP.get(c, c) for c in df.columns})
    return df


def parse_bim360_issues(path: Union[str, Path]) -> pd.DataFrame:
    """Parse a BIM 360 / ACC Issues export into standard RFI format.

    The output DataFrame matches the format expected by
    ``analyse_rfi_distribution()``.

    Args:
        path: Path to the ACC Issues CSV export.

    Returns:
        DataFrame with columns: rfi_id, date_submitted, date_responded,
        discipline, category (mapped from description).
    """
    df = read_register(path)
    df = df.rename(columns={c: _ISSUE_COLUMN_MAP.get(c, c) for c in df.columns})

    # Ensure required columns exist
    if "category" not in df.columns:
        df["category"] = "BIM 360 Issue"

    return df
