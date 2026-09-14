"""Plot corrected e-Stat rule pass rates from tracked results. Uses scripts.metrics.rulestats and matplotlib and writes figures/fig-rule-pass.pdf."""

from __future__ import annotations

import _lib as L


def main() -> None:
    plt = L.mpl()
    run = L.load_tier1_run()
    labels, unscored = L.rule_labels(), L.unscored_reason()
    states = L.load_file_rule_states()
    L.check_states_against_c1(states, run)
    per = [r for r in L.rule_pass_stats(states, run)["overall"] if r["rule_id"] in L.EXCEL_RULES]
    per.sort(key=lambda r: r["rule_id"])

    fig, ax = plt.subplots(figsize=(L.COL_W_IN, 4.1))
    ys = list(range(len(per)))[::-1]
    for y, r in zip(ys, per):
        rid = r["rule_id"]
        lvl = r["level"]
        if r["n_applicable"] == 0:
            reason = {"ai_gated": "AI ゲート(AI-OFF では判定不能)", "not_implemented": "参考実装が判定対象外",
                      "bulk_only": "一括評価専用"}[unscored[rid][0]]
            ax.text(1.0, y, reason, va="center", ha="left", fontsize=6, color="#666666", style="italic")
            continue
        p = 100 * r["pass_rate"]
        lo, hi = 100 * r["ci95_low"], 100 * r["ci95_high"]
        hatch = "////" if rid in {"L1-02", "L3-01"} else None
        ax.barh(y, p, color=L.LEVEL_COLOR[lvl], height=0.72, hatch=hatch, edgecolor="white" if hatch else "none",
                linewidth=0.5)
        ax.errorbar(p, y, xerr=[[p - lo], [hi - p]], fmt="none", ecolor="#333333", elinewidth=0.6, capsize=1.5,
                    capthick=0.6)
        ax.plot(100 * r["weighted_pass_rate"], y, marker="D", ms=2.6, color="black", mfc="white", mew=0.6, ls="none")
        if p < 86:
            ax.text(hi + 1.2, y, f"{p:.1f}", va="center", ha="left", fontsize=5.8, color="black")
        else:
            ax.text(p - 1.5, y, f"{p:.1f}", va="center", ha="right", fontsize=5.8, color="white")

    ax.set_yticks(ys)
    ax.set_yticklabels([f"{r['rule_id']}  {labels[r['rule_id']]}" for r in per], fontsize=6.2)
    ax.set_xlim(0, 100)
    ax.set_xlabel("判定通過率（%）")

    for boundary in (13, 19):
        ax.axhline(len(per) - boundary - 0.5, color="#bbbbbb", lw=0.5, ls=":")
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-0.8, len(per) - 0.2)

    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [Patch(color=L.C_L1, label="レベル 1"), Patch(color=L.C_L2, label="レベル 2"),
               Patch(color=L.C_L3, label="レベル 3"),
               Patch(facecolor="#dddddd", hatch="////", edgecolor="white", label="表の数・位置を測る(過分割と交絡)"),
               Line2D([], [], marker="D", ms=2.6, color="black", mfc="white", ls="none", label="遭遇率加重"),
               Line2D([], [], color="#333333", lw=0.6, label="95% CI(Wilson)")]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.42, -0.15), frameon=False, ncol=3,
              handlelength=1.4, columnspacing=1.0, borderaxespad=0.0)
    L.save(fig, "fig-rule-pass")


if __name__ == "__main__":
    main()
