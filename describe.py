"""Have a vision LLM describe each maze image instead of solving it.

The model is shown the maze PNG (base64) and asked to report the start cell, the goal cell
and which walls exist between neighbouring cells. The description is graded against the true
layout in mazes/mazes.json, which measures how well the model reads the image independently
of how well it plans a route.

Wall encoding (rows top->bottom 0-9, columns left->right 0-9):
    right_walls: 10 strings of 9 chars; char c of row r is '1' if there is a wall between
                 cell (r,c) and (r,c+1), else '0'.
    down_walls:  9 strings of 10 chars; char c of row r is '1' if there is a wall between
                 cell (r,c) and (r+1,c), else '0'.
The outer boundary is not described.

Usage:
    export OPENROUTER_KEY=...
    python3 describe.py --limit 5
    python3 describe.py --model z-ai/glm-5v-turbo --workers 8
    python3 describe.py --show maze_001          # print the prompt

Every run re-runs all selected mazes and writes its own new file, results/<model>.describe...<timestamp>.json.
Existing result files are never modified or overwritten.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import solve
from solve import N, call_model, check_vision, image_data_url, new_result_path, preflight

HERE = os.path.dirname(os.path.abspath(__file__))
MAZES = solve.MAZES
RESULTS_DIR = solve.RESULTS_DIR

PROMPT = """The attached image is a maze on a {n}x{n} grid of cells. Thin gray lines separate cells; thick black lines are walls. One cell is filled green (the start) and one cell is filled red (the goal).

Do NOT solve the maze. Describe it precisely.

Number the rows 0-{last} from top to bottom and the columns 0-{last} from left to right, so (0,0) is the top-left cell and ({last},{last}) is the bottom-right cell. Report:

- "start": [row, col] of the green cell.
- "goal": [row, col] of the red cell.
- "right_walls": a list of {n} strings, one per row (row 0 first), each {m} characters long. Character c of row r is "1" if there is a thick black wall between cell (r,c) and cell (r,c+1), otherwise "0".
- "down_walls": a list of {m} strings, one per row boundary (the boundary between row 0 and row 1 first), each {n} characters long. Character c of string r is "1" if there is a thick black wall between cell (r,c) and cell (r+1,c), otherwise "0".

Do not describe the outer border of the maze, only walls between neighbouring cells.

Finish with a single JSON object containing exactly those four keys, in a ```json code block, and nothing after it."""


def parse_description(text):
    """Return the last JSON object in the text that has a right_walls key, else None."""
    if not text:
        return None
    dec = json.JSONDecoder()
    for i in range(len(text) - 1, -1, -1):
        if text[i] != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "right_walls" in obj:
            return obj
    return None


def _rows(value, count, width):
    """Normalise a list of strings (or lists) into count rows of width '0'/'1' chars.
    Anything missing or malformed becomes None, which is counted as wrong when grading."""
    out = []
    if not isinstance(value, list):
        value = []
    for i in range(count):
        row = value[i] if i < len(value) else None
        if isinstance(row, list):
            row = "".join(str(int(bool(x))) if isinstance(x, (bool, int)) else "?" for x in row)
        if not isinstance(row, str):
            out.append([None] * width)
            continue
        row = row.strip()
        out.append([row[c] if c < len(row) and row[c] in "01" else None for c in range(width)])
    return out


def true_walls(entry):
    """Ground truth as (right, down) grids of '1' (wall) / '0' (open)."""
    open_edges = {(tuple(a), tuple(b)) for a, b in entry["open_edges"]}
    right = [["0" if ((r, c), (r, c + 1)) in open_edges else "1" for c in range(N - 1)] for r in range(N)]
    down = [["0" if ((r, c), (r + 1, c)) in open_edges else "1" for c in range(N)] for r in range(N - 1)]
    return right, down


def _cell(v):
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in v):
        return v
    return None


def grade(entry, desc):
    """Compare a parsed description with the truth."""
    t_right, t_down = true_walls(entry)
    m_right = _rows(desc.get("right_walls"), N, N - 1)
    m_down = _rows(desc.get("down_walls"), N - 1, N)
    tp = fp = fn = correct = total = 0
    missing = 0
    for truth, model in ((t_right, m_right), (t_down, m_down)):
        for trow, mrow in zip(truth, model):
            for t, m in zip(trow, mrow):
                total += 1
                if m is None:
                    missing += 1
                    fn += t == "1"
                    continue
                correct += t == m
                tp += t == "1" and m == "1"
                fp += t == "0" and m == "1"
                fn += t == "1" and m == "0"
    walls = sum(c == "1" for row in t_right + t_down for c in row)
    return {
        "start_ok": _cell(desc.get("start")) == list(entry["start"]),
        "goal_ok": _cell(desc.get("goal")) == list(entry["goal"]),
        "edge_accuracy": correct / total,
        "wall_recall": tp / walls if walls else None,
        "wall_precision": tp / (tp + fp) if tp + fp else None,
        "exact": correct == total,
        "missing_edges": missing,
        "wall_share": walls / total,
    }


def describe_one(entry, args, key):
    content = [
        {"type": "text", "text": PROMPT.format(n=N, m=N - 1, last=N - 1)},
        {"type": "image_url", "image_url": {"url": image_data_url(entry)}},
    ]
    t0 = time.time()
    rec = {"id": entry["id"]}
    try:
        data = call_model(args.model, content, key, args.max_tokens, args.timeout, args.effort)
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        rec["finish_reason"] = choice.get("finish_reason")
        rec["usage"] = data.get("usage")
        rec["served_model"] = data.get("model")  # the model that answered (differs from the request for routers)
        rec["provider"] = data.get("provider")
        rec["response"] = text
        rec["reasoning"] = choice["message"].get("reasoning")
        desc = parse_description(text)
        if desc is None:
            rec["status"], rec["note"] = "failed", "no parseable JSON description"
        else:
            rec["description"] = desc
            rec["status"], rec["note"] = "graded", ""
            rec["scores"] = grade(entry, desc)
    except Exception as e:  # API failure: recorded as error, retried on next run
        rec["status"], rec["note"] = "error", str(e)
    rec["seconds"] = round(time.time() - t0, 1)
    rec["run_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0))
    return rec


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def summarize(recs, total):
    done = [r for r in recs if r["status"] != "error"]
    graded = [r for r in done if r["status"] == "graded"]
    print(f"\nattempted {len(done)}/{total}  (api errors: {len(recs) - len(done)}, unparseable: {len(done) - len(graded)})")
    if not graded:
        return
    s = [r["scores"] for r in graded]
    print(f"  start cell correct : {sum(x['start_ok'] for x in s)}/{len(s)}")
    print(f"  goal cell correct  : {sum(x['goal_ok'] for x in s)}/{len(s)}")
    print(f"  wall edge accuracy : {100 * mean(x['edge_accuracy'] for x in s):.1f}%  (of {2 * N * (N - 1)} edges per maze)")
    print(f"  wall recall        : {100 * mean(x['wall_recall'] for x in s):.1f}%")
    print(f"  wall precision     : {100 * mean(x['wall_precision'] for x in s):.1f}%")
    print(f"  exact descriptions : {sum(x['exact'] for x in s)}/{len(s)}")
    print(f"  (for reference: reporting no walls at all scores {100 * (1 - mean(x['wall_share'] for x in s)):.1f}% edge accuracy)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=solve.DEFAULT_MODEL, help="vision model id on OpenRouter")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--start", type=int, help="first maze number to run (1-based); applied before --limit")
    ap.add_argument("--limit", type=int, help="run at most this many mazes")
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="cap on response tokens (default: no cap, the model's own maximum applies)")
    ap.add_argument("--effort", choices=["low", "medium", "high", "default"],
                    help="reasoning effort; 'default' sends no setting. Unset: per-model DEFAULT_EFFORT "
                         "(GLM: low), else the provider default")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--show", action="store_true", help="print the prompt and exit")
    args = ap.parse_args()
    args.effort = solve.resolve_effort(args.model, args.effort)

    if args.show:
        print(PROMPT.format(n=N, m=N - 1, last=N - 1))
        return

    key = os.environ.get("OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_KEY first.")
    preflight(key)
    check_vision(args.model)

    with open(MAZES) as f:
        mazes = json.load(f)
    if args.ids:
        mazes = [m for m in mazes if m["id"] in set(args.ids)]
    if args.start:
        mazes = mazes[args.start - 1:]
    if args.limit:
        mazes = mazes[: args.limit]

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stem = args.model.replace("/", "_") + ".describe" + (f".effort-{args.effort}" if args.effort else "")
    out_path = new_result_path(RESULTS_DIR, stem)
    run = {}
    print(f"{len(mazes)} mazes selected to run with {args.model}; writing {out_path}")

    lock = Lock()

    def save():
        with open(out_path, "w") as f:
            json.dump(sorted(run.values(), key=lambda r: r["id"]), f, indent=1)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(describe_one, m, args, key) for m in mazes]
        for fut in as_completed(futs):
            rec = fut.result()
            with lock:
                run[rec["id"]] = rec
                save()
            sc = rec.get("scores")
            detail = (f"edges {100 * sc['edge_accuracy']:.0f}%  start {'ok' if sc['start_ok'] else 'WRONG'}  "
                      f"goal {'ok' if sc['goal_ok'] else 'WRONG'}") if sc else rec.get("note", "")
            print(f"{rec['id']}: {rec['status']:7s} {rec['seconds']:6.1f}s  {detail}", flush=True)

    summarize(list(run.values()), len(mazes))
    print(f"saved to {out_path}")


if __name__ == "__main__":
    main()
