"""Measure rule-score sensitivity to injected and observed layout changes. Depends on harunobu and DECO inputs and writes JSON under results/layout/."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from scripts import cache, paths, sampling
from scripts.rule_scoring import _aggregate_rule_checks, configure_ai

SCHEMA_VERSION = "0.1.0"

EXP_DIR = paths.RESULTS_DIR / "layout"
INJECTION_JSON = EXP_DIR / "score-sensitivity-injection-replay.json"
REALDATA_JSON = EXP_DIR / "score-sensitivity-realdata-replay.json"


Bbox = tuple[int, int, int, int]

_LEVELS = ("L1", "L2", "L3")





def variant_specs() -> dict[str, dict]:
    v: dict[str, dict] = {}
    for edge in ("top", "bottom", "left", "right"):
        for d in (-2, -1, 1, 2):
            v[f"shift_{edge}{d:+d}"] = {"kind": "shift", "edge": edge, "delta": d}
    for d in (1, 2):
        v[f"expand_all{d}"] = {"kind": "expand", "delta": d}
        v[f"shrink_all{d}"] = {"kind": "expand", "delta": -d}
    v["split_blank"] = {"kind": "split_blank"}
    v["split_2"] = {"kind": "split_equal", "k": 2}
    v["split_3"] = {"kind": "split_equal", "k": 3}
    v["header+1"] = {"kind": "header", "delta": 1}
    v["header-1"] = {"kind": "header", "delta": -1}
    v["detector"] = {"kind": "detector"}
    return v





def _clamp_bbox(bbox: Bbox, max_row: int, max_col: int) -> Bbox | None:
    r0, c0, r1, c1 = bbox
    r0, c0 = max(r0, 1), max(c0, 1)
    r1, c1 = min(r1, max_row), min(c1, max_col)
    if r0 > r1 or c0 > c1:
        return None
    return (r0, c0, r1, c1)


def shift_bbox(bbox: Bbox, edge: str, delta: int, max_row: int, max_col: int) -> Bbox | None:
    r0, c0, r1, c1 = bbox
    if edge == "top":
        r0 += delta
    elif edge == "bottom":
        r1 += delta
    elif edge == "left":
        c0 += delta
    elif edge == "right":
        c1 += delta
    else:
        raise ValueError(f"unknown edge: {edge!r}")
    if r0 > r1 or c0 > c1:
        return None
    return _clamp_bbox((r0, c0, r1, c1), max_row, max_col)


def expand_bbox(bbox: Bbox, delta: int, max_row: int, max_col: int) -> Bbox | None:
    r0, c0, r1, c1 = bbox
    r0, c0, r1, c1 = r0 - delta, c0 - delta, r1 + delta, c1 + delta
    if r0 > r1 or c0 > c1:
        return None
    return _clamp_bbox((r0, c0, r1, c1), max_row, max_col)


def _row_is_blank(sheet, row: int, c0: int, c1: int) -> bool:
    for c in range(c0, c1 + 1):
        cell = sheet.get_cell(row, c)
        if cell is not None and cell.value is not None:
            return False
    return True


def split_bbox_at_blank_rows(sheet, bbox: Bbox) -> list[Bbox]:
    r0, c0, r1, c1 = bbox
    segments: list[Bbox] = []
    seg_start: int | None = None
    for r in range(r0, r1 + 1):
        if _row_is_blank(sheet, r, c0, c1):
            if seg_start is not None:
                segments.append((seg_start, c0, r - 1, c1))
                seg_start = None
        else:
            if seg_start is None:
                seg_start = r
    if seg_start is not None:
        segments.append((seg_start, c0, r1, c1))
    return segments if segments else [bbox]


def split_bbox_equal(bbox: Bbox, k: int) -> list[Bbox]:
    r0, c0, r1, c1 = bbox
    rows = r1 - r0 + 1
    if rows < 2 * k:
        return [bbox]
    base, rem = divmod(rows, k)
    out: list[Bbox] = []
    start = r0
    for i in range(k):
        size = base + (1 if i < rem else 0)
        out.append((start, c0, start + size - 1, c1))
        start += size
    return out





def build_region(sheet, bbox: Bbox):
    from harunobu.core.layout.island import _estimate_layout
    from harunobu.core.models import CellRange, TableRegion

    r0, c0, r1, c1 = bbox
    layout = _estimate_layout(sheet, r0, r1, c0, c1)
    return TableRegion(
        range=CellRange(start_row=r0, start_col=c0, end_row=r1, end_col=c1),
        layout=layout,
        confidence=1.0,
    )


def perturb_header_region(sheet, region, delta: int):
    from harunobu.core.layout.island import (
        _estimate_stub_cols,
        _generate_column_headers,
        _infer_column_schemas,
    )
    from harunobu.core.models import TableLayout, TableRegion

    lay = region.layout
    r = region.range
    if delta == 1:
        new_body_start = lay.body_start_row + 1
        if new_body_start > lay.body_end_row:
            return None
        new_headers = sorted(set(lay.header_rows) | {lay.body_start_row})
    elif delta == -1:
        if not lay.header_rows:
            return None
        removed = max(lay.header_rows)
        new_headers = sorted(set(lay.header_rows) - {removed})
        new_body_start = removed
    else:
        raise ValueError(f"unsupported header delta: {delta}")

    column_headers = _generate_column_headers(sheet, new_headers, r.start_col, r.end_col)
    columns = _infer_column_schemas(sheet, new_body_start, lay.body_end_row, r.start_col, r.end_col, column_headers)
    stub_cols = _estimate_stub_cols(sheet, new_body_start, lay.body_end_row, r.start_col, r.end_col, columns)
    return TableRegion(
        range=r,
        layout=TableLayout(
            header_rows=new_headers,
            body_start_row=new_body_start,
            body_end_row=lay.body_end_row,
            column_headers=column_headers,
            columns=columns,
            stub_cols=stub_cols,
        ),
        confidence=1.0,
    )


def others_outside(sheet, regions) -> list:
    from harunobu.core.models import OtherCell

    spans = [(g.range.start_row, g.range.end_row, g.range.start_col, g.range.end_col) for g in regions]
    out = []
    for (r, c), cell in sorted(sheet.cells.items()):
        if cell.value is None:
            continue
        if any(sr <= r <= er and sc <= c <= ec for sr, er, sc, ec in spans):
            continue
        out.append(OtherCell(row=r, col=c, value=cell.value, region_type="outside_table"))
    return out


def score_regions(workbook, per_sheet: dict[str, tuple[list, list]], config):
    from harunobu.core.analyzer import MRChecker
    from harunobu.core.models import (
        AnalysisResult,
        FileMeta,
        SheetMeta,
        SheetProperty,
        SheetResult,
        TableContext,
        TableResult,
    )

    checker = MRChecker()
    sheet_results = []
    for sheet in workbook.sheets:
        if sheet.name not in per_sheet:
            continue
        regions, others = per_sheet[sheet.name]
        table_results = []
        for region in regions:
            context = TableContext(
                workbook=workbook,
                sheet=sheet,
                table_region=region,
                config=config,
                all_tables=regions,
                sheet_others=others,
            )
            mr_result = checker.check_all(context, config)
            table_results.append(
                TableResult(
                    range=region.range,
                    layout=region.layout,
                    confidence=region.confidence,
                    mr_result=mr_result,
                    column_headers=region.layout.column_headers,
                    columns=region.layout.columns,
                )
            )
        sheet_results.append(
            SheetResult(
                sheet_meta=SheetMeta(name=sheet.name),
                tables=table_results,
                sheet_property=SheetProperty(
                    sheet_name=sheet.name, max_row=sheet.max_row, max_col=sheet.max_col, hidden=sheet.hidden
                ),
                others=others,
            )
        )
    return AnalysisResult(
        file_meta=FileMeta(
            name=workbook.file_name,
            size=workbook.file_size,
            format=workbook.file_format,
            sheet_count=len(workbook.sheets),
        ),
        sheets=sheet_results,
    )


def condition_record(result) -> dict:
    from harunobu.core.scorer import LevelScorer

    scoring = LevelScorer().score_analysis(result)
    levels = {}
    for lv, ls in sorted(scoring.per_level.items()):
        levels[f"L{lv}"] = {
            "score": ls.score,
            "passed": ls.passed,
            "total": ls.total,
            "forced_zero": ls.forced_zero,
        }
    rules = {
        r.rule_id: ("skip" if r.skipped else ("pass" if r.passed else "fail"))
        for r in _aggregate_rule_checks(result)
    }
    n_regions = sum(len(s.tables) for s in result.sheets)
    return {"n_regions": n_regions, "levels": levels, "rules": rules}





def gt_bboxes_by_sheet(gt_doc, workbook) -> tuple[dict[str, list[Bbox]], list[str], int]:
    by_sheet: dict[str, list[Bbox]] = {}
    missing: list[str] = []
    n_adjusted = 0
    for irs in gt_doc.sheets:
        sheet = workbook.get_sheet(irs.sheet_name)
        if sheet is None:
            missing.append(irs.sheet_name)
            continue
        bboxes: list[Bbox] = []
        for t in irs.tables:
            b = t.bbox
            raw: Bbox = (b.first_row + 1, b.first_col + 1, b.last_row + 1, b.last_col + 1)
            clamped = _clamp_bbox(raw, sheet.max_row, sheet.max_col)
            if clamped is None:
                n_adjusted += 1
                continue
            if clamped != raw:
                n_adjusted += 1
            bboxes.append(clamped)
        by_sheet[irs.sheet_name] = bboxes
    return by_sheet, missing, n_adjusted


def apply_variant(sheet, bboxes: list[Bbox], spec: dict) -> tuple[list, int, int]:
    kind = spec["kind"]
    regions = []
    n_perturbed = 0
    n_dropped = 0
    if kind in ("shift", "expand"):
        for bbox in bboxes:
            if kind == "shift":
                nb = shift_bbox(bbox, spec["edge"], spec["delta"], sheet.max_row, sheet.max_col)
            else:
                nb = expand_bbox(bbox, spec["delta"], sheet.max_row, sheet.max_col)
            if nb is None:
                n_dropped += 1
                continue
            if nb != bbox:
                n_perturbed += 1
            regions.append(build_region(sheet, nb))
        return regions, n_perturbed, n_dropped
    if kind == "split_blank":
        for bbox in bboxes:
            parts = split_bbox_at_blank_rows(sheet, bbox)
            if len(parts) > 1:
                n_perturbed += 1
            regions.extend(build_region(sheet, p) for p in parts)
        return regions, n_perturbed, n_dropped
    if kind == "split_equal":
        for bbox in bboxes:
            parts = split_bbox_equal(bbox, spec["k"])
            if len(parts) > 1:
                n_perturbed += 1
            regions.extend(build_region(sheet, p) for p in parts)
        return regions, n_perturbed, n_dropped
    raise ValueError(f"unknown variant kind: {kind}")


def evaluate_file(path: Path, gt_doc, config, variants: dict[str, dict]) -> dict:
    from harunobu.core.layout.detector import LayoutDetector
    from harunobu.core.reader import read_file

    rec: dict = {"file": path.name}
    try:
        workbook = read_file(path)
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec

    by_sheet, missing, n_adjusted = gt_bboxes_by_sheet(gt_doc, workbook)
    if missing:
        rec["gt_sheets_missing"] = missing
    if n_adjusted:
        rec["gt_tables_adjusted"] = n_adjusted
    rec["gt_tables"] = sum(len(v) for v in by_sheet.values())


    base_regions = {name: [build_region(workbook.get_sheet(name), b) for b in bboxes] for name, bboxes in by_sheet.items()}
    base_per_sheet = {
        name: (regions, others_outside(workbook.get_sheet(name), regions)) for name, regions in base_regions.items()
    }
    rec["baseline"] = condition_record(score_regions(workbook, base_per_sheet, config))

    rec["variants"] = {}
    for vid, spec in variants.items():
        kind = spec["kind"]
        n_perturbed = 0
        n_dropped = 0
        per_sheet: dict[str, tuple[list, list]] = {}
        if kind == "detector":
            detector = LayoutDetector(config)
            for name in by_sheet:
                sheet = workbook.get_sheet(name)
                detection = detector.detect_with_others(sheet)

                per_sheet[name] = (detection.tables, detection.others)
        elif kind == "header":
            for name, regions in base_regions.items():
                sheet = workbook.get_sheet(name)
                new_regions = []
                for region in regions:
                    perturbed = perturb_header_region(sheet, region, spec["delta"])
                    if perturbed is None:
                        new_regions.append(region)
                    else:
                        n_perturbed += 1
                        new_regions.append(perturbed)

                per_sheet[name] = (new_regions, base_per_sheet[name][1])
        else:
            for name, bboxes in by_sheet.items():
                sheet = workbook.get_sheet(name)
                regions, np_, nd = apply_variant(sheet, bboxes, spec)
                n_perturbed += np_
                n_dropped += nd
                per_sheet[name] = (regions, others_outside(sheet, regions))

        vrec = condition_record(score_regions(workbook, per_sheet, config))
        vrec["n_tables_perturbed"] = n_perturbed
        if n_dropped:
            vrec["n_tables_dropped"] = n_dropped
        rec["variants"][vid] = vrec
    return rec





def _level_deltas(files: list[dict], vid: str) -> dict:
    out: dict = {}
    for lv in _LEVELS:
        deltas: list[int] = []
        n_scored_flip = 0
        fz_base = fz_var = 0
        for f in files:
            b = f["baseline"]["levels"][lv]
            v = f["variants"][vid]["levels"][lv]
            if b["forced_zero"]:
                fz_base += 1
            if v["forced_zero"]:
                fz_var += 1
            if b["score"] is None or v["score"] is None:
                if (b["score"] is None) != (v["score"] is None):
                    n_scored_flip += 1
                continue
            deltas.append(v["score"] - b["score"])
        n = len(deltas)
        changed = [d for d in deltas if d != 0]
        out[lv] = {
            "n_pairs": n,
            "n_changed": len(changed),
            "unchanged_pct": round(100 * (n - len(changed)) / n, 1) if n else None,
            "mean_delta": round(statistics.fmean(deltas), 2) if deltas else None,
            "mean_abs_delta": round(statistics.fmean(abs(d) for d in deltas), 2) if deltas else None,
            "median_delta": statistics.median(deltas) if deltas else None,
            "max_abs_delta": max((abs(d) for d in deltas), default=None),
            "n_scored_flip": n_scored_flip,
            "n_forced_zero_baseline": fz_base,
            "n_forced_zero_variant": fz_var,
        }
    return out


def _rule_transitions(files: list[dict], vid: str) -> dict[str, dict[str, int]]:
    trans: dict[str, dict[str, int]] = {}
    for f in files:
        rb = f["baseline"]["rules"]
        rv = f["variants"][vid]["rules"]
        for rid in sorted(set(rb) | set(rv)):
            sb = rb.get(rid, "absent")
            sv = rv.get(rid, "absent")
            if sb == sv:
                continue
            key = f"{sb}->{sv}"
            trans.setdefault(rid, {})
            trans[rid][key] = trans[rid].get(key, 0) + 1
    return {rid: dict(sorted(d.items())) for rid, d in sorted(trans.items())}


def _all_levels_unchanged(f: dict, vid: str) -> bool:
    return all(
        f["baseline"]["levels"][lv]["score"] == f["variants"][vid]["levels"][lv]["score"] for lv in _LEVELS
    )


def aggregate(per_file: list[dict], variant_ids: list[str]) -> dict:
    files = [f for f in per_file if "error" not in f]
    agg: dict = {
        "n_files": len(per_file),
        "n_ok": len(files),
        "variants": {},
    }
    for vid in variant_ids:
        n_unchanged = sum(1 for f in files if _all_levels_unchanged(f, vid))
        agg["variants"][vid] = {
            "n_tables_perturbed": sum(f["variants"][vid].get("n_tables_perturbed", 0) for f in files),
            "n_tables_dropped": sum(f["variants"][vid].get("n_tables_dropped", 0) for f in files),
            "all_levels_unchanged": n_unchanged,
            "all_levels_unchanged_pct": round(100 * n_unchanged / len(files), 1) if files else None,
            "levels": _level_deltas(files, vid),
            "rule_transitions": _rule_transitions(files, vid),
        }
    return agg





def _provenance(config, note: str, **extra) -> dict:
    import harunobu

    return {
        "schema_version": SCHEMA_VERSION,
        "harunobu_version": harunobu.__version__,
        "mode": config.mode,
        "ai": "off",
        "note": note,
        **extra,
    }


def run_inject(args, config) -> Path:
    index = sampling.build_file_index()
    existing = sampling.existing_xlsx_names()
    if args.files:
        names = [s.strip() for s in args.files.split(",") if s.strip()]
        infos = [index[n] for n in names if n in index and n in existing]
    else:
        infos = sampling.select_stratified(index, existing, args.n, args.seed)
    infos = sorted(infos, key=lambda fi: fi.file_name)

    gt_docs = cache.load_deco_cached([fi.file_name for fi in infos])
    variants = variant_specs()

    per_file: list[dict] = []
    for fi in infos:
        gt_doc = gt_docs.get(fi.file_name)
        if gt_doc is None:
            per_file.append({"file": fi.file_name, "error": "GT アノテーションなし"})
            continue
        rec = evaluate_file(paths.DECO_XLSX_DIR / fi.file_name, gt_doc, config, variants)
        rec["owner"] = fi.owner
        per_file.append(rec)
        _print_file_line(rec)

    out = {
        "provenance": _provenance(
            config,
            note=(
                "EXP-0006 (A) 誤り注入。baseline=GT(rangeAnnotations)領域の注入採点。"
                "内部レイアウトは harunobu _estimate_layout、confidence=1.0、"
                "others=領域外の非空セル(detector 条件のみ検出器自身の others)。"
            ),
            sampling={"n": args.n, "seed": args.seed, "files_explicit": bool(args.files)},
        ),
        "variant_specs": variants,
        "aggregate": aggregate(per_file, list(variants)),
        "per_file": per_file,
    }
    out_path = Path(args.out) if args.out else INJECTION_JSON
    _write_json(out_path, out)
    _print_inject_summary(out)
    return out_path


def oversplit_f1zero_files(results_path: Path) -> list[str]:
    data = json.loads(results_path.read_text(encoding="utf-8"))
    names: list[str] = []
    for r in data.get("per_file", []):
        if "eob" not in r or r.get("gt_tables", 0) <= 0:
            continue
        e = r["eob"]["EoB-2"]
        n_pred = e["tp"] + e["fp"]
        if e["f1"] == 0 and n_pred > r["gt_tables"]:
            names.append(r["file"])
    return sorted(names)


def _latest_eval_results() -> Path:
    candidates = sorted((paths.RESULTS_DIR / "layout").glob("eval-deco-*.json"))
    if not candidates:
        raise SystemExit("results/layout/eval-deco-*.json がありません。先に `just reproduce-layout` を実行してください。")
    return candidates[-1]


def run_realdata(args, config) -> Path:
    results_path = Path(args.results) if args.results else _latest_eval_results()
    names = oversplit_f1zero_files(results_path)
    if args.limit:
        names = names[: args.limit]
    print(f"過分割 F1=0 群: {len(names)} 件 (results: {results_path.name})")

    gt_docs = cache.load_deco_cached(names)
    variants = {"detector": {"kind": "detector"}}

    per_file: list[dict] = []
    for name in names:
        gt_doc = gt_docs.get(name)
        if gt_doc is None:
            per_file.append({"file": name, "error": "GT アノテーションなし"})
            continue
        rec = evaluate_file(paths.DECO_XLSX_DIR / name, gt_doc, config, variants)
        per_file.append(rec)
        _print_file_line(rec)

    out = {
        "provenance": _provenance(
            config,
            note=(
                "EXP-0006 (B) 過分割 F1=0 群の実データ差分。baseline=GT 粗括り、"
                "detector=harunobu 実レイアウト(GT アノテーションのあるシートのみ採点)。"
            ),
            results_file=results_path.name,
            n_group=len(names),
        ),
        "aggregate": aggregate(per_file, ["detector"]),
        "per_file": per_file,
    }
    out_path = Path(args.out) if args.out else REALDATA_JSON
    _write_json(out_path, out)
    _print_realdata_summary(out)
    return out_path





def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ {path}")


def _fmt_levels(levels: dict) -> str:
    parts = []
    for lv in _LEVELS:
        d = levels[lv]
        s = "―" if d["score"] is None else str(d["score"])
        parts.append(f"{lv}={s}")
    return " ".join(parts)


def _print_file_line(rec: dict) -> None:
    if "error" in rec:
        print(f"  [ERR] {rec['file']}: {rec['error']}")
        return
    print(f"  {rec['file']}: baseline {_fmt_levels(rec['baseline']['levels'])} (GT表 {rec['gt_tables']})")


def _print_inject_summary(out: dict) -> None:
    agg = out["aggregate"]
    print(f"\n=== EXP-0006 (A) 誤り注入 ({agg['n_ok']}/{agg['n_files']} files) ===")
    print(f"  {'variant':16s} {'全L不変%':>8s} {'L1 mean|Δ|':>10s} {'L2 mean|Δ|':>10s} {'L3 mean|Δ|':>10s} 主な rule 遷移")
    for vid, v in agg["variants"].items():
        mads = []
        for lv in _LEVELS:
            m = v["levels"][lv]["mean_abs_delta"]
            mads.append("―" if m is None else f"{m:.2f}")
        top = sorted(
            ((rid, sum(d.values())) for rid, d in v["rule_transitions"].items()),
            key=lambda kv: (-kv[1], kv[0]),
        )[:3]
        top_s = ", ".join(f"{rid}×{n}" for rid, n in top) if top else "―"
        pct = v["all_levels_unchanged_pct"]
        print(f"  {vid:16s} {pct if pct is not None else '―':>8} {mads[0]:>10s} {mads[1]:>10s} {mads[2]:>10s} {top_s}")


def _print_realdata_summary(out: dict) -> None:
    agg = out["aggregate"]
    v = agg["variants"]["detector"]
    print(f"\n=== EXP-0006 (B) 過分割 F1=0 群 GT vs harunobu ({agg['n_ok']}/{agg['n_files']} files) ===")
    print(f"  全レベル不変: {v['all_levels_unchanged']} 件 ({v['all_levels_unchanged_pct']}%)")
    for lv in _LEVELS:
        d = v["levels"][lv]
        print(
            f"  {lv}: pairs={d['n_pairs']} changed={d['n_changed']} meanΔ={d['mean_delta']} "
            f"mean|Δ|={d['mean_abs_delta']} medianΔ={d['median_delta']} max|Δ|={d['max_abs_delta']} "
            f"forced_zero {d['n_forced_zero_baseline']}→{d['n_forced_zero_variant']}"
        )
    top = sorted(
        ((rid, sum(d.values())) for rid, d in v["rule_transitions"].items()),
        key=lambda kv: (-kv[1], kv[0]),
    )[:8]
    if top:
        print("  rule 遷移上位: " + ", ".join(f"{rid}×{n}" for rid, n in top))





def main() -> int:
    parser = argparse.ArgumentParser(description="EXP-0006: レイアウト誤り→ルール採点のスコア感度分析")
    parser.add_argument("--part", type=str, default="inject", choices=["inject", "realdata"],
                        help="inject=(A) 誤り注入 / realdata=(B) 過分割 F1=0 群の実データ差分")
    parser.add_argument("--n", type=int, default=40, help="(A) 層別サンプル件数(既定 40)")
    parser.add_argument("--seed", type=int, default=0, help="(A) サンプリング seed(既定 0)")
    parser.add_argument("--files", type=str, default=None, help="(A) カンマ区切りで対象ファイルを明示指定")
    parser.add_argument("--results", type=str, default=None,
                        help="(B) eval-deco フル走 JSON(省略時は results/ の最新)")
    parser.add_argument("--limit", type=int, default=None, help="(B) 群の先頭 N 件だけ(スモーク用)")
    parser.add_argument("--out", type=str, default=None, help="出力 JSON パス(既定: results/layout/)")
    args = parser.parse_args()

    configure_ai("off")

    from harunobu.core.models import Config

    config = Config(mode="thorough")

    if args.part == "inject":
        run_inject(args, config)
    else:
        run_realdata(args, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
