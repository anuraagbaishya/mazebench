"""Draw the maze generation steps for one of the real mazes in mazes/mazes.json.

The generator's random choices are replayed from the same seed (generate.py), so the figure shows the actual
order in which that maze was carved and which loop walls were accepted or rejected. The replay is checked
against the stored maze before anything is drawn.

Usage:
    python3 visualize_generation.py                 # picks a maze that shows rejected loops
    python3 visualize_generation.py --maze 7        # maze_007
    python3 visualize_generation.py --out steps.png
"""
import argparse
import os
import random

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import generate
from generate import COUNT, N, SEED, adjacency, border_cells, edge, neighbors, shortest_paths  # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
FRACTIONS = [0.0, 0.05, 0.1, 0.2, 0.35]

# validated categorical slots (blue, aqua, orange, violet) plus neutral inks
BLUE, AQUA, ORANGE, VIOLET = "#2a78d6", "#1baf7a", "#eb6834", "#4a3aa7"
INK, SECOND, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"


def replay(index):
    """Re-run generation up to maze `index` (0-based) and record every step of that maze."""
    rng = random.Random(SEED)
    sides = ["N", "S", "W", "E"] * (COUNT // 4)
    rng.shuffle(sides)
    for i in range(index + 1):
        frac = rng.choice(FRACTIONS)
        if i < index:
            generate.make_maze(rng, sides[i], frac)
            continue
        side = sides[i]
        k = rng.randrange(N)
        start = {"N": (0, k), "S": (N - 1, k), "W": (k, 0), "E": (k, N - 1)}[side]
        goal = start
        while goal == start:
            goal = (rng.randrange(N), rng.randrange(N))
        # random depth-first carving, recording the order (same rng calls as generate.spanning_tree)
        first = (rng.randrange(N), rng.randrange(N))
        seen, stack, carved = {first}, [first], []
        while stack:
            cur = stack[-1]
            nxt = [n for n in neighbors(cur) if n not in seen]
            if not nxt:
                stack.pop()
                continue
            n = rng.choice(nxt)
            seen.add(n)
            carved.append((edge(cur, n), n))
            stack.append(n)
        open_edges = {e for e, _ in carved}
        all_edges = {edge((r, c), n) for r in range(N) for c in range(N) for n in neighbors((r, c))}
        walls = list(all_edges - open_edges)
        rng.shuffle(walls)
        target = int(len(walls) * frac)
        adj = adjacency(open_edges)
        events, added = [], 0
        for a, b in walls:
            if added >= target:
                break
            adj[a].append(b)
            adj[b].append(a)
            n_paths = shortest_paths(adj, start, goal)[1]
            if n_paths == 1:
                open_edges.add((a, b))
                events.append(((a, b), True))
                added += 1
            else:
                adj[a].remove(b)
                adj[b].remove(a)
                events.append(((a, b), False))
        dist, n_paths, path = shortest_paths(adj, start, goal)
        assert n_paths == 1
        return dict(side=side, start=start, goal=goal, first=first, carved=carved, events=events,
                    open_edges=open_edges, path=path, target=target, frac=frac)


def center(cell):
    return cell[1] + 0.5, cell[0] + 0.5


def draw_walls(ax, open_edges, side, start, color=INK, lw=2.4):
    for r in range(N):
        for c in range(N):
            if c + 1 < N and edge((r, c), (r, c + 1)) not in open_edges:
                ax.plot([c + 1, c + 1], [r, r + 1], color=color, lw=lw, solid_capstyle="round", zorder=3)
            if r + 1 < N and edge((r, c), (r + 1, c)) not in open_edges:
                ax.plot([c, c + 1], [r + 1, r + 1], color=color, lw=lw, solid_capstyle="round", zorder=3)
    r0, c0 = start
    for i in range(N):  # outer border, with the entry gap next to the start cell
        for sd, seg in (("N", ([i, i + 1], [0, 0])), ("S", ([i, i + 1], [N, N])),
                        ("W", ([0, 0], [i, i + 1])), ("E", ([N, N], [i, i + 1]))):
            if sd == side and ((sd in "NS" and i == c0) or (sd in "WE" and i == r0)):
                continue
            ax.plot(*seg, color=color, lw=lw, solid_capstyle="round", zorder=3)


def base_axes(ax, title, caption):
    ax.set_xlim(-0.4, N + 0.4)
    ax.set_ylim(N + 0.4, -0.4)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=22)
    ax.text(-0.4, -0.95, caption, fontsize=9.5, color=SECOND, va="center", ha="left")
    for i in range(N + 1):  # hairline cell grid
        ax.plot([i, i], [0, N], color=GRID, lw=0.8, zorder=1)
        ax.plot([0, N], [i, i], color=GRID, lw=0.8, zorder=1)


def mark_ends(ax, start, goal):
    sx, sy = center(start)
    gx, gy = center(goal)
    ax.scatter([sx], [sy], s=260, marker="o", facecolor="white", edgecolor=INK, linewidth=2, zorder=8)
    ax.text(sx, sy, "S", ha="center", va="center", fontsize=9, fontweight="bold", color=INK, zorder=9)
    ax.scatter([gx], [gy], s=260, marker="s", facecolor=INK, edgecolor=INK, zorder=8)
    ax.text(gx, gy, "G", ha="center", va="center", fontsize=9, fontweight="bold", color="white", zorder=9)


def passages(ax, edges, color, lw=3.2, zorder=5):
    for a, b in edges:
        (x1, y1), (x2, y2) = center(a), center(b)
        ax.plot([x1, x2], [y1, y2], color=color, lw=lw, solid_capstyle="round", zorder=zorder)


def figure(info, index, out):
    carved, events = info["carved"], info["events"]
    tree = {e for e, _ in carved}
    fig, axes = plt.subplots(2, 3, figsize=(17, 12.4), facecolor=SURFACE)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.84, bottom=0.09, wspace=0.07, hspace=0.30)
    fig.suptitle(f"How maze_{index + 1:03d} was generated", x=0.03, y=0.985, ha="left", va="top", fontsize=18,
                 fontweight="bold", color=INK)
    fig.text(0.03, 0.945, "A 10x10 grid is carved into a maze, then loops are added without ever creating a tie for the "
             "shortest route.\nPanels replay this maze's real random choices.", fontsize=11, linespacing=1.5, va="top",
             color=SECOND, ha="left")
    side, start, goal = info["side"], info["start"], info["goal"]

    def stage(ax, k, title, caption):
        base_axes(ax, title, caption)
        edges = {e for e, _ in carved[:k]}
        visited = {info["first"]} | {n for _, n in carved[:k]}
        for (r, c) in visited:  # shade cells the walk has reached
            ax.add_patch(plt.Rectangle((c, r), 1, 1, facecolor=BLUE, alpha=0.10, lw=0, zorder=2))
        draw_walls(ax, edges, side, start)
        passages(ax, edges, BLUE)
        for cell in visited:
            ax.scatter(*center(cell), s=16, color=BLUE, zorder=6)
        mark_ends(ax, start, goal)
        return edges, visited

    # 1: every wall present
    ax = axes[0, 0]
    base_axes(ax, "1  Start with every wall", "100 cells, 180 walls between neighbours, no passages.")
    draw_walls(ax, set(), side, start)
    mark_ends(ax, start, goal)
    fx, fy = center(info["first"])
    ax.scatter([fx], [fy], s=130, marker="D", facecolor=BLUE, edgecolor="white", linewidth=1.5, zorder=7)
    ax.annotate("random start\nof the carving", xy=(fx, fy), xytext=(fx + 1.6, fy - 2.4), fontsize=9,
                color=BLUE, ha="left", arrowprops=dict(arrowstyle="-", color=BLUE, lw=1), zorder=10)

    # 2, 3: random depth-first carving, part way through
    for ax, k, n in ((axes[0, 1], 25, 2), (axes[0, 2], 65, 3)):
        stage(ax, k, f"{n}  Carve a random walk, {k} passages in",
              "Step to a random unvisited neighbour and open the wall." if n == 2 else
              "At a dead end, back up. Shaded cells have been reached.")
        head = carved[k - 1][1]
        ax.scatter(*center(head), s=190, marker="D", facecolor=INK, edgecolor="white", linewidth=1.6, zorder=10)

    # 4: complete spanning tree
    ax = axes[1, 0]
    stage(ax, len(carved), "4  Every cell reached: a perfect maze",
          f"{len(carved)} passages, no loops: one route between any two cells.")
    # 5: loops
    ax = axes[1, 1]
    acc = [e for e, ok in events if ok]
    rej = [e for e, ok in events if not ok]
    base_axes(ax, "5  Knock out extra walls to make loops",
              f"Target {info['target']} loops: kept {len(acc)} of {len(events)} tried; "
              f"{len(rej)} rejected as ties.")
    draw_walls(ax, info["open_edges"], side, start)
    passages(ax, tree, BLUE, lw=2.2, zorder=4)
    passages(ax, acc, AQUA, lw=4.2, zorder=6)
    for a, b in rej:  # rejected walls: orange cross on the wall that was put back
        (x1, y1), (x2, y2) = center(a), center(b)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ax.scatter([mx], [my], s=210, marker="X", facecolor=ORANGE, edgecolor="white", linewidth=1.2, zorder=9)
    mark_ends(ax, start, goal)

    # 6: final maze + unique shortest path
    ax = axes[1, 2]
    path = info["path"]
    base_axes(ax, "6  Final maze: one shortest route",
              f"Shortest route: {len(path) - 1} moves. {len(acc)} loops add longer detours.")
    draw_walls(ax, info["open_edges"], side, start)
    xs, ys = zip(*[center(c) for c in path])
    ax.plot(xs, ys, color=VIOLET, lw=4.5, solid_capstyle="round", solid_joinstyle="round", zorder=5)
    mark_ends(ax, start, goal)

    handles = [
        Line2D([0], [0], color=BLUE, lw=3.2, label="passage carved in steps 2 to 4"),
        Line2D([0], [0], marker="D", color="none", markerfacecolor=INK, markeredgecolor="white",
               markersize=10, label="current cell of the walk"),
        Line2D([0], [0], color=AQUA, lw=4.2, label="loop passage kept (step 5)"),
        Line2D([0], [0], marker="X", color="none", markerfacecolor=ORANGE, markeredgecolor="white",
               markersize=12, label="wall put back (would tie the shortest route)"),
        Line2D([0], [0], color=VIOLET, lw=4.5, label="the unique shortest route"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="white", markeredgecolor=INK,
               markeredgewidth=2, markersize=11, label="S start"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor=INK, markersize=10, label="G goal"),
    ]
    leg = fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.03, 0.005), ncol=4, frameon=False,
                     fontsize=10, labelcolor=SECOND, columnspacing=2.2, handlelength=2.2)
    fig.savefig(out, dpi=140, facecolor=SURFACE)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maze", type=int, help="maze number 1-100 (default: first maze that shows rejected loops)")
    ap.add_argument("--out", default=os.path.join(HERE, "generation_steps.png"))
    args = ap.parse_args()
    import json
    stored = json.load(open(os.path.join(HERE, "mazes", "mazes.json")))
    if args.maze:
        index = args.maze - 1
    else:  # pick a maze where loops were both accepted and rejected, so step 5 shows the tie check
        index = next(i for i in range(COUNT) if (lambda t: t["target"] >= 16 and
                     sum(not ok for _, ok in t["events"]) >= 2)(replay(i)))
    info = replay(index)
    mz = stored[index]
    # the replay must reproduce the stored maze exactly
    mine = sorted([list(map(list, e)) for e in info["open_edges"]])
    assert mine == mz["open_edges"], "replay does not match mazes.json"
    assert [list(c) for c in info["path"]] == mz["optimal_path"]
    figure(info, index, args.out)
    print(f"maze_{index + 1:03d}: replay matches mazes.json; wrote {args.out}")


if __name__ == "__main__":
    main()
