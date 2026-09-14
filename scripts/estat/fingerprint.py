"""Compute workbook structure fingerprints and table-shape labels. Depends on openpyxl and writes the requested JSON report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import openpyxl

from scripts import paths





MAX_SHEETS = 40





MAX_FULL_LOAD_BYTES = 40 * 1024 * 1024




BLANK_ROW_GAP = 2


MIN_TABLE_ROWS = 3
MIN_TABLE_COLS = 2


DATA_ROW_NUMERIC_RATIO = 0.6


TITLE_ROW_MAX_CELLS = 1


PAPER_FORM_MERGED_RATIO = 0.15
PAPER_FORM_NUMERIC_MAX = 0.35


CROSSTAB_STUB_RATIO = 0.7
CROSSTAB_BODY_NUMERIC_RATIO = 0.6

SHAPES = ("paper_form", "multi_table", "crosstab", "multi_header", "flat")

SPOT_CHECK_N = 60





def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _is_numeric(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if not isinstance(v, str):
        return False
    s = v.strip().replace(",", "").replace("△", "-").replace("▲", "-").rstrip("%")
    if not s or s in {"-", "―", "…", "・"}:
        return False
    try:
        float(s)
    except ValueError:
        return False
    return True


def _row_profile(row: tuple) -> dict[str, Any]:
    nonempty = [i for i, v in enumerate(row) if not _is_empty(v)]
    body = [i for i in nonempty if i > 0]
    n_numeric = sum(1 for i in body if _is_numeric(row[i]))
    return {
        "n_nonempty": len(nonempty),
        "first_col": nonempty[0] if nonempty else None,
        "last_col": nonempty[-1] if nonempty else None,
        "numeric_ratio": (n_numeric / len(body)) if body else 0.0,
        "stub_is_label": bool(nonempty) and nonempty[0] == 0 and not _is_numeric(row[0]),
    }


def _is_data_row(prof: dict[str, Any]) -> bool:
    return prof["n_nonempty"] >= 2 and prof["numeric_ratio"] >= DATA_ROW_NUMERIC_RATIO





def sheet_features(rows: list[tuple], merged_cell_count: int) -> dict[str, Any]:
    profiles = [_row_profile(r) for r in rows]
    nonempty_idx = [i for i, p in enumerate(profiles) if p["n_nonempty"] > 0]
    n_nonempty_cells = sum(p["n_nonempty"] for p in profiles)
    if not nonempty_idx:
        return {
            "n_rows": len(rows), "n_cols": 0, "n_nonempty_cells": 0, "n_blocks": 0,
            "header_depth": 0, "merged_ratio": 0.0, "density": 0.0,
            "body_numeric_ratio": 0.0, "stub_ratio": 0.0, "corner_blank": False,
            "has_data_row": False, "col_signature": "",
        }

    n_cols = max((p["last_col"] or 0) for p in profiles) + 1
    used_rows = nonempty_idx[-1] - nonempty_idx[0] + 1


    blocks: list[list[int]] = []
    run: list[int] = []
    gap = 0
    for i in range(nonempty_idx[0], nonempty_idx[-1] + 1):
        if profiles[i]["n_nonempty"] > 0:
            if gap >= BLANK_ROW_GAP and run:
                blocks.append(run)
                run = []
            gap = 0
            run.append(i)
        else:
            gap += 1
    if run:
        blocks.append(run)
    n_blocks = sum(
        1 for b in blocks
        if len(b) >= MIN_TABLE_ROWS
        and (max(profiles[i]["last_col"] or 0 for i in b) - min(profiles[i]["first_col"] or 0 for i in b) + 1)
        >= MIN_TABLE_COLS
    )


    start = nonempty_idx[0]
    while start <= nonempty_idx[-1] and profiles[start]["n_nonempty"] <= TITLE_ROW_MAX_CELLS:
        start += 1
    header_depth = 0
    first_data = None
    for i in range(start, nonempty_idx[-1] + 1):
        if profiles[i]["n_nonempty"] == 0:
            continue
        if _is_data_row(profiles[i]):
            first_data = i
            break
        header_depth += 1
    if first_data is None:
        header_depth = min(header_depth, used_rows)

    data_profiles = [profiles[i] for i in range(first_data, nonempty_idx[-1] + 1)] if first_data is not None else []
    data_profiles = [p for p in data_profiles if p["n_nonempty"] > 0]
    body_numeric = (
        sum(p["numeric_ratio"] for p in data_profiles) / len(data_profiles) if data_profiles else 0.0
    )
    stub_ratio = (
        sum(1 for p in data_profiles if p["stub_is_label"]) / len(data_profiles) if data_profiles else 0.0
    )
    corner_blank = bool(first_data is not None and start < first_data and _is_empty(rows[start][0]))


    col_signature = ""
    if first_data is not None:
        r = rows[first_data]
        col_signature = "".join(
            "-" if _is_empty(v) else ("n" if _is_numeric(v) else "s") for v in r[:n_cols]
        )

    area = used_rows * max(n_cols, 1)
    return {
        "n_rows": used_rows,
        "n_cols": n_cols,
        "n_nonempty_cells": n_nonempty_cells,
        "n_blocks": n_blocks,
        "header_depth": header_depth,
        "merged_ratio": (merged_cell_count / n_nonempty_cells) if n_nonempty_cells else 0.0,
        "density": (n_nonempty_cells / area) if area else 0.0,
        "body_numeric_ratio": round(body_numeric, 4),
        "stub_ratio": round(stub_ratio, 4),
        "corner_blank": corner_blank,


        "has_data_row": first_data is not None,
        "col_signature": col_signature[:120],
    }





def file_features(path: Path, *, max_sheets: int = MAX_SHEETS) -> dict[str, Any]:
    read_only = path.stat().st_size > MAX_FULL_LOAD_BYTES
    wb = openpyxl.load_workbook(path, read_only=read_only, data_only=False)
    try:
        sheets = wb.worksheets
        examined = sheets[:max_sheets]
        feats = []
        for ws in examined:
            rows = list(ws.iter_rows(values_only=True))

            n_merged = 0 if read_only else len(ws.merged_cells.ranges)
            feats.append(sheet_features(rows, n_merged))
        n_sheets = len(sheets)
    finally:
        wb.close()

    if not feats:
        return {"n_sheets": n_sheets, "n_sheets_examined": 0, "error": "シートなし"}

    dom = max(feats, key=lambda f: f["n_nonempty_cells"])
    return {
        "n_sheets": n_sheets,
        "n_sheets_examined": len(feats),
        "n_sheets_truncated": max(0, n_sheets - len(feats)),
        "merged_unavailable": read_only,
        "max_blocks_in_sheet": max(f["n_blocks"] for f in feats),
        "total_nonempty_cells": sum(f["n_nonempty_cells"] for f in feats),
        **{k: dom[k] for k in (
            "n_rows", "n_cols", "n_blocks", "header_depth", "body_numeric_ratio",
            "stub_ratio", "corner_blank", "has_data_row", "col_signature",
        )},
        "merged_ratio": round(dom["merged_ratio"], 4),
        "density": round(dom["density"], 4),
    }


def assign_shape(f: dict[str, Any]) -> tuple[str, str]:
    if f.get("error"):
        return ("flat", f"特徴抽出不可: {f['error']}")
    if not f.get("has_data_row", True):


        return ("paper_form", "数値データ行を検出できない(様式/注記シートの可能性)")
    if f["merged_ratio"] >= PAPER_FORM_MERGED_RATIO and f["body_numeric_ratio"] < PAPER_FORM_NUMERIC_MAX:
        return ("paper_form", f"結合セル率 {f['merged_ratio']:.2f} かつ本体数値率 {f['body_numeric_ratio']:.2f}")
    if f["max_blocks_in_sheet"] >= 2:
        return ("multi_table", f"1 シート内に表ブロック {f['max_blocks_in_sheet']} 個")
    if f["n_sheets"] >= 2:
        return ("multi_table", f"表が {f['n_sheets']} シートに分割")
    if (
        f["header_depth"] >= 1
        and f["stub_ratio"] >= CROSSTAB_STUB_RATIO
        and f["corner_blank"]
        and f["body_numeric_ratio"] >= CROSSTAB_BODY_NUMERIC_RATIO
    ):
        return ("crosstab", f"stub 率 {f['stub_ratio']:.2f}・左上空・本体数値率 {f['body_numeric_ratio']:.2f}")
    if f["header_depth"] >= 2:
        return ("multi_header", f"ヘッダ帯 {f['header_depth']} 行")
    return ("flat", "1 行ヘッダー + データ行")


def structural_key(f: dict[str, Any]) -> str:
    parts = (
        f.get("n_sheets", 0), f.get("n_cols", 0), f.get("header_depth", 0),
        f.get("max_blocks_in_sheet", 0), round(f.get("merged_ratio", 0.0), 2),
        f.get("col_signature", ""),
    )
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]





def spot_check_queue(rows: list[dict[str, Any]], *, n: int = SPOT_CHECK_N) -> list[str]:
    by_shape: dict[str, list[str]] = {}
    for r in sorted(rows, key=lambda r: r["scoring_name"]):
        by_shape.setdefault(r["table_shape"], []).append(r["scoring_name"])
    picked: list[str] = []
    cursors = {s: 0 for s in by_shape}
    while len(picked) < n:
        progressed = False
        for shape in sorted(by_shape):
            if len(picked) >= n:
                break
            i = cursors[shape]
            if i < len(by_shape[shape]):
                picked.append(by_shape[shape][i])
                cursors[shape] = i + 1
                progressed = True
        if not progressed:
            break
    return picked





def analyze_dir(xlsx_dir: Path, *, max_sheets: int = MAX_SHEETS, quiet: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    targets = sorted(p for p in xlsx_dir.iterdir() if p.suffix.lower() == ".xlsx")
    for i, path in enumerate(targets):
        try:
            f = file_features(path, max_sheets=max_sheets)
        except Exception as exc:  # noqa: BLE001
            f = {"error": f"{type(exc).__name__}: {exc}", "n_sheets": 0, "n_sheets_examined": 0}
        shape, reason = assign_shape(f)
        out.append({
            "scoring_name": path.name,
            "table_shape": shape,
            "shape_reason": reason,
            "structural_key": structural_key(f),
            "features": f,
        })
        if not quiet and (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{len(targets)}] ...", flush=True)
    return out


def _survey_code(scoring_name: str) -> str:
    return scoring_name.split("_", 1)[0]


def build_report(rows: list[dict[str, Any]], *, spot_n: int = SPOT_CHECK_N) -> dict[str, Any]:
    keys = Counter(r["structural_key"] for r in rows)
    dup_groups = {k: v for k, v in keys.items() if v > 1}
    n_in_dup = sum(dup_groups.values())



    members: dict[str, list[str]] = {}
    for r in rows:
        members.setdefault(r["structural_key"], []).append(r["scoring_name"])
    same_survey = {k: v for k, v in members.items()
                   if len(v) > 1 and len({_survey_code(n) for n in v}) == 1}
    cross_survey = {k: v for k, v in members.items()
                    if len(v) > 1 and len({_survey_code(n) for n in v}) > 1}
    return {
        "adr": "docs/decisions/2026-07-06-e-stat-sampling-scale.md#3-テンプレ-dedup-キーの設計本設計の技術的急所",
        "n_files": len(rows),
        "params": {
            "max_sheets": MAX_SHEETS, "blank_row_gap": BLANK_ROW_GAP,
            "paper_form_merged_ratio": PAPER_FORM_MERGED_RATIO,
            "paper_form_numeric_max": PAPER_FORM_NUMERIC_MAX,
            "crosstab_stub_ratio": CROSSTAB_STUB_RATIO,
        },
        "shape_counts": {s: sum(1 for r in rows if r["table_shape"] == s) for s in SHAPES},
        "n_errors": sum(1 for r in rows if r["features"].get("error")),
        "n_merged_unavailable": sum(1 for r in rows if r["features"].get("merged_unavailable")),
        "structural_dedup": {
            "n_distinct_keys": len(keys),
            "n_duplicate_groups": len(dup_groups),
            "n_files_in_duplicate_groups": n_in_dup,
            "residual_duplicate_rate": round(n_in_dup / len(rows), 4) if rows else None,
            "same_survey": {
                "n_groups": len(same_survey),
                "n_files": sum(len(v) for v in same_survey.values()),
                "largest_group": max((len(v) for v in same_survey.values()), default=0),
                "note": "メタ相 dedup の取りこぼしの候補(同一調査内で構造が一致)",
            },
            "cross_survey": {
                "n_groups": len(cross_survey),
                "n_files": sum(len(v) for v in cross_survey.values()),
                "note": "別調査どうしの一致。構造キーが粗いことによる偽陽性の疑いが強い",
            },
            "note": "**重複の候補**であって確定ではない(構造キーは粗い)。限界として開示する(ADR §3.2-a)",
        },
        "spot_check_queue": spot_check_queue(rows, n=spot_n),
        "files": rows,
    }


def apply_to_manifest(manifest_path: Path, rows: list[dict[str, Any]]) -> int:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {r["scoring_name"]: r for r in rows}
    n = 0
    for e in data["entries"]:
        fn = e.get("file_name")
        if not fn:
            continue
        key = fn if fn.lower().endswith(".xlsx") else Path(fn).stem + ".xlsx"
        row = by_name.get(key)
        if row is None:
            continue
        e["table_shape"] = row["table_shape"]
        e["structural_key"] = row["structural_key"]
        n += 1
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--xlsx-dir", type=Path, default=paths.ESTAT_DIR / "tier1" / "xlsx")
    parser.add_argument("--manifest", type=Path, default=paths.ESTAT_DIR / "tier1" / "manifest.json",
                        help="table_shape を書き戻す manifest(--no-apply で無効)")
    parser.add_argument("--out-json", type=Path, default=paths.ROOT / "docs" / "experiments" / "tier1-fingerprint.json")
    parser.add_argument("--max-sheets", type=int, default=MAX_SHEETS)
    parser.add_argument("--spot-n", type=int, default=SPOT_CHECK_N)
    parser.add_argument("--no-apply", action="store_true", help="manifest に書き戻さない")
    args = parser.parse_args(argv)

    if not args.xlsx_dir.exists():
        print(f"採点用ディレクトリが無い: {args.xlsx_dir}")
        return 1
    rows = analyze_dir(args.xlsx_dir, max_sheets=args.max_sheets)
    report = build_report(rows, spot_n=args.spot_n)

    print(f"\n=== table_shape 半自動付与 ({report['n_files']} 件・エラー {report['n_errors']}) ===")
    for shape in SHAPES:
        n = report["shape_counts"][shape]
        print(f"  {shape:<13} {n:>4} ({100 * n / max(report['n_files'], 1):>5.1f}%)")
    sd = report["structural_dedup"]
    print(f"  構造相 重複候補: {sd['n_files_in_duplicate_groups']} 件 / "
          f"{sd['n_duplicate_groups']} グループ ({100 * (sd['residual_duplicate_rate'] or 0):.1f}%)")
    print(f"    うち同一調査内: {sd['same_survey']['n_files']} 件 / {sd['same_survey']['n_groups']} グループ"
          f"(最大 {sd['same_survey']['largest_group']} 件) ← メタ相の取りこぼし候補")
    print(f"    調査またぎ    : {sd['cross_survey']['n_files']} 件 / {sd['cross_survey']['n_groups']} グループ"
          f" ← 偽陽性の疑い")
    print(f"  spot-check キュー: {len(report['spot_check_queue'])} 件")

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ {args.out_json}")
    if not args.no_apply and args.manifest.exists():
        print(f"→ {args.manifest} に table_shape を書き戻し: {apply_to_manifest(args.manifest, rows)} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
