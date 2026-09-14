"""Convert harunobu layout output to the evaluation data model. Depends on harunobu and scripts.ir and returns in-memory documents."""

from __future__ import annotations

from pathlib import Path

import harunobu
from harunobu.core.layout import LayoutDetector
from harunobu.core.models import Config, Sheet, TableRegion

from scripts.ir import IRBBox, IRCellRole, IRDocument, IRSheet, IRTable, Role


def range_to_bbox(start_row: int, start_col: int, end_row: int, end_col: int) -> IRBBox:
    return IRBBox(
        first_row=start_row - 1,
        first_col=start_col - 1,
        last_row=end_row - 1,
        last_col=end_col - 1,
    )


def _region_cell_roles(sheet: Sheet, region: TableRegion) -> list[IRCellRole]:
    r = region.range
    lay = region.layout
    header_set = set(lay.header_rows)

    roles: list[IRCellRole] = []
    for row in range(r.start_row, r.end_row + 1):
        for col in range(r.start_col, r.end_col + 1):
            cell = sheet.get_cell(row, col)
            if cell is None or cell.value is None:
                continue



            role: Role = "Header" if row in header_set else "Data"
            roles.append(IRCellRole(row=row - 1, col=col - 1, role=role))
    return roles


def others_role(region_type: str) -> Role:
    return "Data" if region_type == "total" else "Other"


def _sheet_to_ir(sheet: Sheet, sheet_index: int, detector: LayoutDetector) -> IRSheet:
    detection = detector.detect_with_others(sheet)

    tables: list[IRTable] = []
    cell_roles: list[IRCellRole] = []
    for region in detection.tables:
        r = region.range
        tables.append(
            IRTable(
                bbox=range_to_bbox(r.start_row, r.start_col, r.end_row, r.end_col),
                header_rows=[hr - 1 for hr in region.layout.header_rows],
                confidence=region.confidence,
                abstain=region.abstain,
            )
        )
        cell_roles.extend(_region_cell_roles(sheet, region))


    for oc in detection.others:
        cell_roles.append(IRCellRole(row=oc.row - 1, col=oc.col - 1, role=others_role(oc.region_type)))

    return IRSheet(
        sheet_name=sheet.name,
        sheet_index=sheet_index,
        tables=tables,
        cell_roles=cell_roles,
        max_row=sheet.max_row,
        max_col=sheet.max_col,
    )


def adapt_file(path: str | Path, mode: str = "standard") -> IRDocument:
    from harunobu.core.reader import read_file

    path = Path(path)
    workbook = read_file(path)
    detector = LayoutDetector(Config(mode=mode))

    sheets = [_sheet_to_ir(sheet, idx, detector) for idx, sheet in enumerate(workbook.sheets)]

    return IRDocument(
        file_name=path.name,
        source="harunobu",
        harunobu_version=harunobu.__version__,
        config={"mode": mode},
        sheets=sheets,
    )
