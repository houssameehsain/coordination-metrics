"""Generic CSV and Excel register parser.

Handles the most common register formats exported from BIM 360, Procore,
Aconex, and manual spreadsheets. Automatically detects delimiter and
encoding for CSV files, and reads .xlsx/.xls via openpyxl/xlrd.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Union

import pandas as pd


def read_register(path: Union[str, Path], **kwargs) -> pd.DataFrame:
    """Read a register file (CSV or Excel) into a DataFrame.

    Supports:
        - .csv files (auto-detects delimiter and encoding)
        - .xlsx / .xls files (requires openpyxl for xlsx)
        - .tsv files (tab-separated)

    Args:
        path: Path to the register file.
        **kwargs: Additional arguments passed to pd.read_csv or pd.read_excel.

    Returns:
        DataFrame with the register contents.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If the file format is not supported.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Register file not found: {path}")

    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, **kwargs)
    elif suffix in (".csv", ".tsv", ".txt"):
        return _read_csv_smart(path, **kwargs)
    else:
        # Try CSV as fallback
        return _read_csv_smart(path, **kwargs)


def _read_csv_smart(path: Path, **kwargs) -> pd.DataFrame:
    """Read a CSV with automatic delimiter and encoding detection.

    Tries UTF-8 first, then falls back to latin-1. Uses csv.Sniffer
    to detect the delimiter from the first few lines.
    """
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(f"Cannot decode {path} with any supported encoding.")

    # Detect delimiter
    try:
        sample = "\n".join(text.splitlines()[:20])
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        sep = ","

    return pd.read_csv(io.StringIO(text), sep=sep, **kwargs)
