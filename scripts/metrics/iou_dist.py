"""Compute best-match IoU distributions for reference and predicted tables. Depends on scripts.ir and returns in-memory summaries."""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.ir import IRBBox
from scripts.metrics.eob import iou


N_BINS = 10


def best_match_ious(
    preds: list[IRBBox], gts: list[IRBBox]
) -> tuple[list[float], list[float]]:
    gt_best = [max((iou(p, g) for p in preds), default=0.0) for g in gts]
    pred_best = [max((iou(p, g) for g in gts), default=0.0) for p in preds]
    return gt_best, pred_best


def quantile(sorted_vals: list[float], q: float) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    h = (n - 1) * q
    lo = int(h)
    hi = min(lo + 1, n - 1)
    frac = h - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def summarize(vals: list[float]) -> dict:
    n = len(vals)
    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "p10": 0.0,
            "p25": 0.0,
            "p50": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "share_zero": 0.0,
            "share_ge_05": 0.0,
            "share_ge_09": 0.0,
            "hist": [0] * N_BINS,
        }
    s = sorted(vals)
    hist = [0] * N_BINS
    for v in s:

        hist[min(int(v * N_BINS), N_BINS - 1)] += 1
    return {
        "n": n,
        "mean": round(sum(s) / n, 4),
        "p10": round(quantile(s, 0.10), 4),
        "p25": round(quantile(s, 0.25), 4),
        "p50": round(quantile(s, 0.50), 4),
        "p75": round(quantile(s, 0.75), 4),
        "p90": round(quantile(s, 0.90), 4),
        "share_zero": round(sum(1 for v in s if v == 0.0) / n, 4),
        "share_ge_05": round(sum(1 for v in s if v >= 0.5) / n, 4),
        "share_ge_09": round(sum(1 for v in s if v >= 0.9) / n, 4),
        "hist": hist,
    }


@dataclass
class IoUDistCounts:

    gt_best: list[float] = field(default_factory=list)
    pred_best: list[float] = field(default_factory=list)

    def add_pair_set(self, preds: list[IRBBox], gts: list[IRBBox]) -> None:
        g, p = best_match_ious(preds, gts)
        self.gt_best.extend(g)
        self.pred_best.extend(p)

    def as_dict(self) -> dict:
        return {
            "gt": summarize(self.gt_best),
            "pred": summarize(self.pred_best),
        }
