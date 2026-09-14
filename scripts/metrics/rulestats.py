"""Compute rule pass rates, Wilson intervals, weighted rates, and group contrasts from rule-check records."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from random import Random


Z_95 = 1.959963984540054


MIN_N_FOR_CONTRAST = 20

BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260804


def wilson_interval(n_pass: int, n_total: int, z: float = Z_95) -> tuple[float, float] | tuple[None, None]:
    if n_total <= 0:
        return (None, None)
    p = n_pass / n_total
    denom = 1.0 + z * z / n_total
    center = (p + z * z / (2 * n_total)) / denom
    half = z * math.sqrt(p * (1 - p) / n_total + z * z / (4 * n_total * n_total)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


@dataclass
class RuleStat:

    rule_id: str
    level: int
    severity: str | None = None
    n_files: int = 0
    n_seen: int = 0
    n_applicable: int = 0
    n_pass: int = 0
    n_fail: int = 0
    n_skipped: int = 0
    n_violations: int = 0

    w_applicable: float = 0.0
    w_pass: float = 0.0

    @property
    def pass_rate(self) -> float | None:
        return self.n_pass / self.n_applicable if self.n_applicable else None

    @property
    def applicability_rate(self) -> float | None:
        return self.n_applicable / self.n_files if self.n_files else None

    @property
    def weighted_pass_rate(self) -> float | None:
        return self.w_pass / self.w_applicable if self.w_applicable else None

    def to_dict(self) -> dict:
        lo, hi = wilson_interval(self.n_pass, self.n_applicable)
        return {
            "rule_id": self.rule_id,
            "level": self.level,
            "severity": self.severity,
            "n_files": self.n_files,
            "n_applicable": self.n_applicable,
            "n_pass": self.n_pass,
            "n_fail": self.n_fail,
            "n_skipped": self.n_skipped,
            "n_violations": self.n_violations,
            "pass_rate": _round(self.pass_rate),
            "ci95_low": _round(lo),
            "ci95_high": _round(hi),
            "applicability_rate": _round(self.applicability_rate),
            "weighted_pass_rate": _round(self.weighted_pass_rate),
            "weight_applicable": round(self.w_applicable, 3),
        }


def _round(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


@dataclass
class RuleAccumulator:

    n_files: int = 0
    stats: dict[str, RuleStat] = field(default_factory=dict)

    outcomes: dict[str, list[int]] = field(default_factory=dict)

    def add(self, rules, *, weight: float = 1.0) -> None:
        self.n_files += 1
        for r in rules:
            st = self.stats.get(r.rule_id)
            if st is None:
                st = self.stats[r.rule_id] = RuleStat(
                    rule_id=r.rule_id, level=r.level, severity=r.severity
                )
                self.outcomes[r.rule_id] = []
            if st.severity is None:
                st.severity = r.severity
            st.n_seen += 1
            st.n_violations += r.n_violations
            if r.skipped:
                st.n_skipped += 1
                continue
            st.n_applicable += 1
            st.w_applicable += weight
            if r.passed:
                st.n_pass += 1
                st.w_pass += weight
                self.outcomes[r.rule_id].append(1)
            else:
                st.n_fail += 1
                self.outcomes[r.rule_id].append(0)

    def finalize(self) -> list[dict]:
        for st in self.stats.values():
            st.n_files = self.n_files
        return [self.stats[k].to_dict() for k in sorted(self.stats)]





def bootstrap_proportion_diff_ci(
    n_pass_a: int, n_a: int, n_pass_b: int, n_b: int, *,
    replicates: int = BOOTSTRAP_REPLICATES, seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    if n_a <= 0 or n_b <= 0:
        return (None, None)
    rng = Random(seed)
    pa, pb = n_pass_a / n_a, n_pass_b / n_b
    diffs = sorted(
        rng.binomialvariate(n_a, pa) / n_a - rng.binomialvariate(n_b, pb) / n_b
        for _ in range(replicates)
    )
    lo = diffs[int(0.025 * (replicates - 1))]
    hi = diffs[int(round(0.975 * (replicates - 1)))]
    return (round(lo, 4), round(hi, 4))


def stable_seed(base: int, key: str) -> int:
    return base + int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def group_contrasts(
    per_rule_by_group: dict[str, list[dict]], *,
    min_n: int = MIN_N_FOR_CONTRAST, seed: int = BOOTSTRAP_SEED,
) -> list[dict]:
    by_rule: dict[str, list[tuple[str, dict]]] = {}
    for group, rows in per_rule_by_group.items():
        for row in rows:
            if row["n_applicable"] >= min_n and row["pass_rate"] is not None:
                by_rule.setdefault(row["rule_id"], []).append((group, row))

    out: list[dict] = []
    for rule_id in sorted(by_rule):
        cand = by_rule[rule_id]
        if len(cand) < 2:
            continue
        cand.sort(key=lambda gr: (gr[1]["pass_rate"], gr[0]))
        lo_group, lo_row = cand[0]
        hi_group, hi_row = cand[-1]
        ci = bootstrap_proportion_diff_ci(
            hi_row["n_pass"], hi_row["n_applicable"], lo_row["n_pass"], lo_row["n_applicable"],
            seed=stable_seed(seed, rule_id),
        )
        out.append({
            "rule_id": rule_id,
            "n_groups_compared": len(cand),
            "max_group": hi_group,
            "max_pass_rate": hi_row["pass_rate"],
            "max_n_applicable": hi_row["n_applicable"],
            "min_group": lo_group,
            "min_pass_rate": lo_row["pass_rate"],
            "min_n_applicable": lo_row["n_applicable"],
            "diff": round(hi_row["pass_rate"] - lo_row["pass_rate"], 4),
            "diff_ci95_low": ci[0],
            "diff_ci95_high": ci[1],
        })
    out.sort(key=lambda d: -abs(d["diff"]))
    return out
