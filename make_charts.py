"""Charts of the description results (python3 make_charts.py; no arguments).

Two sets of charts are written to charts/:

    20 mazes   every model that described the first 20 mazes (experiments.md, step 2)
    100 mazes  the five models that described all 100 mazes, with a _100 suffix on the file name (step 3)

    start_goal_accuracy[_100].png      start and goal cell accuracy per model
    precision_recall_stddev[_100].png  wall recall and precision per model, with spread across mazes
    per_maze_accuracy.png              wall edge accuracy per maze, one dot per model (20 mazes only)
    accuracy_vs_cost[_100].png         accuracy against cost per maze, dot size = output tokens per maze
    accuracy_vs_time[_100].png         accuracy against seconds per maze, dot size = output tokens per maze
    chart_data[_100].csv               every plotted number for the first charts (table view)
    cost_chart_data[_100].csv          every plotted number for the cost and time charts

Inputs are results/<model>.describe.json. MiniMax M3.1 Flash ran on the free tier, so it has no cost and is only
in the time chart. make_solve_charts.py reuses the constants and helpers defined here.
"""
import csv
import glob
import json
import os
import statistics as st

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "charts")

# result file stem -> label used in the charts
LABELS = {
    "google_gemini-4-argon": "gemini-4-argon",
    "anthropic_claude-sonnet-5.5": "claude-sonnet-5.5",
    "openai_gpt-6-luna": "gpt-6-luna",
    "anthropic_claude-haiku-5.5": "claude-haiku-5.5",
    "qwen_qwen3.8-max-0902": "qwen3.8-max-0902",
    "google_gemini-3.8-flash": "gemini-3.8-flash",
    "minimax_minimax-m3.1-flash-free": "minimax-m3.1-flash",
    "meta_muse-spark-1.3": "muse-spark-1.3",
    "z-ai_glm-5.3-flash.effort-low": "glm-5.3-flash (low effort)",
    "mistralai_mistral-large-4-0": "mistral-large-4-0",
    "deepseek_deepseek-v4.1-flash": "deepseek-v4.1-flash",
    "nvidia_nemotron-3.5-super-vl": "nemotron-3.5-super-vl",
    "xiaomi_mimo-v2.6-pro": "mimo-v2.6-pro",
}

# colours (dark surface; the hues were checked with the palette validator)
SLOTS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
SURFACE, INK, SECOND, MUTED, GRID = "#1a1a19", "#ffffff", "#c3c2b7", "#898781", "#2c2c2a"
OTHER, SIZE_DOT, LINE_ALPHA = "#6b7b8f", "#8a8983", 0.95
FRONT = SLOTS[0]
C_START, C_GOAL = SLOTS[0], SLOTS[1]        # start and goal chart series
C_RECALL, C_PREC = SLOTS[6], SLOTS[1]       # recall and precision chart series

STYLES = {  # (colour slot, marker): fixed per model so a model keeps its colour in every chart
    "gemini-4-argon": (0, "o"), "claude-sonnet-5.5": (1, "o"), "gpt-6-luna": (2, "o"), "claude-haiku-5.5": (3, "o"),
    "qwen3.8-max-0902": (4, "o"), "gemini-3.8-flash": (5, "o"), "muse-spark-1.3": (6, "o"),
    "glm-5.3-flash (low effort)": (7, "o"), "mistral-large-4-0": (0, "D"), "deepseek-v4.1-flash": (1, "D"),
    "nemotron-3.5-super-vl": (2, "D"), "mimo-v2.6-pro": (3, "D"), "minimax-m3.1-flash": (4, "D"),
}

# label offsets in points: (dx, dy, horizontal alignment); keeps neighbouring labels apart. ("lead", x, y) parks the
# label at data coordinates and joins it to its dot with a thin line.
LABEL_COST = {
    "gemini-4-argon": (12, 11, "left"), "claude-sonnet-5.5": (14, -5, "left"), "gpt-6-luna": (-11, 7, "right"),
    "claude-haiku-5.5": (-11, -9, "right"), "glm-5.3-flash (low effort)": (13, 0, "left"),
    "nemotron-3.5-super-vl": (-13, 0, "right"), "mimo-v2.6-pro": (13, 0, "left"),
    "deepseek-v4.1-flash": (0, -22, "center"), "mistral-large-4-0": (16, 8, "left"),
    "qwen3.8-max-0902": (14, 0, "left"), "gemini-3.8-flash": (16, 0, "left"), "muse-spark-1.3": (16, 0, "left"),
}
LABEL_TIME = {
    "gemini-4-argon": (12, 11, "left"), "claude-sonnet-5.5": ("lead", 70, 101.2), "gpt-6-luna": (12, -3, "left"),
    "claude-haiku-5.5": (10, -11, "left"), "glm-5.3-flash (low effort)": (13, 0, "left"),
    "nemotron-3.5-super-vl": (-13, 0, "right"), "mimo-v2.6-pro": (13, 0, "left"),
    "deepseek-v4.1-flash": (0, -22, "center"), "mistral-large-4-0": (-16, 9, "right"),
    "qwen3.8-max-0902": (14, 0, "left"), "gemini-3.8-flash": (16, 0, "left"), "muse-spark-1.3": (16, 0, "left"),
    "minimax-m3.1-flash": (16, 0, "left"),
}

# what differs between the two sets of charts
SETS = [
    dict(n=20, suffix="", words="the first 20 mazes", per_maze=True,
         start_goal_note="Mistral has 19 scored mazes.",
         cost_note="MiniMax M3.1 Flash is not shown: it ran on the free tier, so it cost $0.",
         time_note=("Time is wall-clock seconds per request, with 4 to 5 requests running at once through "
                    "whichever provider OpenRouter chose,\nso it reflects load as well as the model."),
         label_cost={}, label_time={}),
    dict(n=100, suffix="_100", words="all 100 mazes", per_maze=False,
         start_goal_note="",
         cost_note="Cost is the OpenRouter bill for the description request.",
         time_note=("Time is wall-clock seconds per request, with several requests running at once through "
                    "whichever provider OpenRouter chose,\nso it reflects load as well as the model."),
         # with only five models the labels can sit close to their dots; Luna and Haiku cost about the same
         label_cost={"gpt-6-luna": (13, 10, "left"), "claude-haiku-5.5": (-13, -10, "right")},
         label_time={"claude-sonnet-5.5": (13, -9, "left")}),
]


def model_style(label):
    slot, marker = STYLES[label]
    return SLOTS[slot], marker


def load_models(n):
    """label -> {maze number: graded record} for every model that described all of mazes 1..n.

    Records that are not graded (API errors) are skipped, so a model can score fewer than n mazes; a model is
    included when its file covers all n mazes, with errors counted (the 20-maze set has one such case, Mistral).
    """
    models = {}
    for path in sorted(glob.glob(os.path.join(HERE, "results", "*.describe.json"))):
        stem = os.path.basename(path)[: -len(".describe.json")]
        if stem not in LABELS:
            continue
        recs = json.load(open(path))
        per = {int(r["id"].split("_")[1]): r for r in recs
               if r["status"] == "graded" and r.get("scores") and int(r["id"].split("_")[1]) <= n}
        covered = {int(r["id"].split("_")[1]) for r in recs if int(r["id"].split("_")[1]) <= n}
        if len(covered) == n:
            models[LABELS[stem]] = per
    return models


def collect(n):
    """[(label, {maze: scores})], best model first by mean wall edge accuracy."""
    data = [(label, {m: r["scores"] for m, r in per.items()}) for label, per in load_models(n).items()]
    return sorted(data, key=lambda d: -st.mean(s["edge_accuracy"] for s in d[1].values()))


def out_path(name, sc):
    """Output file for a chart or table; the 100-maze set adds a suffix so its files sit beside the 20-maze ones."""
    stem, ext = os.path.splitext(name)
    return os.path.join(OUT, stem + sc["suffix"] + ext)


def style_axes(ax, grid_axis):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=MUTED, length=0, labelsize=10)
    ax.grid(axis=grid_axis, color=GRID, lw=1, zorder=0)
    ax.set_axisbelow(True)


def chart_start_goal(data, sc):
    fig, ax = plt.subplots(figsize=(11.5, 8.2), facecolor=SURFACE)
    fig.subplots_adjust(left=0.27, right=0.96, top=0.86, bottom=0.12)
    style_axes(ax, "x")
    n = len(data)
    h = 0.30
    for i, (label, per) in enumerate(data):
        y = n - 1 - i
        mazes = len(per)
        for off, key, color in ((-0.17, "start_ok", C_START), (0.17, "goal_ok", C_GOAL)):
            ok = sum(1 for s in per.values() if s[key])
            pct = 100 * ok / mazes
            ax.barh(y + off * -1, pct, height=h, color=color, zorder=3, edgecolor=SURFACE, linewidth=1.5)
            ax.text(pct + 1.2, y + off * -1, f"{ok}/{mazes}", va="center", ha="left", fontsize=9.5, color=SECOND)
    ax.set_yticks(range(n))
    ax.set_yticklabels([f"{lab}" for lab, _ in reversed(data)], color=INK, fontsize=10.5)
    ax.set_xlim(0, 112)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xticklabels([f"{t}%" for t in range(0, 101, 20)])
    ax.set_ylim(-0.7, n - 0.3)
    fig.text(0.03, 0.955, "Can models find the start and goal cell?", fontsize=17, fontweight="bold", color=INK)
    fig.text(0.03, 0.915, f"Share of {sc['words']} where the model named the green (start) and red (goal) cell "
             "exactly right.\nModels are in order of wall edge accuracy."
             + (" " + sc["start_goal_note"] if sc["start_goal_note"] else ""),
             fontsize=10.5, color=SECOND, va="top", linespacing=1.5)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, color=C_START), Rectangle((0, 0), 1, 1, color=C_GOAL)],
              labels=["start cell correct", "goal cell correct"], loc="lower center", bbox_to_anchor=(0.5, -0.12),
              ncol=2, frameon=False, fontsize=10.5, labelcolor=SECOND)
    fig.savefig(out_path("start_goal_accuracy.png", sc), dpi=140, facecolor=SURFACE)
    plt.close(fig)


def chart_precision_recall(data, sc):
    fig, ax = plt.subplots(figsize=(15, 9.4), facecolor=SURFACE)
    fig.subplots_adjust(left=0.215, right=0.975, top=0.835, bottom=0.14)
    style_axes(ax, "x")
    n = len(data)
    h = 0.27
    for i, (label, per) in enumerate(data):
        for off, key, color in ((-0.17, "wall_recall", C_RECALL), (0.17, "wall_precision", C_PREC)):
            vals = [100 * s[key] for s in per.values() if s[key] is not None]
            m, sd = st.mean(vals), st.stdev(vals)
            lo, hi = min(vals), max(vals)
            y = i + off
            ax.plot([lo, hi], [y, y], color=color, lw=1.6, zorder=3, solid_capstyle="butt")          # wick: min to max
            left, right = max(m - sd, 0), min(m + sd, 100)
            ax.add_patch(Rectangle((left, y - h / 2), max(right - left, 0.5), h, facecolor=color, alpha=0.30,
                                   edgecolor=color, linewidth=1.4, zorder=4))                      # body: mean +/- 1 sd
            ax.plot([m, m], [y - h / 2, y + h / 2], color=color, lw=2.8, zorder=5, solid_capstyle="butt")  # mean
    ax.set_ylim(n - 0.4, -0.6)
    ax.set_xlim(0, 104)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xticklabels([f"{t}%" for t in range(0, 101, 20)])
    ax.set_yticks(range(n))
    ax.set_yticklabels([lab + (f"  (n={len(per)})" if len(per) != sc["n"] else "") for lab, per in data],
                       color=INK, fontsize=10.5)
    fig.text(0.03, 0.955, "Wall recall and precision per model", fontsize=17, fontweight="bold", color=INK)
    fig.text(0.03, 0.915, "Recall: share of real walls the model reported. Precision: share of reported walls that are "
             f"real. Spread is across the {sc['n']} mazes.\nModels are in order of wall edge accuracy.",
             fontsize=10.5, color=SECOND, va="top", linespacing=1.5)
    key = [
        Line2D([0], [0], color=C_RECALL, lw=6, alpha=0.9, label="recall"),
        Line2D([0], [0], color=C_PREC, lw=6, alpha=0.9, label="precision"),
        Rectangle((0, 0), 1, 1, facecolor=INK, alpha=0.25, edgecolor=INK, label="box: mean ± 1 std dev (capped at 100%)"),
        Line2D([0], [0], color=INK, lw=2.8, label="bar: mean"),
        Line2D([0], [0], color=INK, lw=1.6, label="line: lowest to highest maze"),
    ]
    ax.legend(handles=key, loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=5, frameon=False, fontsize=10.5,
              labelcolor=SECOND, handlelength=2.2, columnspacing=2.2)
    fig.savefig(out_path("precision_recall_stddev.png", sc), dpi=130, facecolor=SURFACE)
    plt.close(fig)


def chart_per_maze(data, sc):
    n = len(data)
    n_mazes = sc["n"]
    fig, ax = plt.subplots(figsize=(15, 13), facecolor=SURFACE)
    fig.subplots_adjust(left=0.07, right=0.975, top=0.915, bottom=0.145)
    style_axes(ax, "x")
    span = 0.84                              # dots in a row are spread top to bottom in legend order
    step = span / (n - 1)
    for m in range(1, n_mazes):              # faint divider between maze rows
        ax.axhline(m + 0.5, color=GRID, lw=0.6, zorder=1)
    for i, (label, per) in enumerate(data):
        color, marker = model_style(label)
        mazes = sorted(per)
        ax.scatter([100 * per[m]["edge_accuracy"] for m in mazes], [m - span / 2 + i * step for m in mazes],
                   s=46, color=color, marker=marker, edgecolor=SURFACE, linewidth=0.9, zorder=4)
    base = st.mean(100 * (1 - s["wall_share"]) for _, per in data for s in per.values())
    ax.axvline(base, color=MUTED, lw=1, zorder=2)
    ax.set_ylim(n_mazes + 0.5, 0.5)
    ax.set_xlim(36, 102)
    ax.set_xticks(range(40, 101, 10))
    ax.set_xticklabels([f"{t}%" for t in range(40, 101, 10)])
    ax.set_yticks(range(1, n_mazes + 1))
    ax.set_yticklabels([f"maze {m:03d}" for m in range(1, n_mazes + 1)], color=INK, fontsize=10.5)
    ax.set_xlabel("wall edge accuracy on that maze", color=SECOND, fontsize=11, labelpad=10)
    fig.text(0.02, 0.972, "Wall edge accuracy on each of the first 20 mazes", fontsize=17, fontweight="bold",
             color=INK)
    fig.text(0.02, 0.945, "One dot per model per maze: the share of the 180 gaps between cells reported correctly. "
             "Within a maze, dots run top to bottom in the order of the legend.\nMistral has no dot for maze 007 "
             "(a connection error).", fontsize=10.5, color=SECOND, va="top", linespacing=1.5)
    handles = [Line2D([0], [0], marker=model_style(lab)[1], color="none", markerfacecolor=model_style(lab)[0],
                      markeredgecolor=SURFACE, markersize=9, label=lab) for lab, _ in data]
    handles.append(Line2D([0], [0], color=MUTED, lw=1.2, label=f"reporting no walls at all: {base:.0f}%"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=4, frameon=False, fontsize=10.5,
              labelcolor=SECOND, columnspacing=1.8, handletextpad=0.4)
    fig.savefig(out_path("per_maze_accuracy.png", sc), dpi=100, facecolor=SURFACE)
    plt.close(fig)


def cost_points(n):
    pts = []
    for label, per in load_models(n).items():
        recs = [r for r in per.values() if r.get("usage")]
        pts.append(dict(label=label, n=len(recs),
                        acc=100 * st.mean(r["scores"]["edge_accuracy"] for r in recs),
                        cost=st.mean(r["usage"].get("cost", 0) for r in recs),
                        tokens=st.mean(r["usage"]["completion_tokens"] for r in recs),
                        secs=st.mean(r["seconds"] for r in recs)))

    def frontier(candidates, key):
        """Not beaten on both accuracy and `key` (lower is better) by any other candidate."""
        return {p["label"] for p in candidates if not any(
            q[key] <= p[key] and q["acc"] >= p["acc"] and (q[key] < p[key] or q["acc"] > p["acc"])
            for q in candidates)}

    on_cost = frontier([p for p in pts if p["cost"] > 0], "cost")      # free tier has no point on a log cost axis
    on_time = frontier(pts, "secs")
    for p in pts:
        p["front_cost"] = p["label"] in on_cost
        p["front_time"] = p["label"] in on_time
    return pts


def dot_area(tokens):
    return 30 + 0.012 * tokens          # area grows with tokens, with a floor so the smallest dot stays visible


def scatter_panel(ax, pts, xkey, frontier_key, offsets, xlim, ticks, ticklabels, xlabel, base, base_x):
    style_axes(ax, "both")
    ax.set_xscale("log")
    ax.set_xlim(*xlim)
    ax.set_ylim(48, 103)
    ax.axhline(base, color=MUTED, lw=1, zorder=2)
    ax.text(base_x, base + 0.7, f"reporting no walls at all: {base:.0f}%", color=SECOND, fontsize=10, va="bottom")
    pts = [p for p in pts if p[xkey] > 0]
    fr = sorted((p for p in pts if p[frontier_key]), key=lambda p: p[xkey])
    xs, ys = [xlim[0]], [fr[0]["acc"]]       # staircase: best accuracy available at or below each x
    for p in fr:
        xs += [p[xkey], p[xkey]]
        ys += [ys[-1], p["acc"]]
    xs.append(xlim[1])
    ys.append(ys[-1])
    ax.plot(xs, ys, color=FRONT, lw=2, alpha=LINE_ALPHA, zorder=3, solid_joinstyle="round")
    for p in sorted(pts, key=lambda p: -p["tokens"]):      # big dots first so small ones stay visible
        ax.scatter(p[xkey], p["acc"], s=dot_area(p["tokens"]), facecolor=FRONT if p[frontier_key] else OTHER,
                   edgecolor=SURFACE, linewidth=1.4, zorder=5)
        off = offsets.get(p["label"], (14, 0, "left"))
        if off[0] == "lead":     # label parked in free space and joined to its dot by a thin leader line
            ax.annotate(p["label"], (p[xkey], p["acc"]), xytext=(off[1], off[2]), textcoords="data", ha="left",
                        va="center", fontsize=10.5, color=INK, zorder=6,
                        arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.9, shrinkA=2, shrinkB=4))
        else:
            ax.annotate(p["label"], (p[xkey], p["acc"]), xytext=(off[0], off[1]), textcoords="offset points",
                        ha=off[2], va="center", fontsize=10.5, color=INK, zorder=6)
    ax.set_xticks(ticks)
    ax.set_xticklabels(ticklabels)
    ax.minorticks_off()
    ax.set_xlabel(xlabel, color=SECOND, fontsize=11, labelpad=10)


def _legends(ax, panel_word):
    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=FRONT, markeredgecolor=SURFACE, markersize=11,
               label="on the efficient frontier"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=OTHER, markeredgecolor=SURFACE, markersize=11,
               label="other models"),
        Line2D([0], [0], color=FRONT, lw=2, alpha=LINE_ALPHA, label=f"best accuracy at or below each {panel_word}"),
    ]
    leg1 = ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.32, -0.115), ncol=2, frameon=False,
                     fontsize=10.5, labelcolor=SECOND, columnspacing=2.2)
    ax.add_artist(leg1)
    sizes = [Line2D([0], [0], marker="o", color="none", markerfacecolor=SIZE_DOT, markeredgecolor=SURFACE,
                    markersize=dot_area(t) ** 0.5, label=lab)
             for t, lab in ((1000, "1k"), (10000, "10k"), (30000, "30k"), (70000, "70k"))]
    ax.legend(handles=sizes, title="output tokens per maze", loc="upper center", bbox_to_anchor=(0.82, -0.095),
              ncol=4, frameon=False, fontsize=10.5, labelcolor=SECOND, title_fontsize=10.5, columnspacing=2.2,
              handletextpad=1.1, handlelength=2.6, labelspacing=1.2).get_title().set_color(SECOND)


def _single_scatter(pts, data, sc, kind):
    fig, ax = plt.subplots(figsize=(14, 9.2), facecolor=SURFACE)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.82, bottom=0.215)
    base = st.mean(100 * (1 - s["wall_share"]) for _, per in data for s in per.values())
    if kind == "cost":
        scatter_panel(ax, pts, "cost", "front_cost", {**LABEL_COST, **sc["label_cost"]}, (0.0012, 1.6),
                      [0.001, 0.01, 0.1, 1], ["$0.001", "$0.01", "$0.10", "$1.00"],
                      "billed cost per maze, log scale (multiply by 100 for the full 100 mazes)", base, 0.00125)
        title = "Accuracy against cost: what each model costs for the accuracy it gets"
        note = sc["cost_note"]
        word, fname = "cost", "accuracy_vs_cost.png"
    else:
        scatter_panel(ax, pts, "secs", "front_time", {**LABEL_TIME, **sc["label_time"]}, (5, 1800),
                      [10, 30, 60, 180, 600, 1800], ["10 s", "30 s", "1 min", "3 min", "10 min", "30 min"],
                      "wall-clock time per maze, log scale", base, 5.3)
        title = "Accuracy against time: how long each model takes for the accuracy it gets"
        note = sc["time_note"]
        word, fname = "time", "accuracy_vs_time.png"
    ax.set_ylabel("wall edge accuracy", color=SECOND, fontsize=11, labelpad=10)
    ax.set_yticks(range(50, 101, 10))
    ax.set_yticklabels([f"{t}%" for t in range(50, 101, 10)])
    fig.text(0.03, 0.955, title, fontsize=17, fontweight="bold", color=INK)
    fig.text(0.03, 0.915, "Up and to the left is better. Dot area shows output tokens written per maze. "
             f"Averages over {sc['words']}.\n" + note,
             fontsize=10.5, color=SECOND, va="top", linespacing=1.5)
    _legends(ax, word)
    fig.savefig(out_path(fname, sc), dpi=130, facecolor=SURFACE)
    plt.close(fig)


def write_tables(data, pts, sc):
    with open(out_path("chart_data.csv", sc), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "maze", "start_correct", "goal_correct", "wall_edge_accuracy_pct",
                    "wall_recall_pct", "wall_precision_pct"])
        for label, per in data:
            for maze, s in sorted(per.items()):
                w.writerow([label, f"maze_{maze:03d}", int(s["start_ok"]), int(s["goal_ok"]),
                            round(100 * s["edge_accuracy"], 2),
                            "" if s["wall_recall"] is None else round(100 * s["wall_recall"], 2),
                            "" if s["wall_precision"] is None else round(100 * s["wall_precision"], 2)])
    with open(out_path("cost_chart_data.csv", sc), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "mazes", "wall_edge_accuracy_pct", "billed_cost_per_maze_usd",
                    "output_tokens_per_maze", "seconds_per_maze", "on_cost_frontier", "on_time_frontier"])
        for p in sorted(pts, key=lambda p: p["secs"]):
            w.writerow([p["label"], p["n"], round(p["acc"], 2), round(p["cost"], 5), round(p["tokens"]),
                        round(p["secs"], 1), int(p["front_cost"]), int(p["front_time"])])


def main():
    os.makedirs(OUT, exist_ok=True)
    for sc in SETS:
        data = collect(sc["n"])
        pts = cost_points(sc["n"])
        write_tables(data, pts, sc)
        chart_start_goal(data, sc)
        chart_precision_recall(data, sc)
        if sc["per_maze"]:
            chart_per_maze(data, sc)
        _single_scatter(pts, data, sc, "cost")
        _single_scatter(pts, data, sc, "time")
        print(f"{sc['n']} mazes:", ", ".join(f"{label} ({len(per)})" for label, per in data))
        print("  cost frontier:", [p["label"] for p in pts if p["front_cost"]],
              "| time frontier:", [p["label"] for p in pts if p["front_time"]])


if __name__ == "__main__":
    main()
