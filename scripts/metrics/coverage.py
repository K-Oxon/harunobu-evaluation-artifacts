"""Compute geometric coverage and purity for table regions. Depends on scripts.ir and returns in-memory metric values."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.ir import IRBBox


def _covers(boxes: list[IRBBox], r0: int, r1: int, c0: int, c1: int) -> bool:
    for b in boxes:
        if (
            b.first_row <= r0
            and r1 <= b.last_row + 1
            and b.first_col <= c0
            and c1 <= b.last_col + 1
        ):
            return True
    return False


def union_areas(gts: list[IRBBox], preds: list[IRBBox]) -> tuple[int, int, int]:
    if not gts and not preds:
        return 0, 0, 0

    boxes = gts + preds
    xs = sorted({b.first_row for b in boxes} | {b.last_row + 1 for b in boxes})
    ys = sorted({b.first_col for b in boxes} | {b.last_col + 1 for b in boxes})

    gt_area = pred_area = inter_area = 0
    for i in range(len(xs) - 1):
        r0, r1 = xs[i], xs[i + 1]
        rh = r1 - r0
        for j in range(len(ys) - 1):
            c0, c1 = ys[j], ys[j + 1]
            cell = rh * (c1 - c0)
            in_gt = _covers(gts, r0, r1, c0, c1)
            in_pred = _covers(preds, r0, r1, c0, c1)
            if in_gt:
                gt_area += cell
            if in_pred:
                pred_area += cell
            if in_gt and in_pred:
                inter_area += cell
    return gt_area, pred_area, inter_area


@dataclass
class CoverageCounts:

    gt_area: int = 0
    pred_area: int = 0
    inter_area: int = 0

    def add_pair_set(self, preds: list[IRBBox], gts: list[IRBBox]) -> None:
        g, p, i = union_areas(gts, preds)
        self.gt_area += g
        self.pred_area += p
        self.inter_area += i

    @property
    def coverage(self) -> float:
        return self.inter_area / self.gt_area if self.gt_area else 0.0

    @property
    def purity(self) -> float:
        return self.inter_area / self.pred_area if self.pred_area else 0.0

    @property
    def f1(self) -> float:
        c, p = self.coverage, self.purity
        return 2 * c * p / (c + p) if (c + p) else 0.0

    def as_dict(self) -> dict:
        return {
            "gt_area": self.gt_area,
            "pred_area": self.pred_area,
            "inter_area": self.inter_area,
            "coverage": round(self.coverage, 4),
            "purity": round(self.purity, 4),
            "f1": round(self.f1, 4),
        }
