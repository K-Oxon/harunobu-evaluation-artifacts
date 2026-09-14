"""Run deterministic AI-OFF rule scoring for frozen e-Stat workbooks. Depends on harunobu and writes results/estat/rulescore-tier1-replay.json by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from scripts import paths
from scripts.metrics import rulestats

RULESCORE_SCHEMA_VERSION = "0.2.0"
FILE_SCHEMA_VERSION = "0.1.0"
LEVEL_LABELS = {1: "L1 閲覧・転記", 2: "L2 集計・分析", 3: "L3 連携・自動化"}
AI_DEPENDENT_RULES = frozenset(
    {"L1-05", "L1-09", "L1-11", "L2-01", "L2-02", "L2-04", "L2-05", "L3-04", "L3-06", "L3-09"}
)
_SCOREABLE_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv"}
_STRATA_KEYS = ("cell", "gov_org", "stat_type", "table_shape")


class RuleCheck(BaseModel):
    rule_id: str
    level: int
    passed: bool
    confidence: float
    severity: str | None = None
    skipped: bool = False
    ai_dependent: bool = False
    n_violations: int = 0


class LevelResult(BaseModel):
    level: int
    label: str
    score: int | None
    passed: int
    total: int
    forced_zero: bool = False


class FileRuleScore(BaseModel):
    file_name: str
    file_hash: str
    ok: bool
    error: str | None = None
    elapsed_sec: float | None = None
    sheet_count: int | None = None
    n_tables: int | None = None
    levels: list[LevelResult] = Field(default_factory=list)
    rules: list[RuleCheck] = Field(default_factory=list)
    strata: dict[str, str] = Field(default_factory=dict)
    weight: float = 1.0


class RunProvenance(BaseModel):
    schema_version: str = RULESCORE_SCHEMA_VERSION
    generated_at: str
    harunobu_version: str
    mode: str
    ai: str = "off"
    ai_disabled_env: str = "1"
    note: str = (
        "AI-OFF: HARUNOBU_AI_DISABLED=1. AI-assisted rules use deterministic "
        "fallbacks or confidence=0 (excluded from the applicable denominator)."
    )


class RuleScoreRun(BaseModel):
    provenance: RunProvenance
    files: list[FileRuleScore]
    aggregate: dict


def configure_ai(ai: str = "off", **_: object) -> None:

    if ai != "off":
        raise ValueError("The public reproduction supports AI-OFF only")
    os.environ["HARUNOBU_AI_DISABLED"] = "1"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _severity_str(value: object) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _rule_level(rule_id: str) -> int:
    try:
        return int(rule_id.split("-", 1)[0].lstrip("Ll"))
    except (ValueError, IndexError):
        return 0


def _aggregate_rule_checks(result: object) -> list[RuleCheck]:

    acc: dict[str, dict] = {}
    for sheet in result.sheets:
        for table in sheet.tables:
            for rule_id, check in table.mr_result.all_results().items():
                current = acc.setdefault(
                    rule_id,
                    {
                        "passed": True,
                        "confidence": 0.0,
                        "severity": None,
                        "n_violations": 0,
                    },
                )
                current["passed"] = current["passed"] and check.passed
                current["confidence"] = max(current["confidence"], check.confidence)
                current["severity"] = current["severity"] or _severity_str(check.severity)
                current["n_violations"] += len(check.violations)
    return [
        RuleCheck(
            rule_id=rule_id,
            level=_rule_level(rule_id),
            passed=value["passed"],
            confidence=value["confidence"],
            severity=value["severity"],
            skipped=value["confidence"] == 0.0,
            ai_dependent=rule_id in AI_DEPENDENT_RULES,
            n_violations=value["n_violations"],
        )
        for rule_id, value in sorted(acc.items())
    ]


def score_file(path: str | Path, *, mode: str = "thorough", **_: object) -> FileRuleScore:
    configure_ai()
    from harunobu import Config, analyze
    from harunobu.core.scorer import LevelScorer

    target = Path(path)
    digest = content_hash(target.read_bytes())
    started = time.monotonic()
    try:
        result = analyze(target, Config(mode=mode))
    except Exception as exc:
        return FileRuleScore(
            file_name=target.name,
            file_hash=digest,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            elapsed_sec=round(time.monotonic() - started, 2),
        )
    scoring = LevelScorer().score_analysis(result)
    levels = [
        LevelResult(
            level=level,
            label=LEVEL_LABELS.get(level, f"L{level}"),
            score=value.score,
            passed=value.passed,
            total=value.total,
            forced_zero=value.forced_zero,
        )
        for level, value in sorted(scoring.per_level.items())
    ]
    return FileRuleScore(
        file_name=target.name,
        file_hash=digest,
        ok=True,
        elapsed_sec=round(time.monotonic() - started, 2),
        sheet_count=len(result.sheets),
        n_tables=sum(len(sheet.tables) for sheet in result.sheets),
        levels=levels,
        rules=_aggregate_rule_checks(result),
    )


def _group_stats(files: list[FileRuleScore]) -> dict:
    ok = [item for item in files if item.ok]
    accumulator = rulestats.RuleAccumulator()
    for item in ok:
        accumulator.add(item.rules, weight=item.weight)
    levels: dict[str, dict] = {}
    for level in (1, 2, 3):
        scores = [
            row.score
            for item in ok
            for row in item.levels
            if row.level == level and row.score is not None
        ]
        levels[f"L{level}"] = {
            "label": LEVEL_LABELS[level],
            "n_scored": len(scores),
            "mean_score": round(statistics.fmean(scores), 1) if scores else None,
            "median_score": round(statistics.median(scores), 1) if scores else None,
            "min_score": min(scores) if scores else None,
            "max_score": max(scores) if scores else None,
            "n_zero": sum(score == 0 for score in scores),
            "n_forced_zero": sum(
                row.forced_zero for item in ok for row in item.levels if row.level == level
            ),
        }
    return {
        "n_files": len(files),
        "n_ok": len(ok),
        "n_error": len(files) - len(ok),
        "levels": levels,
        "per_rule": accumulator.finalize(),
        "weight_total": round(sum(item.weight for item in ok), 3),
    }


def aggregate(files: list[FileRuleScore]) -> dict:
    output: dict = {"overall": _group_stats(files)}
    dimensions = sorted({key for item in files for key in item.strata})
    by: dict[str, dict] = {}
    contrasts: dict[str, list[dict]] = {}
    for dimension in dimensions:
        groups: dict[str, list[FileRuleScore]] = {}
        for item in files:
            groups.setdefault(item.strata.get(dimension, "(未分類)"), []).append(item)
        by[dimension] = {name: _group_stats(group) for name, group in sorted(groups.items())}
        rows = rulestats.group_contrasts(
            {name: stats["per_rule"] for name, stats in by[dimension].items()}
        )
        if rows:
            contrasts[dimension] = rows
    if by:
        output["by_stratum"] = by
    if contrasts:
        output["group_contrasts"] = contrasts
    return output


def _load_manifest(path: Path) -> dict[str, dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document.get("entries", document)
    if isinstance(rows, dict):
        return {name: dict(value) for name, value in rows.items()}
    output: dict[str, dict] = {}
    for row in rows:
        name = row.get("file_name")
        if name:
            output[name] = row
            output.setdefault(Path(name).with_suffix(".xlsx").name, row)
    return output


def _entry_weight(row: dict) -> float:
    try:
        value = float(row.get("n_period_instances", 1) or 1)
    except (TypeError, ValueError):
        return 1.0
    return value if value > 0 else 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen AI-OFF harunobu rule evaluation")
    parser.add_argument("--dir", type=Path, default=paths.ESTAT_XLSX_DIR)
    parser.add_argument("--manifest", type=Path, default=paths.ESTAT_MANIFEST)
    parser.add_argument("--mode", choices=("lite", "standard", "thorough"), default="thorough")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--out",
        type=Path,
        default=paths.RESULTS_DIR / "estat" / "rulescore-tier1-replay.json",
    )
    args = parser.parse_args()

    targets = sorted(
        path for path in args.dir.iterdir() if path.suffix.lower() in _SCOREABLE_SUFFIXES
    ) if args.dir.is_dir() else []
    if args.limit:
        targets = targets[: args.limit]
    if not targets:
        parser.error(f"no scoreable files under {args.dir}")

    metadata = _load_manifest(args.manifest)
    files: list[FileRuleScore] = []
    for index, target in enumerate(targets, start=1):
        item = score_file(target, mode=args.mode)
        row = metadata.get(target.name, {})
        item.strata = {key: str(row[key]) for key in _STRATA_KEYS if row.get(key) is not None}
        item.weight = _entry_weight(row)
        files.append(item)
        print(f"[{index}/{len(targets)}] {target.name}: {'ok' if item.ok else item.error}", flush=True)

    import harunobu

    run = RuleScoreRun(
        provenance=RunProvenance(
            generated_at=datetime.now(timezone.utc).isoformat(),
            harunobu_version=harunobu.__version__,
            mode=args.mode,
        ),
        files=files,
        aggregate=aggregate(files),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
