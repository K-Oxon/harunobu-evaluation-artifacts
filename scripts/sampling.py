"""Select a deterministic stratified DECO evaluation sample from DECO annotations and workbook paths."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from random import Random

from scripts import paths


@dataclass
class FileInfo:
    file_name: str
    owner: str
    n_tables: int
    n_sheets: int
    has_derived: bool

    def table_bucket(self) -> str:
        if self.n_tables <= 1:
            return "1"
        if self.n_tables <= 3:
            return "2-3"
        return "4+"


def build_file_index(range_csv: Path | None = None) -> dict[str, FileInfo]:
    range_csv = range_csv or paths.DECO_RANGE_CSV
    n_tables: dict[str, int] = defaultdict(int)
    sheets: dict[str, set[str]] = defaultdict(set)
    has_derived: dict[str, bool] = defaultdict(bool)

    with open(range_csv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            fn = r["FileName"]
            label = r["AnnotationLabel"]
            sheets[fn].add(r["SheetName"])
            if label == "Table":
                n_tables[fn] += 1
            elif label == "Derived":
                has_derived[fn] = True

    index: dict[str, FileInfo] = {}
    for fn in n_tables:
        index[fn] = FileInfo(
            file_name=fn,
            owner=fn.split("__", 1)[0],
            n_tables=n_tables[fn],
            n_sheets=len(sheets[fn]),
            has_derived=has_derived[fn],
        )
    return index


def existing_xlsx_names(xlsx_dir: Path | None = None) -> set[str]:
    xlsx_dir = xlsx_dir or paths.DECO_XLSX_DIR
    return {p.name for p in xlsx_dir.glob("*.xlsx")}


def select_stratified(
    index: dict[str, FileInfo],
    existing: set[str],
    n: int,
    seed: int = 0,
) -> list[FileInfo]:
    candidates = [fi for fi in index.values() if fi.file_name in existing]

    strata: dict[tuple[str, str], list[FileInfo]] = defaultdict(list)
    for fi in candidates:
        strata[(fi.owner, fi.table_bucket())].append(fi)
    for key in strata:
        strata[key].sort(key=lambda fi: (not fi.has_derived, fi.file_name))

    stratum_keys = sorted(strata.keys())
    Random(seed).shuffle(stratum_keys)

    selected: list[FileInfo] = []
    cursors = {k: 0 for k in stratum_keys}
    while len(selected) < n:
        progressed = False
        for k in stratum_keys:
            if len(selected) >= n:
                break
            i = cursors[k]
            if i < len(strata[k]):
                selected.append(strata[k][i])
                cursors[k] = i + 1
                progressed = True
        if not progressed:
            break
    return selected


def manifest(infos: list[FileInfo]) -> list[dict]:
    return [
        {
            "file": fi.file_name,
            "owner": fi.owner,
            "n_tables": fi.n_tables,
            "has_derived": fi.has_derived,
        }
        for fi in infos
    ]
