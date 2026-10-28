"""Import maze descriptions produced outside describe.py (e.g. a model run by hand) as a results file.

Input is a JSONL file with one object per maze:
    {"maze": "maze_001.png", "start": [r, c], "goal": [r, c], "right_walls": [...], "down_walls": [...]}

Each entry is graded with the same grader as describe.py and written, in the same record format, to a
new results/<model>.describe.<timestamp>.json (never overwriting an existing file). The raw input is
copied to results/raw/ alongside it. Imported records carry "source" and have no response, reasoning,
usage or seconds fields, since no API call was made by this repo.

Usage:
    python3 import_descriptions.py vision_notes.jsonl --model anthropic/claude-sonnet-5.5
"""
import argparse
import json
import os
import shutil
import sys
import time

import describe
import solve


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jsonl")
    ap.add_argument("--model", required=True, help="model id the descriptions came from")
    ap.add_argument("--label", default="imported", help="tag added to the file name (default: imported)")
    args = ap.parse_args()

    with open(solve.MAZES) as f:
        mazes = {m["id"]: m for m in json.load(f)}
    src = os.path.abspath(args.jsonl)
    with open(src) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(src)))
    records = []
    for entry in entries:
        mid = entry["maze"].removesuffix(".png")
        if mid not in mazes:
            sys.exit(f"unknown maze {entry['maze']!r}")
        desc = {k: entry[k] for k in ("start", "goal", "right_walls", "down_walls") if k in entry}
        records.append({
            "id": mid,
            "status": "graded",
            "note": "",
            "description": desc,
            "scores": describe.grade(mazes[mid], desc),
            "run_at": stamp,
            "source": f"imported from {os.path.basename(src)}",
        })
    ids = [r["id"] for r in records]
    if len(set(ids)) != len(ids):
        sys.exit("duplicate mazes in input")
    records.sort(key=lambda r: r["id"])

    os.makedirs(solve.RESULTS_DIR, exist_ok=True)
    stem = args.model.replace("/", "_") + ".describe." + args.label
    out_path = solve.new_result_path(solve.RESULTS_DIR, stem)
    with open(out_path, "w") as f:
        json.dump(records, f, indent=1)

    raw_dir = os.path.join(solve.RESULTS_DIR, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    # named after the (unique) results file, opened exclusively so it can never overwrite anything
    raw_path = os.path.join(raw_dir, os.path.basename(out_path).removesuffix(".json") + ".jsonl")
    with open(src, "rb") as fin, open(raw_path, "xb") as fout:
        shutil.copyfileobj(fin, fout)
    print(f"{len(records)} records -> {out_path}\nraw copy      -> {raw_path}\n")
    describe.summarize(records, len(mazes))


if __name__ == "__main__":
    main()
