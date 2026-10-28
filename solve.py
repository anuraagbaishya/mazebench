"""Have an LLM (default: GLM 5.3 Flash via OpenRouter) solve the mazes in mazes/mazes.json.

By default each maze PNG is sent as a base64 data URL, which needs a vision model
(default model z-ai/glm-5.3-flash; z-ai/glm-5.3 itself is text-only).
--input ascii sends a text drawing instead, for text-only models.
The model answers with a move string (U/D/L/R); the answer is simulated against the real
maze and graded as: solved (reaches the goal), optimal (solved in the shortest number of
moves), or failed.

Usage:
    export OPENROUTER_KEY=...         # OPENROUTER_API_KEY also works
    python3 solve.py                      # all 100 mazes, as base64 images
    python3 solve.py --limit 5            # first 5
    python3 solve.py --ids maze_007 maze_042
    python3 solve.py --model z-ai/glm-5v-turbo --workers 8
    python3 solve.py --input ascii --model z-ai/glm-5.3   # text-only baseline (ascii only)

Every run re-runs all selected mazes and writes its own new file, results/<model>...<timestamp>.json.
Existing result files are never modified or overwritten.
"""
import argparse
import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

HERE = os.path.dirname(os.path.abspath(__file__))
MAZES = os.path.join(HERE, "mazes", "mazes.json")
RESULTS_DIR = os.path.join(HERE, "results")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
# Reasoning effort used when --effort is not given. Models not listed get the provider's default.
# GLM never finishes at its default effort (it reasons until the token limit with no answer).
DEFAULT_EFFORT = {
    "z-ai/glm-5.3-flash": "low",
    "z-ai/glm-5.3-flashx": "low",
    "z-ai/glm-5.3": "low",
    "z-ai/glm-5v-turbo": "low",
}
MODELS_URL = "https://openrouter.ai/api/v1/models"
IMAGES = os.path.join(HERE, "mazes")
N = 10

MOVES = {"U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1)}

PROMPT = """You are solving a maze on a {n}x{n} grid of cells.

The maze is drawn as text. '#' is a wall, ' ' (space) is open floor, 'S' is the start cell and 'G' is the goal cell. Each cell occupies one character position at odd row/column indices of the drawing; the characters between two cells are either a wall ('#') or an opening (' '). The start cell is on the outer edge and the outer wall has an opening next to it, but you must begin in the S cell itself and may not leave the grid.

{maze}

Moves: U = up (toward the top of the drawing), D = down, L = left, R = right. Each move goes from one cell to the adjacent cell, and is only allowed if there is no wall between them.

Find the SHORTEST path from S to G (fewest moves). Check each move against the drawing so that you never pass through a wall.

Finish your answer with a final line in exactly this format, and nothing after it:
ANSWER: <moves>
where <moves> is a string of the letters U, D, L, R, for example "ANSWER: RRDLDD"."""


IMAGE_PROMPT = """The attached image is a maze on a {n}x{n} grid of cells (thin gray lines separate cells; thick black lines are walls). The green cell is the start and the red cell is the goal. The start cell is on the outer edge and the outer wall has an opening next to it. You begin in the green cell and may not leave the grid.

Moves: U = up (toward the top of the image), D = down, L = left, R = right. Each move goes from one cell to the adjacent cell, and is only allowed if there is no thick black wall between them.

Find the SHORTEST path from the green cell to the red cell (fewest moves). Check each move against the image so that you never pass through a wall.

Finish your answer with a final line in exactly this format, and nothing after it:
ANSWER: <moves>
where <moves> is a string of the letters U, D, L, R, for example "ANSWER: RRDLDD"."""


def image_data_url(entry):
    with open(os.path.join(IMAGES, entry["id"] + ".png"), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def build_ascii(entry):
    n = N
    g = [["#"] * (2 * n + 1) for _ in range(2 * n + 1)]
    for r in range(n):
        for c in range(n):
            g[2 * r + 1][2 * c + 1] = " "
    for a, b in entry["open_edges"]:
        (r1, c1), (r2, c2) = a, b
        g[r1 + r2 + 1][c1 + c2 + 1] = " "
    sr, sc = entry["start"]
    gr, gc = entry["goal"]
    # opening in the outer wall next to the start cell
    side = entry["entry_side"]
    if side == "N":
        g[0][2 * sc + 1] = " "
    elif side == "S":
        g[2 * n][2 * sc + 1] = " "
    elif side == "W":
        g[2 * sr + 1][0] = " "
    else:
        g[2 * sr + 1][2 * n] = " "
    g[2 * sr + 1][2 * sc + 1] = "S"
    g[2 * gr + 1][2 * gc + 1] = "G"
    return "\n".join("".join(row) for row in g)


def parse_moves(text):
    matches = re.findall(r"ANSWER:\s*([UDLRudlr\s,]*)", text or "")
    if not matches:
        return None
    return re.sub(r"[^UDLR]", "", matches[-1].upper())


def grade(entry, moves):
    """Returns (status, note, walls), where walls describes any walls the answer ignored.

    The whole move string is walked as if walls were passable, and every move that crosses a wall
    is recorded. A path that ignores walls always fails, but walls shows how close it was:
    walls_ignored == 1 and reaches_goal_ignoring_walls means it would be correct if that one wall
    did not exist. Leaving the grid ends the walk, since there is no cell to continue from; the
    walls then cover the moves up to that point and reaches_goal_ignoring_walls is False.
    """
    edges = {(tuple(a), tuple(b)) for a, b in entry["open_edges"]}
    pos = tuple(entry["start"])
    goal = tuple(entry["goal"])
    wall_moves = []
    left_grid = False
    for i, m in enumerate(moves):
        dr, dc = MOVES[m]
        nxt = (pos[0] + dr, pos[1] + dc)
        key = (pos, nxt) if pos < nxt else (nxt, pos)
        if not (0 <= nxt[0] < N and 0 <= nxt[1] < N):
            left_grid = True
            break
        if key not in edges:
            wall_moves.append(i + 1)
        pos = nxt
    walls = {
        "walls_ignored": len(wall_moves),
        "wall_moves": wall_moves,  # 1-based indices of the moves that crossed a wall
        "reaches_goal_ignoring_walls": not left_grid and pos == goal,
    }
    listed = ", ".join(map(str, wall_moves))
    if left_grid:
        note = f"left the grid at move {i + 1}"
        if wall_moves:
            note += f"; ignored {len(wall_moves)} wall(s) before that (moves {listed})"
        return "failed", note, walls
    if wall_moves:
        note = f"hit a wall at move {wall_moves[0]}; ignored {len(wall_moves)} wall(s) (moves {listed})"
        note += ", ends at the goal" if pos == goal else ", does not end at the goal"
        return "failed", note, walls
    if pos != goal:
        return "failed", "did not reach the goal", walls
    if len(moves) == entry["optimal_length"]:
        return "optimal", "", walls
    return "solved", f"{len(moves)} moves vs optimal {entry['optimal_length']}", walls


def call_model(model, content, key, max_tokens, timeout, effort=None, retries=4):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if effort:
        payload["reasoning"] = {"effort": effort}
    body = json.dumps(payload).encode()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "mazebench",
    }
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API_URL, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
            if "error" in data:
                raise RuntimeError(json.dumps(data["error"]))
            choices = data.get("choices") or []
            if choices and choices[0].get("finish_reason") == "error":
                # provider/connection failure mid-response: no usable answer, so retry instead of grading it
                detail = choices[0].get("error") or choices[0].get("message", {}).get("content") or ""
                raise RuntimeError(f"provider error mid-response {json.dumps(detail)[:200]}")
            return data
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
            print(f"  attempt {attempt + 1}/{retries} failed: {last}", file=sys.stderr, flush=True)
            if e.code not in (408, 429, 500, 502, 503, 504):
                break
        except (OSError, http.client.HTTPException, RuntimeError, json.JSONDecodeError) as e:  # OSError covers URLError, timeouts and resets; HTTPException covers IncompleteRead
            last = str(e)
            print(f"  attempt {attempt + 1}/{retries} failed: {last}", file=sys.stderr, flush=True)
        time.sleep(2 ** attempt * 2)
    raise RuntimeError(last)


def preflight(key):
    """Fail fast if OpenRouter is unreachable or the key is rejected."""
    req = urllib.request.Request("https://openrouter.ai/api/v1/auth/key",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            info = json.load(resp).get("data", {})
    except urllib.error.HTTPError as e:
        sys.exit(f"OpenRouter rejected the key (HTTP {e.code}). Check OPENROUTER_KEY.")
    except Exception as e:
        sys.exit(f"Could not reach OpenRouter within 15s: {e}")
    print(f"OpenRouter reachable; key {info.get('label', '?')}", flush=True)


def solve_one(entry, args, key):
    if args.input == "image":
        prompt = [
            {"type": "text", "text": IMAGE_PROMPT.format(n=N)},
            {"type": "image_url", "image_url": {"url": image_data_url(entry)}},
        ]
    else:
        prompt = PROMPT.format(n=N, maze=build_ascii(entry))
    t0 = time.time()
    rec = {"id": entry["id"], "optimal_length": entry["optimal_length"]}
    try:
        data = call_model(args.model, prompt, key, args.max_tokens, args.timeout, args.effort)
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        moves = parse_moves(text)
        rec["finish_reason"] = choice.get("finish_reason")
        rec["usage"] = data.get("usage")
        rec["served_model"] = data.get("model")  # the model that answered (differs from the request for routers)
        rec["provider"] = data.get("provider")
        rec["response"] = text
        rec["reasoning"] = choice["message"].get("reasoning")
        rec["moves"] = moves
        if moves is None:
            rec["status"], rec["note"] = "failed", "no ANSWER line found"
        elif moves == "":
            rec["status"], rec["note"] = "failed", "empty answer"
        else:
            rec["status"], rec["note"], walls = grade(entry, moves)
            rec.update(walls)
    except Exception as e:  # API failure: recorded as error, retried on next run
        rec["status"], rec["note"] = "error", str(e)
    rec["seconds"] = round(time.time() - t0, 1)
    rec["run_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0))
    return rec


def check_vision(model):
    with urllib.request.urlopen(MODELS_URL, timeout=30) as resp:
        models = {m["id"]: m for m in json.load(resp)["data"]}
    info = models.get(model)
    if info is None:
        sys.exit(f"{model} not found on OpenRouter.")
    if "image" not in info.get("architecture", {}).get("input_modalities", []):
        vision = sorted(i for i, m in models.items()
                        if i.startswith("z-ai/") and "image" in m.get("architecture", {}).get("input_modalities", []))
        sys.exit(f"{model} does not accept images. z-ai vision models: {', '.join(vision)}")


def resolve_effort(model, requested):
    """--effort wins ('default' means send no setting); otherwise the per-model entry in DEFAULT_EFFORT."""
    if requested == "default":
        return None
    return requested or DEFAULT_EFFORT.get(model)


def new_result_path(results_dir, stem):
    """Reserve a result file that does not exist yet (timestamped; never overwrites)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    n = 0
    while True:
        path = os.path.join(results_dir, f"{stem}.{stamp}" + (f"-{n}" if n else "") + ".json")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            n += 1
            continue
        with os.fdopen(fd, "w") as f:
            f.write("[]")
        return path


def summarize(results, total):
    done = [r for r in results.values() if r["status"] != "error"]
    errors = len(results) - len(done)
    opt = sum(r["status"] == "optimal" for r in done)
    solved = sum(r["status"] in ("optimal", "solved") for r in done)
    print(f"\nattempted {len(done)}/{total}  (api errors: {errors})")
    if done:
        print(f"  reached goal : {solved}/{len(done)}  ({100 * solved / len(done):.1f}%)")
        print(f"  optimal path : {opt}/{len(done)}  ({100 * opt / len(done):.1f}%)")
        ignored = [r["walls_ignored"] for r in done if r.get("walls_ignored")]
        if ignored:
            print(f"  ignored walls: {len(ignored)}/{len(done)} answers crossed walls "
                  f"({sum(w == 1 for w in ignored)} crossed exactly one); {sum(ignored)} wall crossings in total")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", choices=["ascii", "image"], default="image",
                    help="send the maze as an ASCII drawing or as a base64 PNG")
    ap.add_argument("--model", help=f"OpenRouter model id (default {DEFAULT_MODEL})")
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
    ap.add_argument("--show", metavar="ID", help="print the ASCII prompt for a maze and exit")
    args = ap.parse_args()
    args.model = args.model or DEFAULT_MODEL
    args.effort = resolve_effort(args.model, args.effort)

    with open(MAZES) as f:
        mazes = json.load(f)
    if args.show:
        entry = next(m for m in mazes if m["id"] == args.show)
        print(PROMPT.format(n=N, maze=build_ascii(entry)))
        return

    key = os.environ.get("OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_KEY first.")
    preflight(key)

    if args.ids:
        mazes = [m for m in mazes if m["id"] in set(args.ids)]
    if args.start:
        mazes = mazes[args.start - 1:]
    if args.limit:
        mazes = mazes[: args.limit]

    if args.input == "image":
        check_vision(args.model)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    suffix = (".image" if args.input == "image" else "") + (f".effort-{args.effort}" if args.effort else "")
    out_path = new_result_path(RESULTS_DIR, args.model.replace("/", "_") + suffix)
    run = {}
    print(f"{len(mazes)} mazes selected to run with {args.model}; writing {out_path}")

    lock = Lock()

    def save():
        with open(out_path, "w") as f:
            json.dump(sorted(run.values(), key=lambda r: r["id"]), f, indent=1)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(solve_one, m, args, key): m for m in mazes}
        for fut in as_completed(futs):
            rec = fut.result()
            with lock:
                run[rec["id"]] = rec
                save()
            print(f"{rec['id']}: {rec['status']:8s} {rec['seconds']:6.1f}s  {rec.get('note', '')}", flush=True)

    summarize(run, len(mazes))
    print(f"saved to {out_path}")


if __name__ == "__main__":
    main()
