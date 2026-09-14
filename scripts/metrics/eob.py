"""Compute Error-of-Boundary and matched IoU metrics for table regions. Depends on scripts.ir and returns in-memory metric values."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.ir import IRBBox


def boundary_error(a: IRBBox, b: IRBBox) -> int:
    return max(
        abs(a.first_row - b.first_row),
        abs(a.first_col - b.first_col),
        abs(a.last_row - b.last_row),
        abs(a.last_col - b.last_col),
    )


def iou(a: IRBBox, b: IRBBox) -> float:
    inter_rows = min(a.last_row, b.last_row) - max(a.first_row, b.first_row) + 1
    inter_cols = min(a.last_col, b.last_col) - max(a.first_col, b.first_col) + 1
    if inter_rows <= 0 or inter_cols <= 0:
        return 0.0
    inter = inter_rows * inter_cols
    union = a.area() + b.area() - inter
    return inter / union if union > 0 else 0.0


def match_boxes(
    preds: list[IRBBox], gts: list[IRBBox], n: int
) -> list[tuple[int, int, float]]:
    candidates: list[tuple[int, float, int, int]] = []
    for pi, p in enumerate(preds):
        for gi, g in enumerate(gts):
            be = boundary_error(p, g)
            if be <= n:
                candidates.append((be, -iou(p, g), pi, gi))
    candidates.sort()

    used_pred: set[int] = set()
    used_gt: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for be, neg_iou, pi, gi in candidates:
        if pi in used_pred or gi in used_gt:
            continue
        used_pred.add(pi)
        used_gt.add(gi)
        matches.append((pi, gi, -neg_iou))
    return matches


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


@dataclass
class EoBCounts:

    n: int
    tp: int = 0
    fp: int = 0
    fn: int = 0
    iou_sum: float = 0.0

    def add_pair_set(self, preds: list[IRBBox], gts: list[IRBBox]) -> None:
        matches = match_boxes(preds, gts, self.n)
        tp = len(matches)
        self.tp += tp
        self.fp += len(preds) - tp
        self.fn += len(gts) - tp
        self.iou_sum += sum(m[2] for m in matches)

    @property
    def precision(self) -> float:
        return prf(self.tp, self.fp, self.fn)[0]

    @property
    def recall(self) -> float:
        return prf(self.tp, self.fp, self.fn)[1]

    @property
    def f1(self) -> float:
        return prf(self.tp, self.fp, self.fn)[2]

    @property
    def mean_iou(self) -> float:
        return self.iou_sum / self.tp if self.tp else 0.0

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "mean_iou": round(self.mean_iou, 4),
        }
