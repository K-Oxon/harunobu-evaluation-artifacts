"""Enumerate e-Stat catalogue records by statistics code. Depends on ESTAT_FILE_SEARCH_SCRIPT and ESTAT_APP_ID and writes run data under data/estat/enumeration/."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from scripts import paths
from scripts.estat import frame as frame_mod
from scripts.estat import plugin

DEFAULT_DATA_TYPE = "XLS,XLS_REP"






def _pages(raw: dict[str, Any]) -> list[dict[str, Any]]:
    if "pages" in raw and isinstance(raw["pages"], list):
        return [p for p in raw["pages"] if isinstance(p, dict)]
    return [raw]


def _list_inf(page: dict[str, Any]) -> dict[str, Any]:
    value = page.get("GET_DATA_CATALOG", {})
    value = value.get("DATA_CATALOG_LIST_INF", {}) if isinstance(value, dict) else {}
    return value if isinstance(value, dict) else {}


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def summarize_raw(raw: dict[str, Any]) -> dict[str, Any]:
    pages = _pages(raw)
    first = _list_inf(pages[0]) if pages else {}
    number = first.get("NUMBER")
    n_datasets = sum(len(_ensure_list(_list_inf(p).get("DATA_CATALOG_INF"))) for p in pages)
    result = pages[0].get("GET_DATA_CATALOG", {}).get("RESULT", {}) if pages else {}
    return {
        "number": int(number) if str(number).isdigit() else number,
        "n_pages": len(pages),
        "n_datasets": n_datasets,
        "api_result_date": result.get("DATE") if isinstance(result, dict) else None,
    }


def count_candidate_rows(candidates_csv: Path) -> int:

    with open(candidates_csv, encoding="utf-8", newline="") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)





def build_command(
    search_script: Path, code: str, out_dir: Path, args: argparse.Namespace
) -> list[str]:
    return [
        "uv",
        "run",
        "--quiet",
        "--no-project",
        "--script",
        str(search_script),
        "--stats-code",
        code,
        "--data-type",
        args.data_type,
        "--all",
        "--limit",
        str(args.limit),
        "--sleep-seconds",
        str(args.page_sleep),
        "--timeout",
        str(args.timeout),
        "--raw-output",
        str(out_dir / "raw.json"),
        "--candidates-output",
        str(out_dir / "candidates.csv"),
        "--format",
        "csv",
    ]


def fetch_one(
    code: str,
    run_dir: Path,
    search_script: Path,
    frame_row: frame_mod.FrameRow | None,
    args: argparse.Namespace,
    env: dict[str, str],
) -> dict[str, Any]:
    out_dir = run_dir / code
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(search_script, code, out_dir, args)
    meta: dict[str, Any] = {
        "gov_stats_code": code,
        "gov_stats_name": frame_row.gov_stats_name if frame_row else None,
        "stats_type": frame_row.stats_type if frame_row else None,
        "query": {
            "endpoint": "getDataCatalog",
            "statsCode": code,
            "dataType": args.data_type,
            "limit": args.limit,
            "lang": "J",
            "paging": "--all (RESULT_INF.NEXT_KEY を最後まで辿る)",
        },
        "search_script": str(search_script),
        "command": cmd,
        "fetched_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
    }

    last_error: str | None = None
    for attempt in range(1 + args.retries):
        if attempt:
            time.sleep(args.sleep * (2**attempt))
        try:
            proc = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=args.survey_timeout
            )
        except subprocess.TimeoutExpired:
            last_error = f"survey timeout ({args.survey_timeout}s)"
            continue
        if proc.returncode != 0:
            last_error = (proc.stderr or proc.stdout).strip()[-500:]
            continue
        try:
            raw = json.loads((out_dir / "raw.json").read_text(encoding="utf-8"))
            meta |= summarize_raw(raw)
            meta["n_resources"] = count_candidate_rows(out_dir / "candidates.csv")
        except (OSError, ValueError) as exc:


            last_error = f"出力の読み取り失敗: {exc}"
            continue
        meta["status"] = "ok"
        if meta["number"] not in (None, meta["n_datasets"]):

            meta["status"] = "incomplete"
            meta["warning"] = f"NUMBER={meta['number']} != n_datasets={meta['n_datasets']}"
        break
    else:
        meta["status"] = "error"
        meta["error"] = last_error
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta





def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--stats-code", help="カンマ区切りの政府統計コード(8桁)")
    target.add_argument(
        "--all-frame", action="store_true", help="母集団フレーム(has_file=〇)の全調査を回す"
    )
    parser.add_argument("--frame", type=Path, default=None, help="フレーム CSV(既定: 凍結スナップショット)")
    parser.add_argument("--enum-dir", type=Path, default=None, help="列挙出力ルート(既定: dataset/e-stat/enumeration)")
    parser.add_argument("--run-id", default=None, help="run ディレクトリ名(既定: 今日の日付)")
    parser.add_argument("--data-type", default=DEFAULT_DATA_TYPE, help="dataType(FORMAT は hint。verify は dedup 側)")
    parser.add_argument("--limit", type=int, default=100, help="1ページのデータセット数")
    parser.add_argument("--sleep", type=float, default=1.0, help="調査間 sleep 秒")
    parser.add_argument("--page-sleep", type=float, default=0.5, help="ページ間 sleep 秒(search.py に渡す)")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP リクエスト timeout 秒")
    parser.add_argument("--survey-timeout", type=float, default=1800.0, help="1調査あたりの subprocess timeout 秒")
    parser.add_argument("--retries", type=int, default=2, help="調査単位のリトライ回数")
    parser.add_argument("--force", action="store_true", help="取得済み(meta.json あり)でも再取得する")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    frame = frame_mod.load_frame(args.frame)
    if args.all_frame:
        codes = frame_mod.population_codes(frame)
    else:
        codes = [c.strip() for c in args.stats_code.split(",") if c.strip()]
        unknown = [c for c in codes if c not in frame]
        if unknown:
            print(f"warning: フレームに無いコード(続行はする): {unknown}", file=sys.stderr)

    enum_dir = args.enum_dir or paths.ESTAT_ENUM_DIR
    run_id = args.run_id or dt.date.today().isoformat()
    run_dir = enum_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    search_script = plugin.find_search_script()
    env = dict(os.environ)
    if "ESTAT_APP_ID" not in env:
        raise SystemExit("ESTAT_APP_ID must be set in the process environment")

    results: list[dict[str, Any]] = []
    for i, code in enumerate(codes):
        out_dir = run_dir / code
        if not args.force and (out_dir / "meta.json").is_file():
            meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
            if meta.get("status") != "error":
                meta["cached"] = True
                results.append(meta)
                print(f"[{i + 1}/{len(codes)}] {code} skip(取得済み)")
                continue
            print(f"[{i + 1}/{len(codes)}] {code} 前回 error → 再取得")
        if i and args.sleep:
            time.sleep(args.sleep)
        row = frame.get(code)
        meta = fetch_one(code, run_dir, search_script, row, args, env)
        results.append(meta)
        name = row.gov_stats_name if row else "?"
        print(
            f"[{i + 1}/{len(codes)}] {code} {name}: {meta['status']}"
            f" datasets={meta.get('n_datasets', '-')} files={meta.get('n_resources', '-')}"
        )

    n_error = sum(1 for m in results if m.get("status") == "error")
    summary = {
        "run_id": run_id,
        "data_type": args.data_type,
        "n_surveys": len(codes),
        "n_ok": sum(1 for m in results if m.get("status") == "ok"),
        "n_incomplete": sum(1 for m in results if m.get("status") == "incomplete"),
        "n_error": n_error,
        "surveys": [
            {
                k: m.get(k)
                for k in (
                    "gov_stats_code",
                    "gov_stats_name",
                    "stats_type",
                    "status",
                    "cached",
                    "number",
                    "n_datasets",
                    "n_resources",
                    "fetched_at",
                )
            }
            for m in results
        ],
    }
    (run_dir / "fetch-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"run_dir={run_dir}")
    print(f"ok={summary['n_ok']} incomplete={summary['n_incomplete']} error={n_error}")
    return 1 if n_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
