"""Collapse repeated e-Stat catalogue entries into template records. Reads catalogue runs and writes template tables and summary JSON files to the selected run directory."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from scripts import paths
from scripts.estat import frame as frame_mod
from scripts.estat.titles import dataset_title_stem, normalize_table_name

ALLOWED_FORMATS = {"XLS", "XLS_REP"}

OUTPUT_FIELDS = [

    "gov_stats_code",
    "gov_org_code",
    "gov_org",
    "stat_type",
    "template_id",
    "dataset_title_stem",
    "table_no",
    "representative_resource_id",
    "representative_url",
    "survey_date_latest",
    "n_period_instances",
    "has_db",
    "format",

    "gov_stats_name",
    "table_name",
    "representative_dataset_id",
    "representative_dataset_title",
    "n_distinct_survey_dates",
    "n_region_variants",
    "formats",
    "key_source",
]

_DATE_TOKEN_RE = re.compile(r"\d{4,6}")


def survey_date_key(survey_date: str | None) -> int:
    if not survey_date:
        return -1
    best = -1
    for token in _DATE_TOKEN_RE.findall(survey_date):
        value = int(token)
        if len(token) == 4:
            value *= 100
        best = max(best, value)
    return best



PERIOD_ENCODED_MIN_RATIO = 0.9


@dataclass
class TemplateKey:
    gov_stats_code: str
    stem: str
    key_kind: str
    key_value: str
    key_source: str

    def template_id(self) -> str:
        digest = hashlib.sha1(
            "\x1f".join([self.gov_stats_code, self.stem, self.key_kind, self.key_value]).encode()
        ).hexdigest()
        return digest[:16]


def build_key(row: dict[str, str], stem: str, *, period_encoded_no: bool = False) -> TemplateKey:
    code = (row.get("stat_code") or "").strip()
    table_no = normalize_table_name(row.get("table_no"))


    if period_encoded_no:
        return TemplateKey(code, stem, "name", normalize_table_name(row.get("table_name")), "table_name:no_period_encoded")
    if not table_no:
        return TemplateKey(code, stem, "name", normalize_table_name(row.get("table_name")), "table_name:no_missing")
    return TemplateKey(code, stem, "no", table_no, "table_no")


def find_period_encoded_stems(stem_rows: list[tuple[str, dict[str, str]]]) -> set[str]:
    blocks: dict[str, list[dict[str, str]]] = defaultdict(list)
    for stem, row in stem_rows:
        if normalize_table_name(row.get("table_no")):
            blocks[stem].append(row)
    encoded: set[str] = set()
    for stem, members in blocks.items():
        if len(members) < 2:
            continue
        n_periods = len({survey_date_key(m.get("survey_date")) for m in members})
        n_table_no = len({normalize_table_name(m.get("table_no")) for m in members})
        n_table_name = len({normalize_table_name(m.get("table_name")) for m in members})
        if (
            n_periods > 1
            and n_table_no >= PERIOD_ENCODED_MIN_RATIO * len(members)
            and n_table_name < n_table_no
        ):
            encoded.add(stem)
    return encoded


def _representative_sort_key(row: dict[str, str]) -> tuple:

    return (
        survey_date_key(row.get("survey_date")),
        row.get("resource_release_date") or "",
        row.get("resource_last_modified_date") or "",
        row.get("resource_id") or "",
    )


def iter_candidate_rows(candidates_csv: Path) -> Iterable[dict[str, str]]:
    with open(candidates_csv, encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def dedup_survey(
    rows: Iterable[dict[str, str]], frame_row: frame_mod.FrameRow | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    n_files = 0
    dropped_formats: Counter[str] = Counter()
    stem_rows: list[tuple[str, dict[str, str]]] = []
    region_stems: dict[int, str] = {}
    for row in rows:
        n_files += 1
        fmt = (row.get("format") or "").strip().upper()
        if fmt not in ALLOWED_FORMATS:
            dropped_formats[fmt or "(empty)"] += 1
            continue
        stem_rows.append((dataset_title_stem(row.get("dataset_title")), row))
        region_stems[id(row)] = dataset_title_stem(row.get("dataset_title"), strip_region=False)

    encoded_stems = find_period_encoded_stems(stem_rows)
    groups: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    keys: dict[tuple, TemplateKey] = {}
    for stem, row in stem_rows:
        key = build_key(row, stem, period_encoded_no=stem in encoded_stems)
        kt = (key.gov_stats_code, key.stem, key.key_kind, key.key_value)
        groups[kt].append(row)
        keys[kt] = key

    templates: list[dict[str, Any]] = []
    for kt, members in groups.items():
        key = keys[kt]
        rep = max(members, key=_representative_sort_key)
        org_names = Counter(
            (m.get("organization_name") or "").strip() for m in members if m.get("organization_name")
        )
        gov_org = org_names.most_common(1)[0][0] if org_names else (
            frame_row.organization if frame_row else ""
        )
        templates.append(
            {
                "gov_stats_code": key.gov_stats_code,
                "gov_org_code": (rep.get("organization_code") or "").strip(),
                "gov_org": gov_org,
                "stat_type": frame_row.stats_type if frame_row else "",
                "template_id": key.template_id(),
                "dataset_title_stem": key.stem,
                "table_no": key.key_value if key.key_kind == "no" else "",
                "representative_resource_id": rep.get("resource_id") or "",
                "representative_url": rep.get("url") or "",
                "survey_date_latest": rep.get("survey_date") or "",
                "n_period_instances": len(members),

                "has_db": frame_row.has_db if frame_row else None,
                "format": (rep.get("format") or "").strip().upper(),
                "gov_stats_name": frame_row.gov_stats_name if frame_row else (rep.get("stat_name") or ""),
                "table_name": rep.get("table_name") or "",
                "representative_dataset_id": rep.get("dataset_id") or "",
                "representative_dataset_title": rep.get("dataset_title") or "",
                "n_distinct_survey_dates": len({m.get("survey_date") or "" for m in members}),
                "n_region_variants": len({region_stems[id(m)] for m in members}),
                "formats": "+".join(sorted({(m.get("format") or "").strip().upper() for m in members})),
                "key_source": key.key_source,
            }
        )

    templates.sort(key=lambda t: (t["dataset_title_stem"], t["table_no"], t["table_name"]))



    stem_files: Counter[str] = Counter(stem for stem, _ in stem_rows)
    stem_periods: dict[str, set[int]] = defaultdict(set)
    for stem, row in stem_rows:
        stem_periods[stem].add(survey_date_key(row.get("survey_date")))
    stem_templates: Counter[str] = Counter(t["dataset_title_stem"] for t in templates)
    no_collapse = sorted(
        stem
        for stem, n in stem_files.items()
        if len(stem_periods[stem]) > 1 and stem_templates[stem] == n
    )

    n_kept = sum(t["n_period_instances"] for t in templates)
    summary = {
        "n_files_total": n_files,
        "n_files_xls": n_kept,
        "n_files_dropped_format": dict(dropped_formats),
        "n_templates": len(templates),
        "redundancy": round(n_kept / len(templates), 1) if templates else None,
        "n_templates_fallback_key": sum(1 for t in templates if t["key_source"] != "table_no"),
        "n_templates_region_collapsed": sum(1 for t in templates if t["n_region_variants"] > 1),
        "n_stems_period_encoded_no": len(encoded_stems),
        "n_stems_multi_period_no_collapse": len(no_collapse),
        "stems_multi_period_no_collapse_sample": no_collapse[:5],
    }
    return templates, summary


def latest_run_dir(enum_dir: Path) -> Path:
    runs_root = enum_dir / "runs"
    runs = [d for d in runs_root.glob("*") if d.is_dir()]
    if not runs:
        raise SystemExit(f"run ディレクトリが無い: {runs_root}(先に estat-fetch を実行)")


    dated = [d for d in runs if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name)]
    return max(dated or runs, key=lambda d: d.name)


def write_csv(out_csv: Path, templates: list[dict[str, Any]]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(templates)


def maybe_write_parquet(out_csv: Path, templates: list[dict[str, Any]]) -> Path | None:
    try:
        import pyarrow as pa  # noqa: PLC0415
        import pyarrow.parquet as pq  # noqa: PLC0415
    except ImportError:
        return None
    out_parquet = out_csv.with_suffix(".parquet")
    table = pa.Table.from_pylist([{k: t.get(k) for k in OUTPUT_FIELDS} for t in templates])
    pq.write_table(table, out_parquet)
    return out_parquet


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--run-dir", type=Path, default=None, help="fetch の run ディレクトリ(既定: 最新 run)")
    parser.add_argument("--enum-dir", type=Path, default=None, help="列挙出力ルート(既定: dataset/e-stat/enumeration)")
    parser.add_argument("--stats-code", default=None, help="カンマ区切りで調査を絞る(既定: run 内全調査)")
    parser.add_argument("--frame", type=Path, default=None, help="フレーム CSV(既定: 凍結スナップショット)")
    parser.add_argument("--out", type=Path, default=None, help="出力 CSV(既定: <run-dir>/templates.csv)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = args.run_dir or latest_run_dir(args.enum_dir or paths.ESTAT_ENUM_DIR)
    frame = frame_mod.load_frame(args.frame)
    only = {c.strip() for c in args.stats_code.split(",")} if args.stats_code else None

    survey_dirs = sorted(
        d for d in run_dir.iterdir() if d.is_dir() and (d / "candidates.csv").is_file()
    )
    if only is not None:
        survey_dirs = [d for d in survey_dirs if d.name in only]
    if not survey_dirs:
        raise SystemExit(f"candidates.csv を持つ調査が無い: {run_dir}")

    all_templates: list[dict[str, Any]] = []
    per_survey: dict[str, dict[str, Any]] = {}
    for d in survey_dirs:
        frame_row = frame.get(d.name)
        templates, summary = dedup_survey(iter_candidate_rows(d / "candidates.csv"), frame_row)
        all_templates.extend(templates)
        name = frame_row.gov_stats_name if frame_row else "?"
        summary = {"gov_stats_name": name, "stats_type": frame_row.stats_type if frame_row else ""} | summary
        per_survey[d.name] = summary
        red = summary["redundancy"]
        print(
            f"{d.name} {name}: {summary['n_files_xls']} files -> {summary['n_templates']} templates"
            f" (冗長度 {red if red is not None else '-'}x,"
            f" fallback {summary['n_templates_fallback_key']},"
            f" 期符号化stem {summary['n_stems_period_encoded_no']})"
        )
        if summary["n_stems_multi_period_no_collapse"]:
            print(
                f"  warning: 期が複数なのに畳めなかった stem が"
                f" {summary['n_stems_multi_period_no_collapse']} 件"
                f"(例: {summary['stems_multi_period_no_collapse_sample'][:2]})",
                file=sys.stderr,
            )

    out_csv = args.out or (run_dir / "templates.csv")
    write_csv(out_csv, all_templates)
    out_parquet = maybe_write_parquet(out_csv, all_templates)
    summary_path = out_csv.with_name(out_csv.stem + "-summary.json")
    summary_path.write_text(
        json.dumps(
            {
                "run_dir": str(run_dir),


                "dedup_scheme": {
                    "scheme_version": 2,
                    "template_key": "(gov_stats_code, dataset_title_stem, key_kind, key_value)",
                    "period_encoded_min_ratio": PERIOD_ENCODED_MIN_RATIO,
                    "region_normalization": "prefecture",
                },
                "n_surveys": len(survey_dirs),
                "n_templates_total": len(all_templates),
                "per_survey": per_survey,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"templates_csv={out_csv} ({len(all_templates)} templates)")
    if out_parquet:
        print(f"templates_parquet={out_parquet}")
    else:
        print("parquet は省略(pyarrow 未導入。CSV が正本)", file=sys.stderr)
    print(f"summary={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
