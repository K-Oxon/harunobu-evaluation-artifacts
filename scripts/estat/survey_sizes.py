"""Probe e-Stat catalogue sizes by survey. Depends on ESTAT_FILE_SEARCH_SCRIPT and ESTAT_APP_ID and writes run data under data/estat/enumeration/."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from scripts import paths
from scripts.estat import frame as frame_mod
from scripts.estat import plugin
from scripts.estat.fetch_catalog import (
    DEFAULT_DATA_TYPE,
    _ensure_list,
    _list_inf,
    _pages,
)


def parse_probe(raw: dict[str, Any]) -> dict[str, Any]:
    pages = _pages(raw)
    first = _list_inf(pages[0]) if pages else {}
    number = first.get("NUMBER")
    items = _ensure_list(first.get("DATA_CATALOG_INF"))
    org = {}
    if items and isinstance(items[0], dict):
        org = items[0].get("DATASET", {}).get("ORGANIZATION", {})
        org = org if isinstance(org, dict) else {}
    return {
        "number": int(number) if str(number).isdigit() else 0,
        "org_code": org.get("@code") or "",
        "org_name": org.get("$") or "",
    }


def probe_one(
    code: str,
    out_dir: Path,
    search_script: Path,
    frame_row: frame_mod.FrameRow | None,
    args: argparse.Namespace,
    env: dict[str, str],
) -> dict[str, Any]:
    raw_path = out_dir / f"{code}.raw.json"
    cmd = [
        "uv", "run", "--quiet", "--no-project", "--script", str(search_script),
        "--stats-code", code,
        "--data-type", args.data_type,
        "--limit", "1",
        "--max-pages", "1",
        "--timeout", str(args.timeout),
        "--raw-output", str(raw_path),
        "--candidates-output", str(out_dir / f"{code}.candidates.csv"),
        "--format", "csv",
    ]
    meta: dict[str, Any] = {
        "gov_stats_code": code,
        "gov_stats_name": frame_row.gov_stats_name if frame_row else None,
        "stats_type": frame_row.stats_type if frame_row else None,
        "cycle": frame_row.cycle if frame_row else None,
        "has_db": frame_row.has_db if frame_row else None,
        "frame_organization": frame_row.organization if frame_row else None,
        "fetched_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    last_error: str | None = None
    for attempt in range(1 + args.retries):
        if attempt:
            time.sleep(args.sleep * (2**attempt))
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=args.timeout + 60)
        except subprocess.TimeoutExpired:
            last_error = "subprocess timeout"
            continue
        if proc.returncode != 0:
            last_error = (proc.stderr or proc.stdout).strip()[-300:]
            continue
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            last_error = f"raw 読み取り失敗: {exc}"
            continue
        meta |= parse_probe(raw)
        meta["status"] = "ok"
        break
    else:
        meta["status"] = "error"
        meta["error"] = last_error
    (out_dir / f"{code}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


CSV_FIELDS = [
    "gov_stats_code", "gov_stats_name", "stats_type", "cycle", "has_db",
    "frame_organization", "org_code", "org_name", "number", "status", "fetched_at",
]


def write_csv(out_dir: Path, metas: list[dict[str, Any]]) -> Path:
    csv_path = out_dir / "survey-sizes.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for m in sorted(metas, key=lambda m: m["gov_stats_code"]):
            writer.writerow(m)
    return csv_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--stats-code", help="カンマ区切りの政府統計コード(既定: フレーム全 739 調査)")
    parser.add_argument("--frame", type=Path, default=None, help="フレーム CSV(既定: 凍結スナップショット)")
    parser.add_argument("--run-id", default=None, help="probe ディレクトリ名(既定: 今日の日付-sizes)")
    parser.add_argument("--data-type", default=DEFAULT_DATA_TYPE)
    parser.add_argument("--sleep", type=float, default=0.5, help="調査間 sleep 秒")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--force", action="store_true", help="取得済みでも再取得する")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    frame = frame_mod.load_frame(args.frame)
    if args.stats_code:
        codes = [c.strip() for c in args.stats_code.split(",") if c.strip()]
    else:
        codes = frame_mod.population_codes(frame)

    run_id = args.run_id or f"{dt.date.today().isoformat()}-sizes"
    out_dir = paths.ESTAT_ENUM_DIR / "probes" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    search_script = plugin.find_search_script()
    env = dict(os.environ)
    if "ESTAT_APP_ID" not in env:
        raise SystemExit("ESTAT_APP_ID must be set in the process environment")

    metas: list[dict[str, Any]] = []
    for i, code in enumerate(codes):
        meta_path = out_dir / f"{code}.meta.json"
        if not args.force and meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("status") == "ok":
                metas.append(meta)
                continue
        if i and args.sleep:
            time.sleep(args.sleep)
        meta = probe_one(code, out_dir, search_script, frame.get(code), args, env)
        metas.append(meta)
        if (i + 1) % 25 == 0 or meta["status"] != "ok":
            print(f"[{i + 1}/{len(codes)}] {code} {meta.get('gov_stats_name', '?')}: "
                  f"{meta['status']} NUMBER={meta.get('number', '-')}", flush=True)


    all_metas = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("*.meta.json"))
    ]
    csv_path = write_csv(out_dir, all_metas)
    n_error = sum(1 for m in all_metas if m["status"] == "error")
    print(f"csv={csv_path} ({len(all_metas)} 調査)")
    print(f"ok={len(all_metas) - n_error} error={n_error} total_datasets={sum(m.get('number', 0) for m in all_metas if m['status'] == 'ok')}")
    return 1 if n_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
