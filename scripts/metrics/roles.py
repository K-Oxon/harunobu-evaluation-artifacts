"""Compute macro-F1 for DECO cell-role annotations. Depends on scripts.ir and returns in-memory class metrics."""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.ir import IRCellRole, Role

CLASSES: tuple[Role, ...] = ("Header", "Data", "Other")


def _role_map(cells: list[IRCellRole]) -> dict[tuple[int, int], Role]:
    return {(c.row, c.col): c.role for c in cells}


@dataclass
class RoleConfusion:

    tp: dict[Role, int] = field(default_factory=lambda: {c: 0 for c in CLASSES})
    fp: dict[Role, int] = field(default_factory=lambda: {c: 0 for c in CLASSES})
    fn: dict[Role, int] = field(default_factory=lambda: {c: 0 for c in CLASSES})

    def add(self, pred_cells: list[IRCellRole], gt_cells: list[IRCellRole]) -> None:
        pred = _role_map(pred_cells)
        for coord, true_role in _role_map(gt_cells).items():
            pred_role = pred.get(coord, "Other")
            if pred_role == true_role:
                self.tp[true_role] += 1
            else:
                self.fp[pred_role] += 1
                self.fn[true_role] += 1

    def per_class(self) -> dict[Role, dict[str, float]]:
        out: dict[Role, dict[str, float]] = {}
        for c in CLASSES:
            tp, fp, fn = self.tp[c], self.fp[c], self.fn[c]
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
            out[c] = {
                "support": tp + fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            }
        return out

    def macro_f1(self) -> float:
        pc = self.per_class()
        return round(sum(pc[c]["f1"] for c in CLASSES) / len(CLASSES), 4)

    def as_dict(self) -> dict:
        return {"macro_f1": self.macro_f1(), "per_class": self.per_class()}
