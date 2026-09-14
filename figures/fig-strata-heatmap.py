"""Plot corrected e-Stat rule pass rates by statistical type. Uses scripts.metrics.rulestats and matplotlib and writes figures/fig-strata-stat-type.pdf."""

from __future__ import annotations

import _lib as L

STAT_TYPES = ["基幹統計", "一般統計", "業務統計", "加工統計", "その他"]


def heat(plt, run: dict, dim: str, order: list[str], names: dict[str, str], out: str) -> None:
    import numpy as np

    labels = L.rule_labels()


    states = L.load_file_rule_states()
    L.check_states_against_c1(states, run)
    by_group = L.rule_pass_stats(states, run, group_key=dim)
    groups = {g: {"per_rule": by_group.get(g, []), "n_ok": run["aggregate"]["by_stratum"][dim][g]["n_ok"]}
              for g in run["aggregate"]["by_stratum"][dim]}
    order = [o for o in order if o in groups]
    scored = [r["rule_id"] for r in run["aggregate"]["overall"]["per_rule"]
              if r["rule_id"] in L.EXCEL_RULES and r["n_applicable"] > 0]
    mat = np.full((len(scored), len(order)), np.nan)
    for j, g in enumerate(order):
        pr = {r["rule_id"]: r for r in groups[g]["per_rule"]}
        for i, rid in enumerate(scored):
            r = pr.get(rid)
            if r and r["n_applicable"] >= 10:
                mat[i, j] = 100 * r["pass_rate"]

    fig, ax = plt.subplots(figsize=(L.COL_W_IN, 4.1))
    im = ax.imshow(mat, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    for i in range(len(scored)):
        for j in range(len(order)):
            v = mat[i, j]
            if np.isnan(v):
                ax.text(j, i, "―", ha="center", va="center", fontsize=6, color="#888888")
            else:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=6,
                        color="white" if v > 60 else "black")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f"{names.get(g, g)}\n(n={groups[g]['n_ok']})" for g in order], fontsize=6.2)
    ax.set_yticks(range(len(scored)))
    ax.set_yticklabels([f"{rid}  {labels[rid]}" for rid in scored], fontsize=6.2)
    ax.tick_params(length=0)
    ax.xaxis.set_ticks_position("top")
    for boundary in (13, 18):
        ax.axhline(boundary - 0.5, color="white", lw=1.5)
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("判定通過率（%）", fontsize=6.5)
    cb.ax.tick_params(labelsize=6)
    L.save(fig, out)


def main() -> None:
    plt = L.mpl()
    run = L.load_tier1_run()
    heat(plt, run, "stat_type", STAT_TYPES, {}, "fig-strata-stat-type")


if __name__ == "__main__":
    main()
