"""Summarize XLS and XLSX composition in data/estat/tier1/manifest.json and write Markdown tables to standard output."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts import paths

EXTS = [".xls", ".xlsx"]


def load_entries(manifest_path: Path) -> list[dict[str, Any]]:
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)["entries"]


def ext_of(entry: dict[str, Any]) -> str:
    return Path(entry["file_name"]).suffix.lower()


def survey_year(entry: dict[str, Any]) -> int | None:
    m = re.match(r"(\d{4})", entry.get("survey_date") or "")
    return int(m.group(1)) if m else None


def _table(rows: list[tuple[str, int, int, int]], key_label: str) -> str:
    lines = [f"| {key_label} | 総数 | .xls | .xlsx | xls比率 |", "|---|--:|--:|--:|--:|"]
    for label, total, xls, xlsx in rows:
        ratio = xls / total * 100 if total else 0.0
        lines.append(f"| {label} | {total} | {xls} | {xlsx} | {ratio:.1f}% |")
    return "\n".join(lines)


def by_key(entries: list[dict[str, Any]], key: str) -> str:
    cross: dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        cross[e[key]][ext_of(e)] += 1
    rows = []
    for label, c in cross.items():
        total = sum(c.values())
        rows.append((label, total, c.get(".xls", 0), c.get(".xlsx", 0)))
    rows.sort(key=lambda r: -(r[2] / r[1] if r[1] else 0))
    return _table(rows, key)


def by_year_bucket(entries: list[dict[str, Any]], bucket: int = 5) -> str:
    cross: dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        y = survey_year(e)
        label = "不明" if y is None else f"{(y // bucket) * bucket}–{(y // bucket) * bucket + bucket - 1}"
        cross[label][ext_of(e)] += 1
    rows = []
    for label, c in cross.items():
        total = sum(c.values())
        rows.append((label, total, c.get(".xls", 0), c.get(".xlsx", 0)))
    rows.sort(key=lambda r: (r[0] == "不明", r[0]))
    return _table(rows, "年代")


def top_surveys(entries: list[dict[str, Any]], n: int = 20) -> str:
    xls_count: Counter = Counter()
    total_count: Counter = Counter()
    for e in entries:
        k = (e["gov_org"], e["gov_stats_name"])
        total_count[k] += 1
        if ext_of(e) == ".xls":
            xls_count[k] += 1
    rows = sorted(xls_count.items(), key=lambda kv: -kv[1])[:n]
    lines = ["| 府省 | 調査名 | .xls件 | 総件 |", "|---|---|--:|--:|"]
    for (org, name), xls_n in rows:
        lines.append(f"| {org} | {name} | {xls_n} | {total_count[(org, name)]} |")
    n_surveys_with_xls = sum(1 for v in xls_count.values() if v > 0)
    n_surveys_total = len(total_count)
    footer = f"\n`.xls` は {n_surveys_with_xls}/{n_surveys_total} 個の異なる調査に由来する(特定の少数調査への集中ではない)。"
    return "\n".join(lines) + footer


def render(entries: list[dict[str, Any]]) -> str:
    total = len(entries)
    xls = sum(1 for e in entries if ext_of(e) == ".xls")
    xlsx = total - xls
    parts = [
        "# Tier 1(600 件)`.xls`/`.xlsx` 内訳",
        "",
        f"総数 {total} 件のうち `.xls` **{xls} 件({xls / total * 100:.1f}%)** / `.xlsx` {xlsx} 件。",
        "",
        "## 年代別",
        "",
        by_year_bucket(entries),
        "",
        "## 府省別",
        "",
        by_key(entries, "gov_org"),
        "",
        "## 統計種別",
        "",
        by_key(entries, "stat_type"),
        "",
        "## `.xls` の由来調査(上位)",
        "",
        top_surveys(entries),
        "",
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--manifest", type=Path, default=paths.ESTAT_DIR / "tier1" / "manifest.json")
    p.add_argument("--out", type=Path, default=None, help="省略時は標準出力")
    args = p.parse_args(argv)

    entries = load_entries(args.manifest)
    text = render(entries)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
