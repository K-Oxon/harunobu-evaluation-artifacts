"""Select and download a deterministic e-Stat starter set from the template frame. Writes selection, manifest, and workbook files to the requested paths."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from scripts import paths
from scripts.estat import frame as frame_mod



SURVEY_CODES = [

    "00200521",
    "00200531",
    "00200561",
    "00450011",
    "00450071",
    "00400001",
    "00600130",

    "00200356",
    "00450171",
    "00450099",
    "00400202",
    "00601020",
    "00100405",
    "00450312",

    "00250011",
    "00250002",
    "00130001",
    "00200523",
    "00130002",

    "00200573",
    "00500300",
    "00550425",
    "00600920",
]



OVERRIDES: dict[str, tuple[str | None, str | None]] = {
    "00400001": (None, "8c676f9cf321edca"),
    "00100405": (None, "7de0334757d02db0"),
    "00450011": ("cc2152b302538bac", "b9ba2d3d507387d2"),
    "00550425": ("d09fe7792c172a0d", "1c4f6e2f94b7a0f0"),
}

_EXCLUDE_RE = re.compile(r"正誤|訂正|目次|利用上|付録|凡例|調査の概要|お知らせ|取扱説明書")
_FLAGSHIP_RE = re.compile(r"第1表|総括|概況|全国結果|結果の概要|主要|時系列")
_STAT_INF_ID_RE = re.compile(r"statInfId=(\d+)")
_TABLE_NO_NUM_RE = re.compile(r"\d+")

RECENT_WINDOW = 1000


def _survey_date_int(value: str) -> int:
    digits = [int(t) for t in re.findall(r"\d{4,6}", value or "")]
    return max((d * 100 if d < 10000 else d) for d in digits) if digits else -1


def _table_no_num(row: dict[str, str]) -> int:
    m = _TABLE_NO_NUM_RE.search(row["table_no"] or row["table_name"] or "")
    return int(m.group()) if m else 10**9


def _is_flagship(row: dict[str, str]) -> bool:
    return bool(_FLAGSHIP_RE.search(row["dataset_title_stem"] + " " + row["table_name"]))


def select_two(templates: list[dict[str, str]], code: str) -> list[dict[str, Any]]:
    pool = [
        r
        for r in templates
        if r["representative_url"]
        and not _EXCLUDE_RE.search(r["dataset_title_stem"] + " " + r["table_name"])
    ]
    if not pool:
        raise SystemExit(f"{code}: 候補テンプレなし")
    max_sd = max(_survey_date_int(r["survey_date_latest"]) for r in pool)
    recent = [r for r in pool if _survey_date_int(r["survey_date_latest"]) >= max_sd - RECENT_WINDOW]
    pool = recent if len(recent) >= 2 else pool

    stem_count = Counter(r["dataset_title_stem"] for r in pool)

    def order(r: dict[str, str]) -> tuple:
        return (
            not _is_flagship(r),
            -stem_count[r["dataset_title_stem"]],
            _table_no_num(r),
            r["dataset_title_stem"],
            r["table_name"],
        )

    ranked = sorted(pool, key=order)
    ov_flag, ov_div = OVERRIDES.get(code, (None, None))
    flagship = next((r for r in ranked if r["template_id"] == ov_flag), None) if ov_flag else None
    flagship = flagship or ranked[0]
    other_stems = [r for r in ranked if r["dataset_title_stem"] != flagship["dataset_title_stem"]]
    diversity = next((r for r in ranked if r["template_id"] == ov_div), None) if ov_div else None
    diversity = diversity or (other_stems[0] if other_stems else next(
        (r for r in ranked if r["template_id"] != flagship["template_id"]), flagship
    ))
    flagship = dict(flagship, role="flagship")
    diversity = dict(diversity, role="diversity")
    return [flagship, diversity]


def load_selection(templates_csv: Path) -> list[dict[str, Any]]:
    by_survey: dict[str, list[dict[str, str]]] = {c: [] for c in SURVEY_CODES}
    with open(templates_csv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["gov_stats_code"] in by_survey:
                by_survey[r["gov_stats_code"]].append(r)
    selection: list[dict[str, Any]] = []
    for code in SURVEY_CODES:
        if not by_survey[code]:
            raise SystemExit(f"{code}: templates-v2.csv に行なし")
        selection.extend(select_two(by_survey[code], code))
    return selection


def _detect_ext(head: bytes) -> str:
    if head.startswith(b"PK"):
        return "xlsx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "xls"
    return "bin"


def download(entry: dict[str, Any], files_dir: Path, *, timeout: float, retries: int) -> dict[str, Any]:
    req = urllib.request.Request(
        entry["representative_url"],
        headers={"User-Agent": "harunobu-evaluation/starter-set (research; contact repo owner)"},
    )
    last_error: str | None = None
    for attempt in range(1 + retries):
        if attempt:
            time.sleep(2.0 * attempt)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            break
        except OSError as exc:
            last_error = str(exc)
    else:
        return {"dl_status": "error", "dl_error": last_error}
    ext = _detect_ext(body[:8])
    name = f"{entry['gov_stats_code']}_{entry['representative_resource_id']}.{ext}"
    (files_dir / name).write_bytes(body)
    return {
        "dl_status": "ok" if ext != "bin" else "unexpected_format",
        "file_name": name,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "fetched_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


MANIFEST_ENTRY_FIELDS = [
    "gov_stats_code", "gov_stats_name", "stat_type", "gov_org", "role",
    "template_id", "dataset_title_stem", "table_no", "table_name",
    "representative_resource_id", "stat_inf_id", "representative_dataset_id",
    "representative_dataset_title", "representative_url", "survey_date_latest",
    "n_period_instances", "n_region_variants",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--templates",
        type=Path,
        default=paths.ESTAT_ENUM_DIR / "runs" / "2026-07-17-full" / "templates-v2.csv",
        help="テンプレ・フレーム CSV(scheme v2)",
    )
    parser.add_argument("--out-dir", type=Path, default=paths.ESTAT_DIR / "starter-set")
    parser.add_argument("--select-only", action="store_true", help="選定表の表示のみ(DL しない)")
    parser.add_argument("--sleep", type=float, default=1.0, help="DL 間 sleep 秒")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    frame = frame_mod.load_frame()
    selection = load_selection(args.templates)
    for e in selection:
        m = _STAT_INF_ID_RE.search(e["representative_url"])
        e["stat_inf_id"] = m.group(1) if m else ""
        e["stat_type"] = frame[e["gov_stats_code"]].stats_type

    print(f"{'調査':<16} {'種別':<5} {'role':<9} {'統計表ID':<13} stem / 表")
    for e in selection:
        print(
            f"{e['gov_stats_name'][:15]:<16} {e['stat_type'][:4]:<5} {e['role']:<9}"
            f" {e['stat_inf_id']:<13} {e['dataset_title_stem'][:40]} / [{e['table_no']}] {e['table_name'][:40]}"
        )
    if args.select_only:
        return 0

    files_dir = args.out_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    n_error = 0
    for i, e in enumerate(selection):
        if i and args.sleep:
            time.sleep(args.sleep)
        e.update(download(e, files_dir, timeout=args.timeout, retries=args.retries))
        if e["dl_status"] != "ok":
            n_error += 1
        print(f"  DL[{i + 1}/{len(selection)}] {e['gov_stats_name']}: {e['dl_status']}"
              f" {e.get('file_name', '')} ({e.get('bytes', 0):,}B)", flush=True)

    manifest = {
        "issue": "docs/issues/2026-07-17-starter-set-annotation.md",
        "source_templates": str(args.templates),
        "dedup_scheme_version": 2,
        "g1_mini_approved": "2026-07-17 オーナー承認(44→46表構成)",
        "n_entries": len(selection),
        "entries": [
            {k: e.get(k) for k in MANIFEST_ENTRY_FIELDS + ["dl_status", "file_name", "bytes", "sha256", "fetched_at", "dl_error"]}
            for e in selection
        ],
    }
    manifest_path = args.out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"manifest={manifest_path}")
    print(f"files={files_dir} ok={len(selection) - n_error} error={n_error}")
    return 1 if n_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
