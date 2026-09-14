"""Load and normalize the tracked e-Stat survey frame from data/estat/frame/gov_stats_codes-2026-07-06.csv."""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from scripts import paths



_CIRCLES = {"〇", "○", "◯"}

_STATS_TYPES = {"基幹統計", "一般統計", "業務統計", "加工統計", "その他"}


@dataclass(frozen=True)
class FrameRow:
    gov_stats_code: str
    gov_stats_name: str
    organization: str
    stats_type: str
    cycle: str
    has_file: bool
    has_db: bool


def _normalize_stats_type(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").strip()
    if text in _STATS_TYPES:
        return text

    for st in _STATS_TYPES:
        if st in text:
            return st
    return ""


def load_frame(frame_csv: Path | None = None) -> dict[str, FrameRow]:
    frame_csv = frame_csv or paths.ESTAT_FRAME_CSV
    rows: dict[str, FrameRow] = {}
    with open(frame_csv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            code = (r["gov_stats_code"] or "").strip()
            if not code:
                continue
            rows[code] = FrameRow(
                gov_stats_code=code,
                gov_stats_name=(r["gov_stats_name"] or "").strip(),
                organization=(r["organization"] or "").strip(),
                stats_type=_normalize_stats_type(r["stats_type"]),
                cycle=(r["cycle"] or "").strip(),
                has_file=(r["has_file"] or "").strip() in _CIRCLES,
                has_db=(r["has_db"] or "").strip() in _CIRCLES,
            )
    return rows


def population_codes(frame: dict[str, FrameRow]) -> list[str]:
    return [code for code, row in frame.items() if row.has_file]
