"""Plot best-match IoU distributions from tracked DECO and TableSense results. Uses matplotlib and writes figures/fig-iou-hist.pdf."""

from __future__ import annotations

import _lib as L


def main() -> None:
    plt = L.mpl()
    import numpy as np

    deco, ts = L.load_deco_eval(), L.load_tablesense_eval()
    d, t = deco["micro"]["iou_dist"]["gt"], ts["micro"]["iou_dist"]["gt"]
    bins = np.arange(10)
    w = 0.4
    fig, ax = plt.subplots(figsize=(L.COL_W_IN, 2.0))
    ax.bar(bins - w / 2, 100 * np.array(d["hist"]) / d["n"], w, color=L.C_L1, label=f"DECO(正解表 {d['n']:,})")
    ax.bar(bins + w / 2, 100 * np.array(t["hist"]) / t["n"], w, color=L.C_L2, label=f"TableSense 系列(正解表 {t['n']:,})")
    ax.set_xticks(bins)
    ax.set_xticklabels([f"{i / 10:.1f}–{(i + 1) / 10:.1f}" for i in range(10)], fontsize=5.8, rotation=40,
                       ha="right", rotation_mode="anchor")
    ax.set_xlabel("正解表と最も重なる予測との IoU")
    ax.set_ylabel("正解表の割合(%)")
    ax.legend(frameon=False, loc="upper center")
    print(f"[fig-iou-hist] share>=0.9 DECO {100 * d['share_ge_09']:.1f}% / TS {100 * t['share_ge_09']:.1f}%; "
          f"share<0.1 DECO {100 * d['hist'][0] / d['n']:.1f}% / TS {100 * t['hist'][0] / t['n']:.1f}%")
    L.save(fig, "fig-iou-hist")


if __name__ == "__main__":
    main()
