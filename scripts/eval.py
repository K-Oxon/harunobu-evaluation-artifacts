"""Evaluate harunobu layouts against DECO or TableSense annotations. Depends on harunobu, dataset loaders, and metric modules and writes JSON under results/layout/."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from random import Random

from scripts import cache, paths, sampling
from scripts.ir import IRBBox, IRDocument
from scripts.loaders import tablesense
from scripts.metrics.coverage import CoverageCounts
from scripts.metrics.eob import EoBCounts
from scripts.metrics.iou_dist import IoUDistCounts
from scripts.metrics.roles import RoleConfusion

EOB_NS = (0, 1, 2)


@dataclass
class EvalTarget:

    file_name: str
    path: Path
    meta: dict = field(default_factory=dict)


def _pred_boxes(doc: IRDocument, sheet_name: str) -> list[IRBBox]:
    sheet = doc.sheet_by_name(sheet_name)
    if sheet is None:
        return []
    return [t.bbox for t in sheet.tables if not t.abstain]


def evaluate(
    targets: list[EvalTarget],
    gt_docs: dict[str, IRDocument],
    mode: str,
    *,
    dataset: str = "deco",
    manifest: list[dict] | None = None,
    use_cache: bool = True,
) -> dict:
    with_roles = dataset == "deco"


    micro_eob = {n: EoBCounts(n=n) for n in EOB_NS}
    micro_roles = RoleConfusion() if with_roles else None
    micro_cov = CoverageCounts()
    micro_iou = IoUDistCounts()
    per_file: list[dict] = []

    for target in targets:
        name = target.file_name
        gt_doc = gt_docs.get(name)
        record: dict = {"file": name}
        record.update({k: v for k, v in target.meta.items() if k in ("corpus", "split")})

        if gt_doc is None or not gt_doc.sheets:
            record["error"] = "GT アノテーションなし"
            per_file.append(record)
            continue

        try:
            har_doc = cache.cached_adapt_file(target.path, mode=mode, use_cache=use_cache)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            per_file.append(record)
            continue

        file_eob = {n: EoBCounts(n=n) for n in EOB_NS}
        file_roles = RoleConfusion() if with_roles else None
        file_cov = CoverageCounts()
        file_iou = IoUDistCounts()
        sheets_missing: list[str] = []

        for gt_sheet in gt_doc.sheets:
            if har_doc.sheet_by_name(gt_sheet.sheet_name) is None:

                sheets_missing.append(gt_sheet.sheet_name)
            preds = _pred_boxes(har_doc, gt_sheet.sheet_name)
            gts = [t.bbox for t in gt_sheet.tables]
            for n in EOB_NS:
                file_eob[n].add_pair_set(preds, gts)
                micro_eob[n].add_pair_set(preds, gts)
            file_cov.add_pair_set(preds, gts)
            micro_cov.add_pair_set(preds, gts)
            file_iou.add_pair_set(preds, gts)
            micro_iou.add_pair_set(preds, gts)

            if with_roles:
                har_sheet = har_doc.sheet_by_name(gt_sheet.sheet_name)
                har_cells = har_sheet.cell_roles if har_sheet else []
                file_roles.add(har_cells, gt_sheet.cell_roles)
                micro_roles.add(har_cells, gt_sheet.cell_roles)

        record["sheets"] = len(gt_doc.sheets)
        record["gt_tables"] = sum(len(s.tables) for s in gt_doc.sheets)
        record["eob"] = {f"EoB-{n}": file_eob[n].as_dict() for n in EOB_NS}
        record["roles"] = file_roles.as_dict() if with_roles else None
        record["coverage"] = file_cov.as_dict()

        record["iou_dist"] = {
            "gt_best": [round(v, 4) for v in file_iou.gt_best],
            "pred_best": [round(v, 4) for v in file_iou.pred_best],
        }
        if sheets_missing:
            record["gt_sheets_missing_in_pred"] = sheets_missing
        per_file.append(record)

    result: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset,
        "mode": mode,
        "use_cache": use_cache,
        "n_files": len(targets),
    }
    if dataset == "deco":
        result["n_owners"] = len({t.meta.get("owner") for t in targets})
    result["manifest"] = manifest if manifest is not None else [{"file": t.file_name, **t.meta} for t in targets]
    result["micro"] = {
        "eob": {f"EoB-{n}": micro_eob[n].as_dict() for n in EOB_NS},
        "roles": micro_roles.as_dict() if with_roles else None,
        "coverage": micro_cov.as_dict(),
        "iou_dist": micro_iou.as_dict(),
    }
    result["per_file"] = per_file
    return result


def _print_summary(result: dict) -> None:
    dataset = result.get("dataset", "deco")
    owners = f", {result['n_owners']} owners" if "n_owners" in result else ""
    print(f"\n=== EoB 評価 ({dataset}, mode={result['mode']}, {result['n_files']} files{owners}) ===")
    n_err = sum(1 for r in result["per_file"] if "error" in r)
    if n_err:
        print(f"  (errors: {n_err} files)")
    n_missing = sum(1 for r in result["per_file"] if r.get("gt_sheets_missing_in_pred"))
    if n_missing:
        print(f"  (GT シートが予測側に無いファイル: {n_missing})")

    print("\n[micro] 全ファイル横断")
    for n in EOB_NS:
        d = result["micro"]["eob"][f"EoB-{n}"]
        print(
            f"  EoB-{n}: P={d['precision']:.3f} R={d['recall']:.3f} F1={d['f1']:.3f} "
            f"IoU={d['mean_iou']:.3f} (tp={d['tp']} fp={d['fp']} fn={d['fn']})"
        )
    roles = result["micro"]["roles"]
    if roles is not None:
        print(f"  roles macro-F1: {roles['macro_f1']:.3f}")
        for cls, m in roles["per_class"].items():
            print(f"    {cls:7s} P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} (support={m['support']})")
    cov = result["micro"].get("coverage")
    if cov:
        print(f"  coverage(被覆)={cov['coverage']:.3f} purity(純度)={cov['purity']:.3f} F1={cov['f1']:.3f}")
    idist = result["micro"].get("iou_dist")
    if idist:
        g, p = idist["gt"], idist["pred"]
        print(
            f"  best-match IoU: GT側 mean={g['mean']:.3f} p50={g['p50']:.3f} (n={g['n']}) / "
            f"予測側 mean={p['mean']:.3f} p50={p['p50']:.3f} (n={p['n']})"
        )


def _deco_targets(args: argparse.Namespace) -> tuple[list[EvalTarget], dict[str, IRDocument], list[dict]]:
    index = sampling.build_file_index()
    existing = sampling.existing_xlsx_names()

    if args.files:
        names = [s.strip() for s in args.files.split(",") if s.strip()]
        infos = [index[n] for n in names if n in index and n in existing]
        skipped = [n for n in names if n not in index or n not in existing]
        if skipped:
            print(f"(skip: index/実ファイルに無い {len(skipped)} 件: {skipped})")
    else:
        infos = sampling.select_stratified(index, existing, args.n, args.seed)

    targets = [
        EvalTarget(
            file_name=fi.file_name,
            path=paths.DECO_XLSX_DIR / fi.file_name,
            meta={"owner": fi.owner, "n_tables": fi.n_tables, "has_derived": fi.has_derived},
        )
        for fi in infos
    ]
    gt_docs = cache.load_deco_cached([t.file_name for t in targets], use_cache=not args.no_cache)
    return targets, gt_docs, sampling.manifest(infos)


def _tablesense_targets(args: argparse.Namespace) -> tuple[list[EvalTarget], dict[str, IRDocument], list[dict]]:
    index = tablesense.file_index()
    try:
        status = tablesense_conversion_status()
    except FileNotFoundError:
        raise SystemExit(
            "変換結果 JSON がありません。先に `just convert-tablesense` を実行してください: "
            f"{paths.TABLESENSE_CONVERSION_JSON}"
        )

    eligible = sorted(
        (n for n, info in index.items() if status.get(n) == "ok"),
        key=lambda n: index[n].relpath,
    )
    excluded = {n: s for n, s in status.items() if s != "ok"}
    if excluded:
        by_status: dict[str, int] = {}
        for s in excluded.values():
            by_status[s] = by_status.get(s, 0) + 1
        print(f"(変換除外 {len(excluded)} 件: {by_status})")

    if args.files:
        names = [s.strip() for s in args.files.split(",") if s.strip()]
        skipped = [n for n in names if n not in eligible]
        if skipped:
            print(f"(skip: eligible に無い {len(skipped)} 件: {skipped})")
        names = [n for n in names if n in eligible]
    elif args.n < len(eligible):
        names = sorted(Random(args.seed).sample(eligible, args.n), key=lambda n: index[n].relpath)
    else:
        names = eligible

    targets = [
        EvalTarget(
            file_name=n,
            path=paths.TABLESENSE_XLSX_DIR / index[n].relpath,
            meta={
                "corpus": index[n].corpus,
                "split": index[n].split,
                "relpath": index[n].relpath,
                "n_tables": index[n].n_tables,
            },
        )
        for n in names
    ]
    gt_docs = tablesense.load_tablesense(names)
    return targets, gt_docs, [{"file": t.file_name, **t.meta} for t in targets]


def tablesense_conversion_status() -> dict[str, str]:
    from scripts.convert_tablesense import load_conversion_status

    return load_conversion_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="harunobu のレイアウト検出を GT データセットで EoB 評価する")
    parser.add_argument("--dataset", type=str, default="deco", choices=["deco", "tablesense"])
    parser.add_argument("--n", type=int, default=40, help="対象件数(deco: 層別 / tablesense: 決定的サンプル)")
    parser.add_argument("--seed", type=int, default=0, help="サンプリングの seed")
    parser.add_argument("--files", type=str, default=None, help="カンマ区切りで対象を明示(index にあるもののみ)")
    parser.add_argument("--mode", type=str, default="standard", choices=["lite", "standard", "thorough"])
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを使わない")
    parser.add_argument("--out", type=Path, default=None, help="出力JSONパス")
    args = parser.parse_args()

    if args.dataset == "deco":
        targets, gt_docs, manifest = _deco_targets(args)
    else:
        targets, gt_docs, manifest = _tablesense_targets(args)

    if not targets:
        print("対象ファイルが見つかりません(preflight を確認)")
        return 1

    result = evaluate(
        targets,
        gt_docs,
        args.mode,
        dataset=args.dataset,
        manifest=manifest,
        use_cache=not args.no_cache,
    )
    _print_summary(result)

    (paths.RESULTS_DIR / "layout").mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out or paths.RESULTS_DIR / "layout" / f"eval-{args.dataset}-{ts}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
