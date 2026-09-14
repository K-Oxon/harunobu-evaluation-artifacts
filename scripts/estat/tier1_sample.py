"""Select a stratified e-Stat sample from the tracked template frame. Writes selection metadata and a manifest under data/estat/tier1/ and can download source workbooks."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from random import Random
from typing import Any

from scripts import paths
from scripts.estat.starter_set import download as download_entry


CELL_ORG_CODES: dict[str, str] = {
    "00200": "総務省",
    "00550": "経済産業省",
    "00450": "厚生労働省",
    "00500": "農林水産省",
    "00600": "国土交通省",
}
OTHER_ORG = "その他集約"
ORG_ORDER = [*CELL_ORG_CODES.values(), OTHER_ORG]

MAIN_STAT_TYPES = ("基幹統計", "一般統計", "業務統計")
REFERENCE_STAT_TYPES = ("加工統計", "その他")
REFERENCE_ORG = "―"

PER_CELL = 30
DEFAULT_SEED = 20260804
MIN_SURVEYS_PER_CELL = 2
MAX_RESAMPLE_ATTEMPTS = 20

DEFAULT_TEMPLATES = paths.ESTAT_DIR / "frame" / "templates-v2.csv.gz"
TIER1_DIR = paths.ESTAT_DIR / "tier1"
SELECTION_JSON = TIER1_DIR / "selection-current.json"

_STAT_INF_ID_RE = re.compile(r"statInfId=(\d+)")





def org_label(gov_org_code: str) -> str:
    return CELL_ORG_CODES.get(gov_org_code, OTHER_ORG)


def cell_of(row: dict[str, str]) -> tuple[str, str] | None:
    stat_type = row["stat_type"]
    if stat_type in MAIN_STAT_TYPES:
        return (stat_type, org_label(row["gov_org_code"]))
    if stat_type in REFERENCE_STAT_TYPES:
        return (stat_type, REFERENCE_ORG)
    return None


def cell_keys() -> list[tuple[str, str]]:
    keys = [(st, org) for st in MAIN_STAT_TYPES for org in ORG_ORDER]
    keys += [(st, REFERENCE_ORG) for st in REFERENCE_STAT_TYPES]
    return keys


def cell_id(cell: tuple[str, str]) -> str:
    return f"{cell[0]}×{cell[1]}"





def load_pools(templates_csv: Path) -> tuple[dict[tuple[str, str], list[dict[str, str]]], dict[str, Any]]:
    pools: dict[tuple[str, str], list[dict[str, str]]] = {k: [] for k in cell_keys()}
    excluded: Counter[tuple[str, str]] = Counter()
    n_rows = 0
    opener = gzip.open if templates_csv.suffix == ".gz" else open
    with opener(templates_csv, mode="rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            n_rows += 1
            cell = cell_of(row)
            if cell is None:
                excluded[(row["gov_stats_code"], row["gov_stats_name"])] += 1
                continue
            pools[cell].append(row)

    for rows in pools.values():
        rows.sort(key=lambda r: r["template_id"])

    excluded_info = {
        "reason": "フレーム CSV の stats_type が空(原本が空欄。推定はしない)",
        "n_templates": sum(excluded.values()),
        "surveys": [
            {"gov_stats_code": code, "gov_stats_name": name, "n_templates": n}
            for (code, name), n in sorted(excluded.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }
    return pools, {"n_rows": n_rows, "excluded": excluded_info}





def _cell_rng(seed: int, cell: tuple[str, str], attempt: int) -> Random:
    digest = hashlib.sha256(f"{seed}:{cell_id(cell)}:{attempt}".encode()).hexdigest()
    return Random(int(digest[:16], 16))


def sample_cell(
    pool: list[dict[str, str]], cell: tuple[str, str], *, n: int, seed: int
) -> tuple[list[dict[str, str]], int, str]:
    if not pool:
        return [], 0, "empty_pool"
    take = min(n, len(pool))
    pool_surveys = {r["gov_stats_code"] for r in pool}
    if len(pool_surveys) < MIN_SURVEYS_PER_CELL:
        return _cell_rng(seed, cell, 0).sample(pool, take), 0, "impossible"

    for attempt in range(MAX_RESAMPLE_ATTEMPTS):
        picked = _cell_rng(seed, cell, attempt).sample(pool, take)
        if len({r["gov_stats_code"] for r in picked}) >= MIN_SURVEYS_PER_CELL:
            return picked, attempt, "ok"
    return picked, MAX_RESAMPLE_ATTEMPTS, "unsatisfied"


def select(
    pools: dict[tuple[str, str], list[dict[str, str]]], *, per_cell: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selection: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for cell in cell_keys():
        pool = pools[cell]
        picked, retries, status = sample_cell(pool, cell, n=per_cell, seed=seed)
        survey_counts = Counter(r["gov_stats_code"] for r in pool)
        top_survey, top_n = survey_counts.most_common(1)[0] if survey_counts else ("", 0)
        summary.append(
            {
                "cell": cell_id(cell),
                "stat_type": cell[0],
                "gov_org": cell[1],
                "pool_n_templates": len(pool),
                "pool_n_surveys": len(survey_counts),
                "pool_top_survey": top_survey,
                "pool_top_survey_share": round(top_n / len(pool), 4) if pool else None,
                "n_selected": len(picked),
                "selected_n_surveys": len({r["gov_stats_code"] for r in picked}),
                "sampling_fraction": round(len(picked) / len(pool), 4) if pool else None,
                "resample_attempts": retries,
                "min_survey_constraint": status,
                "shortfall": max(0, per_cell - len(picked)),
            }
        )
        for row in picked:
            selection.append(dict(row, _cell=cell_id(cell), _cell_org=cell[1]))
    return selection, summary




MANIFEST_ENTRY_FIELDS = [
    "cell",
    "gov_stats_code",
    "gov_stats_name",
    "stat_type",
    "gov_org",
    "gov_org_code",
    "gov_org_raw",
    "template_id",
    "dataset_title_stem",
    "table_no",
    "table_name",
    "representative_resource_id",
    "stat_inf_id",
    "representative_dataset_id",
    "representative_dataset_title",
    "representative_url",
    "survey_date",
    "n_period_instances",
    "n_distinct_survey_dates",
    "n_region_variants",
    "has_db",
    "format",
    "key_source",
    "table_shape",
]

DL_FIELDS = ["dl_status", "file_name", "bytes", "sha256", "fetched_at", "dl_error"]


def to_entry(row: dict[str, Any]) -> dict[str, Any]:
    m = _STAT_INF_ID_RE.search(row["representative_url"])
    return {
        "cell": row["_cell"],
        "gov_stats_code": row["gov_stats_code"],
        "gov_stats_name": row["gov_stats_name"],
        "stat_type": row["stat_type"],
        "gov_org": row["_cell_org"],
        "gov_org_code": row["gov_org_code"],
        "gov_org_raw": row["gov_org"],
        "template_id": row["template_id"],
        "dataset_title_stem": row["dataset_title_stem"],
        "table_no": row["table_no"],
        "table_name": row["table_name"],
        "representative_resource_id": row["representative_resource_id"],
        "stat_inf_id": m.group(1) if m else "",
        "representative_dataset_id": row["representative_dataset_id"],
        "representative_dataset_title": row["representative_dataset_title"],
        "representative_url": row["representative_url"],
        "survey_date": row["survey_date_latest"],
        "n_period_instances": int(row["n_period_instances"] or 0),
        "n_distinct_survey_dates": int(row["n_distinct_survey_dates"] or 0),
        "n_region_variants": int(row["n_region_variants"] or 0),
        "has_db": row["has_db"],
        "format": row["format"],
        "key_source": row["key_source"],
        "table_shape": None,
    }


def build_selection_report(
    *, templates_csv: Path, seed: int, per_cell: int, meta: dict[str, Any],
    summary: list[dict[str, Any]], entries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "adr": "docs/decisions/2026-07-06-e-stat-sampling-scale.md#5-抽出法規模段階式",
        "source_templates": str(templates_csv),
        "dedup_scheme_version": 2,
        "seed": seed,
        "per_cell": per_cell,
        "frame": {
            "n_template_rows": meta["n_rows"],
            "n_in_scope": meta["n_rows"] - meta["excluded"]["n_templates"],
            "excluded": meta["excluded"],
        },
        "n_selected": len(entries),
        "n_distinct_surveys": len({e["gov_stats_code"] for e in entries}),
        "cells": summary,
    }





def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--templates", type=Path, default=DEFAULT_TEMPLATES)
    parser.add_argument("--out-dir", type=Path, default=TIER1_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--per-cell", type=int, default=PER_CELL)
    parser.add_argument("--select-only", action="store_true",
                        help="選定サマリのみ表示(manifest も DL も書かない)")
    parser.add_argument("--download", action="store_true",
                        help="実 DL を行う(G1 承認後。既定は manifest のみ書く)")
    parser.add_argument("--sleep", type=float, default=1.0, help="DL 間 sleep 秒")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args(argv)


def print_summary(report: dict[str, Any]) -> None:
    ex = report["frame"]["excluded"]
    print(f"母集団: {report['frame']['n_template_rows']:,} テンプレ "
          f"→ 対象 {report['frame']['n_in_scope']:,}"
          f"(除外 {ex['n_templates']:,} = stat_type 空 {len(ex['surveys'])} 調査)")
    print(f"seed={report['seed']} per_cell={report['per_cell']} "
          f"→ 選定 {report['n_selected']} 件 / {report['n_distinct_surveys']} 調査\n")
    print(f"{'セル':<22} {'母数':>8} {'調査':>5} {'最大単一調査':>12} {'抽出':>5} {'調査':>5} {'抽出率':>7} {'引直':>4}")
    for c in report["cells"]:
        share = "―" if c["pool_top_survey_share"] is None else f"{100 * c['pool_top_survey_share']:.1f}%"
        frac = "―" if c["sampling_fraction"] is None else f"{100 * c['sampling_fraction']:.2f}%"
        flag = "  ← 単一調査支配" if (c["pool_top_survey_share"] or 0) > 0.5 else ""
        note = "" if c["min_survey_constraint"] == "ok" else f"  [{c['min_survey_constraint']}]"
        print(f"  {c['cell']:<20} {c['pool_n_templates']:>8,} {c['pool_n_surveys']:>5} "
              f"{share:>12} {c['n_selected']:>5} {c['selected_n_surveys']:>5} {frac:>7} "
              f"{c['resample_attempts']:>4}{flag}{note}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pools, meta = load_pools(args.templates)
    rows, summary = select(pools, per_cell=args.per_cell, seed=args.seed)
    entries = [to_entry(r) for r in rows]
    report = build_selection_report(
        templates_csv=args.templates, seed=args.seed, per_cell=args.per_cell,
        meta=meta, summary=summary, entries=entries,
    )
    print_summary(report)

    shortfall = sum(c["shortfall"] for c in summary)
    unsatisfied = [c["cell"] for c in summary if c["min_survey_constraint"] not in ("ok",)]
    if shortfall:
        print(f"\n[注意] セル充足不足 合計 {shortfall} 件")
    if unsatisfied:
        print(f"[注意] >=2 調査制約を満たさないセル: {', '.join(unsatisfied)}")

    if args.select_only:
        return 0

    SELECTION_JSON.parent.mkdir(parents=True, exist_ok=True)
    SELECTION_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ {SELECTION_JSON}")

    n_error = 0
    if args.download:
        files_dir = args.out_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        for i, entry in enumerate(entries):
            if i and args.sleep:
                time.sleep(args.sleep)
            entry.update(download_entry(entry, files_dir, timeout=args.timeout, retries=args.retries))
            if entry["dl_status"] != "ok":
                n_error += 1
            if (i + 1) % 25 == 0 or entry["dl_status"] != "ok":
                print(f"  DL[{i + 1}/{len(entries)}] {entry['gov_stats_name'][:20]}: "
                      f"{entry['dl_status']} ({entry.get('bytes', 0):,}B)", flush=True)

    manifest = {
        "adr": "docs/decisions/2026-07-06-e-stat-sampling-scale.md",
        "tier": "1",
        "source_templates": str(args.templates),
        "dedup_scheme_version": 2,
        "sampling_seed": args.seed,
        "per_cell": args.per_cell,
        "downloaded": bool(args.download),
        "n_entries": len(entries),
        "entries": [{k: e.get(k) for k in MANIFEST_ENTRY_FIELDS + DL_FIELDS} for e in entries],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {manifest_path} (entries={len(entries)}"
          + (f", DL ok={len(entries) - n_error} error={n_error}" if args.download else ", DL 未実行")
          + ")")
    return 1 if n_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
