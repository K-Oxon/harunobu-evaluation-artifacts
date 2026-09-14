"""Load DECO table ranges and cell roles into the evaluation data model. Depends on DECO CSV annotations and returns in-memory documents."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from scripts import paths
from scripts.ir import IRBBox, IRCellRole, IRDocument, IRSheet, IRTable, Role


DECO_ROLE_MAP: dict[str, Role] = {
    "Header": "Header",
    "GroupHead": "Header",
    "Data": "Data",
    "Derived": "Data",
    "MetaTitle": "Other",
    "Notes": "Other",
    "Other": "Other",
}


_MAX_CELL_SPAN = 10_000


class _SheetAcc:

    def __init__(self, sheet_name: str, sheet_index: int) -> None:
        self.sheet_name = sheet_name
        self.sheet_index = sheet_index
        self.tables: list[IRTable] = []
        self.cell_roles: list[IRCellRole] = []


def _acc_for(
    store: dict[str, dict[str, _SheetAcc]], file_name: str, sheet_name: str, sheet_index: int
) -> _SheetAcc:
    by_sheet = store.setdefault(file_name, {})
    acc = by_sheet.get(sheet_name)
    if acc is None:
        acc = _SheetAcc(sheet_name, sheet_index)
        by_sheet[sheet_name] = acc
    return acc


def _to_int(value: str) -> int:
    return int(value.strip())


def load_deco(
    file_names: Iterable[str],
    *,
    range_csv: Path | None = None,
    cell_csv: Path | None = None,
) -> dict[str, IRDocument]:
    range_csv = range_csv or paths.DECO_RANGE_CSV
    cell_csv = cell_csv or paths.DECO_CELL_CSV
    targets = set(file_names)

    store: dict[str, dict[str, _SheetAcc]] = {}


    with open(range_csv, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["FileName"] not in targets or row["AnnotationLabel"] != "Table":
                continue
            acc = _acc_for(store, row["FileName"], row["SheetName"], _to_int(row["SheetIndex"]))
            acc.tables.append(
                IRTable(
                    bbox=IRBBox(
                        first_row=_to_int(row["FirstRow"]),
                        first_col=_to_int(row["FirstColumn"]),
                        last_row=_to_int(row["LastRow"]),
                        last_col=_to_int(row["LastColumn"]),
                    )
                )
            )


    with open(cell_csv, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["FileName"] not in targets:
                continue
            role = DECO_ROLE_MAP.get(row["AnnotationLabel"])
            if role is None:
                continue
            first_row = _to_int(row["FirstRow"])
            first_col = _to_int(row["FirstColumn"])
            last_row = _to_int(row["LastRow"])
            last_col = _to_int(row["LastColumn"])
            if (last_row - first_row) > _MAX_CELL_SPAN or (last_col - first_col) > _MAX_CELL_SPAN:
                continue
            acc = _acc_for(store, row["FileName"], row["SheetName"], _to_int(row["SheetIndex"]))
            for r in range(first_row, last_row + 1):
                for c in range(first_col, last_col + 1):
                    acc.cell_roles.append(IRCellRole(row=r, col=c, role=role))


    result: dict[str, IRDocument] = {}
    for file_name, by_sheet in store.items():
        sheets = [
            IRSheet(
                sheet_name=acc.sheet_name,
                sheet_index=acc.sheet_index,
                tables=acc.tables,
                cell_roles=acc.cell_roles,
            )
            for acc in by_sheet.values()
        ]
        result[file_name] = IRDocument(file_name=file_name, source="deco", sheets=sheets)
    return result


def annotated_file_names(range_csv: Path | None = None) -> list[str]:
    range_csv = range_csv or paths.DECO_RANGE_CSV
    names: set[str] = set()
    with open(range_csv, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["AnnotationLabel"] == "Table":
                names.add(row["FileName"])
    return sorted(names)
