"""Define tracked input, downloaded input, and generated result paths for the repository."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"


DECO_DIR = DATA_DIR / "deco"
DECO_XLSX_DIR = DECO_DIR / "xlsx"
DECO_RANGE_CSV = DECO_DIR / "annotations" / "rangeAnnotations.csv"
DECO_CELL_CSV = DECO_DIR / "annotations" / "cellAnnotations.csv"


TABLESENSE_DIR = DATA_DIR / "tablesense"
TABLESENSE_TSV = TABLESENSE_DIR / "annotations" / "TableSenseTableRangeAnnotations.txt"
TABLESENSE_RAW_DIR = TABLESENSE_DIR / "raw"
TABLESENSE_XLSX_DIR = TABLESENSE_DIR / "xlsx"
TABLESENSE_CONVERSION_JSON = RESULTS_DIR / "layout" / "tablesense-conversion.json"


ESTAT_DIR = DATA_DIR / "estat"
ESTAT_FRAME_CSV = ESTAT_DIR / "frame" / "gov_stats_codes-2026-07-06.csv"
ESTAT_ENUM_DIR = ESTAT_DIR / "enumeration"
ESTAT_MANIFEST = ESTAT_DIR / "tier1" / "manifest.json"
ESTAT_XLSX_DIR = ESTAT_DIR / "tier1" / "xlsx"
