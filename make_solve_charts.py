"""Charts of the 100-maze solve results (image input), two runs per model (python3 make_solve_charts.py).

    charts/solve_outcomes.png          how each model's 100 answers ended: optimal, solved but longer than optimal,
                                       crossed walls (stayed in the grid), left the grid, or no usable answer;
                                       bars are the mean of the runs
    charts/solve_accuracy_vs_cost.png  accuracy against billed cost per run of 100 mazes
    charts/solve_accuracy_vs_time.png  accuracy against seconds per maze
    charts/solve_walls_crossed.png     walls crossed by the answers that ignored a wall: median and std dev per model
    charts/describe_vs_solve.png       how well each model describes a maze against how well it solves it
    charts/solve_chart_data.csv        every plotted number (table view)
    charts/solve_walls_data.csv        the walls crossed statistics (table view)
    charts/describe_vs_solve_data.csv  the describe vs solve numbers (table view)

Inputs are results/<model>.image.run1.json and run2.json (each one pass over all 100 mazes) for the models in
SOLVE_STEMS, and results/<model>.describe.json for the description accuracy.
"""
import collections
import csv
import glob
import json
import os
import random
import statistics as st

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

import make_charts as mc
import solve

HERE = os.path.dirname(os.path.abspath(__file__))
MAZES = {m["id"]: m for m in json.load(open(os.path.join(HERE, "mazes", "mazes.json")))}

# models with two full solve runs (result file stems; the chart labels come from make_charts.LABELS)
SOLVE_STEMS = ["google_gemini-4-argon", "anthropic_claude-haiku-5.5", "anthropic_claude-sonnet-5.5", "openai_gpt-6-luna"]

# outcome categories, in bar order
CATS = [
    ("optimal", "optimal path"),
    ("solved", "reached the goal, longer than optimal"),
    ("walls", "crossed walls (partial fail)"),
    ("left", "left the maze (complete fail)"),
    ("other", "no answer, or stopped short"),
]


def categorize(rec):
    if rec["status"] in ("optimal", "solved"):
        return rec["status"]
    if not rec.get("moves"):
        return "other"
    _, note, walls = solve.grade(MAZES[rec["id"]], rec["moves"])
    if note.startswith("left the grid"):
        return "left"
    return "walls" if walls["walls_ignored"] else "other"


def walls_crossed(rec):
    """Walls the answer's path crossed (0 for a legal path or an answer with no moves)."""
    if rec["status"] in ("optimal", "solved") or not rec.get("moves"):
        return 0
    return solve.grade(MAZES[rec["id"]], rec["moves"])[2]["walls_ignored"]


def load_run(path):
    recs = json.load(open(path))
    assert len(recs) == 100 and all(r["status"] != "error" for r in recs), path
    counts = {k: 0 for k, _ in CATS}
    for r in recs:
        counts[categorize(r)] += 1
    assert sum(counts.values()) == 100
    return dict(counts=counts,
                walls=[walls_crossed(r) for r in recs],
                goal=counts["optimal"] + counts["solved"],
                optimal=counts["optimal"],
                cost=sum(r["usage"]["cost"] for r in recs),
                secs=st.mean(r["seconds"] for r in recs))


def collect():
    """[(label, [run, ...])], best model first by mean share of mazes that reached the goal."""
    data = []
    for stem in SOLVE_STEMS:
        paths = sorted(glob.glob(os.path.join(HERE, "results", stem + ".image.run*.json")))
        data.append((mc.LABELS[stem], [load_run(p) for p in paths]))
    return sorted(data, key=lambda d: -st.mean(r["goal"] for r in d[1]))


def mean_of(runs, f):
    return st.mean(f(r) for r in runs)


def chart_outcomes(data):
    fig, ax = plt.subplots(figsize=(13.5, 8.2), facecolor=mc.SURFACE)
    fig.subplots_adjust(left=0.07, right=0.975, top=0.835, bottom=0.2)
    mc.style_axes(ax, "y")
    colors = [mc.SLOTS[2], mc.SLOTS[0], mc.SLOTS[1], mc.SLOTS[6], mc.MUTED]
    n = len(CATS)
    w = 0.15
    for g, (label, runs) in enumerate(data):
        for i, (key, _) in enumerate(CATS):
            x = g + (i - (n - 1) / 2) * (w + 0.012)
            m = st.mean(r["counts"][key] for r in runs)
            ax.bar(x, m, width=w, color=colors[i], zorder=3, edgecolor=mc.SURFACE, linewidth=1.5)
            ax.text(x, m + 1.3, f"{m:g}", ha="center", va="bottom", fontsize=9.5, color=mc.SECOND, zorder=6)
    ax.set_xticks(range(len(data)))
    ax.set_xticklabels([lab for lab, _ in data], color=mc.INK, fontsize=11.5)
    ax.set_xlim(-0.55, len(data) - 0.45)
    ax.set_ylim(0, 80)
    ax.set_yticks(range(0, 81, 20))
    ax.set_yticklabels([f"{t}" for t in range(0, 81, 20)])
    ax.set_ylabel("mazes out of 100", color=mc.SECOND, fontsize=11, labelpad=10)
    fig.text(0.03, 0.955, "How each model's answers ended", fontsize=17, fontweight="bold", color=mc.INK)
    fig.text(0.03, 0.915, "Each model solved all 100 mazes twice. Bars are the mean of the two runs.\n"
             "A run's answers add up to 100. Models are in order of how often they reached the goal.",
             fontsize=10.5, color=mc.SECOND, va="top", linespacing=1.5)
    handles = [Rectangle((0, 0), 1, 1, color=c, label=lab) for c, (_, lab) in zip(colors, CATS)]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=3, frameon=False, fontsize=10.5,
              labelcolor=mc.SECOND, columnspacing=2.2, handlelength=1.6)
    fig.savefig(os.path.join(mc.OUT, "solve_outcomes.png"), dpi=130, facecolor=mc.SURFACE)
    plt.close(fig)


def chart_walls(data):
    """One dot per answer that crossed at least one wall (both runs), with the median and +/- 1 std dev per model."""
    fig, ax = plt.subplots(figsize=(11.5, 8.2), facecolor=mc.SURFACE)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.835, bottom=0.17)
    mc.style_axes(ax, "y")
    rng = random.Random(0)                    # fixed jitter so the chart is the same every time
    stats = []
    for g, (label, runs) in enumerate(data):
        answers = sum(len(r["walls"]) for r in runs)
        crossed = [w for r in runs for w in r["walls"] if w > 0]
        med, sd = st.median(crossed), st.stdev(crossed)
        stats.append(dict(label=label, answers=answers, crossed=crossed, median=med, mean=st.mean(crossed), sd=sd))
        ax.scatter([g + rng.uniform(-0.27, 0.27) for _ in crossed], crossed, s=30, color=mc.SLOTS[0], alpha=0.45,
                   edgecolor="none", zorder=3)
        lo, hi = max(med - sd, 0), med + sd                                   # whisker: median +/- 1 std dev
        ax.plot([g, g], [lo, hi], color=mc.INK, lw=1.6, zorder=5, solid_capstyle="butt")
        for v in (lo, hi):
            ax.plot([g - 0.1, g + 0.1], [v, v], color=mc.INK, lw=1.6, zorder=5, solid_capstyle="butt")
        ax.plot([g - 0.3, g + 0.3], [med, med], color=mc.SLOTS[1], lw=3.2, zorder=6, solid_capstyle="butt")   # median
    ax.set_xticks(range(len(data)))
    ax.set_xticklabels([f"{p['label']}\n{len(p['crossed'])} of {p['answers']} answers\nmedian {p['median']:g}, "
                        f"std dev {p['sd']:.1f}" for p in stats], color=mc.INK, fontsize=11)
    ax.set_xlim(-0.55, len(data) - 0.45)
    ax.set_ylim(0, 20)
    ax.set_yticks(range(0, 21, 5))
    ax.set_ylabel("walls crossed by one answer", color=mc.SECOND, fontsize=11, labelpad=10)
    fig.text(0.03, 0.955, "How many walls the answers that ignored a wall crossed", fontsize=17, fontweight="bold",
             color=mc.INK)
    fig.text(0.03, 0.915, "Each dot is one answer, over both runs, that crossed at least one wall. Answers that crossed none are not "
             "shown: they would make every median 0.\nBar: median. Line: median \u00b1 1 std dev, "
             "capped at 0. A wall crossed at move 3 and again at move 9 counts as 2.",
             fontsize=10.5, color=mc.SECOND, va="top", linespacing=1.5)
    fig.savefig(os.path.join(mc.OUT, "solve_walls_crossed.png"), dpi=130, facecolor=mc.SURFACE)
    plt.close(fig)
    with open(os.path.join(mc.OUT, "solve_walls_data.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "answers", "answers_crossing_walls", "median_walls", "mean_walls", "std_dev_walls",
                    "max_walls", "answers_by_walls_crossed"])
        for p in stats:
            by = collections.Counter(p["crossed"])
            w.writerow([p["label"], p["answers"], len(p["crossed"]), p["median"], round(p["mean"], 2),
                        round(p["sd"], 2), max(p["crossed"]), " ".join(f"{k}:{by[k]}" for k in sorted(by))])
    return stats


def frontier(points, xkey, ykey):
    """Labels not beaten on both x (lower is better) and y (higher is better) by another model."""
    return {p["label"] for p in points if not any(
        q[xkey] <= p[xkey] and q[ykey] >= p[ykey] and (q[xkey] < p[xkey] or q[ykey] > p[ykey])
        for q in points)}


def points(data):
    return [dict(label=lab, cost=mean_of(runs, lambda r: r["cost"]), secs=mean_of(runs, lambda r: r["secs"]),
                 goal=mean_of(runs, lambda r: r["goal"]), optimal=mean_of(runs, lambda r: r["optimal"]))
            for lab, runs in data]


def scatter_panel(ax, pts, xkey, ykey, xlim, ticks, ticklabels, offsets, title):
    mc.style_axes(ax, "both")
    ax.set_xscale("log")
    ax.set_xlim(*xlim)
    ax.set_ylim(30, 100)
    front = frontier(pts, xkey, ykey)
    fr = sorted((p for p in pts if p["label"] in front), key=lambda p: p[xkey])
    xs, ys = [xlim[0]], [fr[0][ykey]]       # staircase: best accuracy available at or below each x
    for p in fr:
        xs += [p[xkey], p[xkey]]
        ys += [ys[-1], p[ykey]]
    xs.append(xlim[1])
    ys.append(ys[-1])
    ax.plot(xs, ys, color=mc.FRONT, lw=2, alpha=mc.LINE_ALPHA, zorder=3, solid_joinstyle="round")
    for p in pts:
        color = mc.FRONT if p["label"] in front else mc.OTHER
        xm, ym = p[xkey], p[ykey]
        ax.scatter(xm, ym, s=150, facecolor=color, edgecolor=mc.SURFACE, linewidth=1.6, zorder=5)
        dx, dy, ha = offsets.get(p["label"], (14, 0, "left"))
        ax.annotate(p["label"], (xm, ym), xytext=(dx, dy), textcoords="offset points", ha=ha, va="center",
                    fontsize=10.5, color=mc.INK, zorder=6)
    ax.set_xticks(ticks)
    ax.set_xticklabels(ticklabels)
    ax.minorticks_off()
    ax.set_yticks(range(30, 101, 10))
    ax.set_yticklabels([f"{t}%" for t in range(30, 101, 10)])
    ax.set_title(title, loc="left", color=mc.INK, fontsize=12.5, fontweight="bold", pad=12)


def chart_scatter(data, kind):
    pts = points(data)
    fig, axes = plt.subplots(1, 2, figsize=(15, 8.0), facecolor=mc.SURFACE, sharey=True)
    fig.subplots_adjust(left=0.06, right=0.985, top=0.79, bottom=0.2, wspace=0.07)
    if kind == "cost":
        xkey, xlim, ticks = "cost", (0.17, 5.5), [0.2, 0.5, 1, 2, 5]
        ticklabels = ["$0.20", "$0.50", "$1", "$2", "$5"]
        xlabel = "billed cost for one run of 100 mazes, log scale"
        title = "Accuracy against cost"
        note = "Cost is the OpenRouter bill for all 100 answers in a run."
        fname = "solve_accuracy_vs_cost.png"
        off_goal = {"gemini-4-argon": (-14, 9, "right"), "claude-haiku-5.5": (14, 9, "left"),
                    "claude-sonnet-5.5": (-14, 0, "right"), "gpt-6-luna": (14, -2, "left")}
        off_opt = {"gemini-4-argon": (-14, 9, "right"), "claude-haiku-5.5": (14, 9, "left"),
                   "claude-sonnet-5.5": (-14, 0, "right"), "gpt-6-luna": (14, -2, "left")}
    else:
        xkey, xlim, ticks = "secs", (12, 150), [15, 20, 30, 60, 120]
        ticklabels = ["15 s", "20 s", "30 s", "1 min", "2 min"]
        xlabel = "wall-clock seconds per maze, log scale"
        title = "Accuracy against time"
        note = "Time is wall-clock seconds per request, with 8 running at once, so it reflects provider load as well as the model."

        fname = "solve_accuracy_vs_time.png"
        off_goal = {"gemini-4-argon": (14, 9, "left"), "claude-haiku-5.5": (-14, 9, "right"),
                    "claude-sonnet-5.5": (-8, -17, "left"), "gpt-6-luna": (-14, 0, "right")}
        off_opt = dict(off_goal)
    scatter_panel(axes[0], pts, xkey, "goal", xlim, ticks, ticklabels, off_goal, "reached the goal")
    scatter_panel(axes[1], pts, xkey, "optimal", xlim, ticks, ticklabels, off_opt, "found the shortest path")
    axes[1].tick_params(labelleft=False)
    for ax in axes:
        ax.set_xlabel(xlabel, color=mc.SECOND, fontsize=11, labelpad=10)
    axes[0].set_ylabel("share of the 100 mazes", color=mc.SECOND, fontsize=11, labelpad=10)
    fig.text(0.03, 0.955, title, fontsize=17, fontweight="bold", color=mc.INK)
    fig.text(0.03, 0.915, "Up and to the left is better. Each dot is the mean of two runs of all 100 mazes.\n" + note, fontsize=10.5, color=mc.SECOND, va="top", linespacing=1.5)
    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=mc.FRONT, markeredgecolor=mc.SURFACE, markersize=11,
               label="on the efficient frontier"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=mc.OTHER, markeredgecolor=mc.SURFACE, markersize=11,
               label="other models"),
        Line2D([0], [0], color=mc.FRONT, lw=2, alpha=mc.LINE_ALPHA,
               label=f"best accuracy at or below each {'cost' if kind == 'cost' else 'time'}"),
    ]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=3, frameon=False, fontsize=10.5,
               labelcolor=mc.SECOND, columnspacing=2.2)
    fig.savefig(os.path.join(mc.OUT, fname), dpi=130, facecolor=mc.SURFACE)
    plt.close(fig)


def describe_points(data):
    pts = []
    described = mc.load_models(100)
    for lab, runs in data:
        sc = [r["scores"] for r in described[lab].values()]
        assert len(sc) == 100, lab
        pts.append(dict(label=lab,
                        describe=100 * st.mean(s["edge_accuracy"] for s in sc),
                        goal=mean_of(runs, lambda r: r["goal"]),
                        optimal=mean_of(runs, lambda r: r["optimal"])))
    return pts


def chart_describe_vs_solve(data):
    pts = describe_points(data)
    fig, axes = plt.subplots(1, 2, figsize=(15, 8.0), facecolor=mc.SURFACE, sharey=True)
    fig.subplots_adjust(left=0.06, right=0.985, top=0.79, bottom=0.17, wspace=0.07)
    offsets = {"gemini-4-argon": (-14, 9, "right"), "claude-haiku-5.5": (14, 9, "left"),
               "claude-sonnet-5.5": (14, -2, "left"), "gpt-6-luna": (14, -9, "left")}
    for ax, key, title in ((axes[0], "goal", "reached the goal"), (axes[1], "optimal", "found the shortest path")):
        mc.style_axes(ax, "both")
        ax.set_xlim(95.5, 100.4)
        ax.set_ylim(30, 100)
        for p in pts:
            ax.scatter(p["describe"], p[key], s=150, facecolor=mc.FRONT, edgecolor=mc.SURFACE, linewidth=1.6, zorder=5)
            dx, dy, ha = offsets[p["label"]]
            ax.annotate(p["label"], (p["describe"], p[key]), xytext=(dx, dy), textcoords="offset points", ha=ha,
                        va="center", fontsize=10.5, color=mc.INK, zorder=6)
        ax.set_xticks(range(96, 101))
        ax.set_xticklabels([f"{t}%" for t in range(96, 101)])
        ax.set_yticks(range(30, 101, 10))
        ax.set_yticklabels([f"{t}%" for t in range(30, 101, 10)])
        ax.set_title(title, loc="left", color=mc.INK, fontsize=12.5, fontweight="bold", pad=12)
        ax.set_xlabel("description accuracy: share of wall edges reported correctly", color=mc.SECOND, fontsize=11,
                      labelpad=10)
    axes[1].tick_params(labelleft=False)
    axes[0].set_ylabel("solution accuracy: share of the 100 mazes", color=mc.SECOND, fontsize=11, labelpad=10)
    fig.text(0.03, 0.955, "Describing a maze against solving it", fontsize=17, fontweight="bold", color=mc.INK)
    fig.text(0.03, 0.915, "Up and to the right is better. Description accuracy is the share of the 180 gaps between cells a model "
             "reported correctly, averaged over all 100 mazes.\nSolution accuracy is the mean of two runs of all 100 mazes. "
             "Four models, so four dots per panel.", fontsize=10.5, color=mc.SECOND, va="top", linespacing=1.5)
    fig.savefig(os.path.join(mc.OUT, "describe_vs_solve.png"), dpi=130, facecolor=mc.SURFACE)
    plt.close(fig)
    with open(os.path.join(mc.OUT, "describe_vs_solve_data.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "describe_wall_edge_accuracy_pct", "solve_reached_goal_pct", "solve_optimal_pct"])
        for p in pts:
            w.writerow([p["label"], round(p["describe"], 2), round(p["goal"], 1), round(p["optimal"], 1)])
    return pts


def write_table(data):
    with open(os.path.join(mc.OUT, "solve_chart_data.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "run"] + [k for k, _ in CATS] + ["reached_goal", "cost_usd", "seconds_per_maze"])
        for label, runs in data:
            for i, r in enumerate(runs, 1):
                w.writerow([label, i] + [r["counts"][k] for k, _ in CATS] + [r["goal"], round(r["cost"], 4),
                                                                              round(r["secs"], 1)])


def main():
    os.makedirs(mc.OUT, exist_ok=True)
    data = collect()
    write_table(data)
    chart_outcomes(data)
    chart_walls(data)
    chart_scatter(data, "cost")
    chart_scatter(data, "time")
    for p in chart_describe_vs_solve(data):
        print(f"{p['label']:20s} describe {p['describe']:.2f}%  goal {p['goal']:.1f}%  optimal {p['optimal']:.1f}%")
    for label, runs in data:
        print(f"{label:20s}", [{k: r['counts'][k] for k, _ in CATS} for r in runs])
    print("wrote", mc.OUT)


if __name__ == "__main__":
    main()
