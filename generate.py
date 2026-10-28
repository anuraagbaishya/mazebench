"""Generate 100 10x10 mazes, each with a unique shortest start->goal path.

Each maze starts as a perfect maze (spanning tree), then extra walls are
removed at random to create loops (alternate, longer routes) as long as the
shortest path from start to goal stays unique.

Outputs: mazes/maze_XXX.png and mazes/mazes.json (layout, start, goal, solution).
"""
import json
import os
import random
from collections import deque

from PIL import Image, ImageDraw

N = 10
COUNT = 100
CELL = 56
MARGIN = 40
SEED = 20261017
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mazes")

DIRS = {"N": (-1, 0), "S": (1, 0), "W": (0, -1), "E": (0, 1)}


def edge(a, b):
    return (a, b) if a < b else (b, a)


def neighbors(c):
    r, k = c
    for dr, dc in DIRS.values():
        nr, nc = r + dr, k + dc
        if 0 <= nr < N and 0 <= nc < N:
            yield (nr, nc)


def spanning_tree(rng):
    start = (rng.randrange(N), rng.randrange(N))
    seen = {start}
    stack = [start]
    open_edges = set()
    while stack:
        cur = stack[-1]
        nxt = [n for n in neighbors(cur) if n not in seen]
        if not nxt:
            stack.pop()
            continue
        n = rng.choice(nxt)
        seen.add(n)
        open_edges.add(edge(cur, n))
        stack.append(n)
    return open_edges


def adjacency(open_edges):
    adj = {(r, c): [] for r in range(N) for c in range(N)}
    for a, b in open_edges:
        adj[a].append(b)
        adj[b].append(a)
    return adj


def shortest_paths(adj, s, g):
    """Return (distance, number of shortest paths, one shortest path)."""
    dist = {s: 0}
    cnt = {s: 1}
    parent = {s: None}
    q = deque([s])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in dist:
                dist[v] = dist[u] + 1
                cnt[v] = cnt[u]
                parent[v] = u
                q.append(v)
            elif dist[v] == dist[u] + 1:
                cnt[v] += cnt[u]
    path = []
    cur = g
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    return dist[g], cnt[g], path[::-1]


def border_cells():
    cells = []
    for i in range(N):
        cells += [((0, i), "N"), ((N - 1, i), "S"), ((i, 0), "W"), ((i, N - 1), "E")]
    return cells


def make_maze(rng, side, loop_fraction):
    # Entry on the requested side, at a random position along it.
    i = rng.randrange(N)
    start = {"N": (0, i), "S": (N - 1, i), "W": (i, 0), "E": (i, N - 1)}[side]
    goal = start
    while goal == start:
        goal = (rng.randrange(N), rng.randrange(N))

    open_edges = spanning_tree(rng)
    all_edges = {edge((r, c), n) for r in range(N) for c in range(N) for n in neighbors((r, c))}
    walls = list(all_edges - open_edges)
    rng.shuffle(walls)
    target_loops = int(len(walls) * loop_fraction)

    adj = adjacency(open_edges)
    added = 0
    for a, b in walls:
        if added >= target_loops:
            break
        adj[a].append(b)
        adj[b].append(a)
        _, n, _ = shortest_paths(adj, start, goal)
        if n == 1:
            open_edges.add((a, b))
            added += 1
        else:
            adj[a].remove(b)
            adj[b].remove(a)

    dist, n, path = shortest_paths(adj, start, goal)
    assert n == 1
    return start, goal, open_edges, path, added


def render(path_png, start, goal, side, open_edges):
    size = N * CELL + 2 * MARGIN
    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img)

    def px(r, c):
        return MARGIN + c * CELL, MARGIN + r * CELL

    # start / goal cell highlights
    for cell, color in ((start, (190, 235, 190)), (goal, (245, 190, 190))):
        x, y = px(*cell)
        d.rectangle([x + 2, y + 2, x + CELL - 2, y + CELL - 2], fill=color)
    # light grid lines marking every cell (walls are drawn over them)
    grid = (200, 200, 200)
    for i in range(N + 1):
        d.line([MARGIN + i * CELL, MARGIN, MARGIN + i * CELL, MARGIN + N * CELL], fill=grid, width=1)
        d.line([MARGIN, MARGIN + i * CELL, MARGIN + N * CELL, MARGIN + i * CELL], fill=grid, width=1)
    gx, gy = px(*goal)
    d.ellipse([gx + 14, gy + 14, gx + CELL - 14, gy + CELL - 14], fill=(200, 30, 30))
    sx, sy = px(*start)
    d.ellipse([sx + 18, sy + 18, sx + CELL - 18, sy + CELL - 18], fill=(30, 140, 50))

    w = 4
    ink = (20, 20, 20)
    # internal walls
    for r in range(N):
        for c in range(N):
            x, y = px(r, c)
            if c + 1 < N and edge((r, c), (r, c + 1)) not in open_edges:
                d.line([x + CELL, y, x + CELL, y + CELL], fill=ink, width=w)
            if r + 1 < N and edge((r, c), (r + 1, c)) not in open_edges:
                d.line([x, y + CELL, x + CELL, y + CELL], fill=ink, width=w)
    # outer walls, with a gap at the entry
    x0, y0 = MARGIN, MARGIN
    x1 = y1 = MARGIN + N * CELL
    sides = {
        "N": [(x0, y0, x1, y0)],
        "S": [(x0, y1, x1, y1)],
        "W": [(x0, y0, x0, y1)],
        "E": [(x1, y0, x1, y1)],
    }
    for s, segs in sides.items():
        for (ax, ay, bx, by) in segs:
            if s != side:
                d.line([ax, ay, bx, by], fill=ink, width=w)
                continue
            r, c = start
            if s in "NS":
                gap = (x0 + c * CELL, x0 + (c + 1) * CELL)
                d.line([ax, ay, gap[0], by], fill=ink, width=w)
                d.line([gap[1], ay, bx, by], fill=ink, width=w)
            else:
                gap = (y0 + r * CELL, y0 + (r + 1) * CELL)
                d.line([ax, ay, bx, gap[0]], fill=ink, width=w)
                d.line([ax, gap[1], bx, by], fill=ink, width=w)
    # square corners
    for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        d.rectangle([cx - w // 2, cy - w // 2, cx + w // 2, cy + w // 2], fill=ink)
    img.save(path_png)


def main():
    rng = random.Random(SEED)
    os.makedirs(OUT, exist_ok=True)
    sides = ["N", "S", "W", "E"] * (COUNT // 4)
    rng.shuffle(sides)
    meta = []
    for idx in range(COUNT):
        side = sides[idx]
        # Vary loopiness: 0 -> perfect maze (single solution), up to ~35% of walls removed.
        frac = rng.choice([0.0, 0.05, 0.1, 0.2, 0.35])
        start, goal, open_edges, path, loops = make_maze(rng, side, frac)
        name = f"maze_{idx + 1:03d}"
        render(os.path.join(OUT, name + ".png"), start, goal, side, open_edges)
        meta.append({
            "id": name,
            "entry_side": side,
            "start": list(start),
            "goal": list(goal),
            "optimal_length": len(path) - 1,
            "extra_openings": loops,
            "optimal_path": [list(p) for p in path],
            "open_edges": sorted([list(map(list, e)) for e in open_edges]),
        })
    with open(os.path.join(OUT, "mazes.json"), "w") as f:
        json.dump(meta, f)


if __name__ == "__main__":
    main()
