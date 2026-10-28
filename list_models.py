"""Write a CSV of OpenRouter models listed in the last N months (default 6), from the live model list.

Usage:
    python3 list_models.py                     # models_last_6_months.csv
    python3 list_models.py --months 3 --out recent.csv

By default the output is the SHORTLIST of at most 15 models (--all-models to skip it), cut down to the
cheapest model per provider (--multi-per-provider to keep several; KEEP_REGARDLESS_OF_PRICE is exempt). Before that, only
models from well-known providers (COMMON_PROVIDERS) are listed (--all-providers to
include the rest), and only the newest version of each model line is kept (see keep_newest_generation;
--all-generations to keep every model). Models without a fixed input and output price (e.g. routers) are omitted unless they are in SHORTLIST (their
cost cells are then blank). Rows are sorted by output price, low to high. Prices are USD per million tokens. release_date is OpenRouter's `created` timestamp, i.e. when the model
was added to OpenRouter, which can be later than the model's own public release.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# Well-known providers. OpenRouter's list has no usage data, so "common" is a judgement call: edit freely.
COMMON_PROVIDERS = {
    "anthropic", "openai", "google", "x-ai", "meta", "deepseek", "qwen", "moonshotai", "z-ai",
    "mistralai", "nvidia", "minimax", "xiaomi", "bytedance-seed", "tencent", "stepfun", "cohere",
    "ibm-granite",
}


def months_ago(today, months):
    y, m = today.year, today.month - months
    while m < 1:
        y, m = y - 1, m + 12
    # clamp the day to the length of the target month
    for day in (today.day, 30, 29, 28):
        try:
            return dt.date(y, m, day)
        except ValueError:
            continue


# Final shortlist (at most 15): image-capable models, about one per provider, from COMMON_PROVIDERS' newest
# generation. Edit to swap models; --all-models ignores it.
SHORTLIST = [
    "anthropic/claude-sonnet-5.5",
    "anthropic/claude-haiku-5.5",
    "openai/gpt-6-luna",
    "google/gemini-4-argon",
    "google/gemini-3.8-flash",
    "x-ai/grok-4.7",
    "meta/muse-spark-1.3",
    "deepseek/deepseek-v4.1-flash",
    "qwen/qwen3.8-max-0902",
    "moonshotai/kimi-k3",
    "z-ai/glm-5.3-flash",
    "mistralai/mistral-large-4-0",
    "nvidia/nemotron-3.5-super-vl",
    "xiaomi/mimo-v2.6-pro",
]

# Kept even when a cheaper model from the same provider is also listed: Sonnet because results already
# exist, Gemini 4 Argon because it is Google's frontier model and there is no cheap Gemini 4.
KEEP_REGARDLESS_OF_PRICE = {"anthropic/claude-sonnet-5.5", "google/gemini-4-argon"}


def _clean_name(model_id):
    """Model name without provider prefix, with size tags (30b, 2.4t, a3b) and date/build tags (0902,
    20260420) blanked out and 'large-4-0' style versions turned into 'large-4.0'."""
    name = model_id.split("/", 1)[1]
    name = re.sub(r"(?<![a-z0-9.])a?\d+(\.\d+)?[bt](?![a-z0-9])", " ", name)
    name = re.sub(r"(?<!\d)\d{4,}(?!\d)", " ", name)
    return re.sub(r"(?<=\d)-(?=\d(?!\d))", ".", name)


def parse_version(model_id):
    """Version tuple from the model name, e.g. 'claude-opus-5.5' -> (5, 5), 'mistral-large-4-0' -> (4, 0);
    None if the name has no version."""
    m = re.search(r"\d+(?:\.\d+)*", _clean_name(model_id))
    return tuple(int(x) for x in m.group().split(".")) if m else None


def tier_key(model_id):
    """Provider plus the model name with its version removed, shared by every version of a model line:
    openai/gpt-5.6-luna and openai/gpt-6-luna both -> 'openai/gpt-luna'."""
    name = _clean_name(model_id)
    name = re.sub(r"\d+(?:\.\d+)*", "", name, count=1)
    return model_id.split("/")[0] + "/" + re.sub(r"[-_ ]+", "-", name).strip("-")


def keep_newest_generation(rows):
    """Keep the newest version of each model line (tier) per provider.

    A tier is the model name with its version removed, so claude-opus-4.8 and claude-opus-5.5 compete,
    but claude-haiku-5.5 is its own tier; gpt-6-luna stays even though gpt-6.1-sol exists. Models whose
    name has no version are always kept."""
    groups = {}
    for r in rows:
        groups.setdefault(tier_key(r["model_id"]), []).append(r)
    kept = []
    for models in groups.values():
        ver = {r["model_id"]: parse_version(r["model_id"]) for r in models}
        versions = [v for v in ver.values() if v]
        if not versions:
            kept += models
            continue
        newest = max(versions)  # tuple comparison: (26, 10) > (26, 9), (6, 1) > (6,)
        kept += [r for r in models if ver[r["model_id"]] in (newest, None)]
    return kept


def price_key(r):
    """Sort key: output price, then input price, then name; models with no fixed price sort last."""
    return (r["output_usd_per_m_tokens"] == "", r["output_usd_per_m_tokens"] or 0,
            r["input_usd_per_m_tokens"] or 0, r["model_id"])


def per_million(value):
    try:
        v = float(value) * 1e6
    except (TypeError, ValueError):
        return ""
    return "" if v < 0 else round(v, 4)  # negative = variable pricing (routers)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--multi-per-provider", action="store_true", help="keep several models per provider, not just the cheapest")
    ap.add_argument("--all-models", action="store_true", help="ignore SHORTLIST (all models passing the other filters)")
    ap.add_argument("--all-providers", action="store_true", help="include lesser-known providers too")
    ap.add_argument("--all-generations", action="store_true", help="keep older generations too")
    ap.add_argument("--out", default=os.path.join(HERE, "models_last_6_months.csv"))
    args = ap.parse_args()

    today = dt.date.today()
    cutoff = months_ago(today, args.months)
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=60) as resp:
        models = json.load(resp)["data"]

    rows = []
    skipped_variants = skipped_aliases = skipped_no_price = 0
    for m in models:
        if m["id"].startswith("~"):  # moving aliases that point at another model
            skipped_aliases += 1
            continue
        if ":" in m["id"]:  # :free / :batch / :thinking variants of a model that is listed separately
            skipped_variants += 1
            continue
        created = dt.datetime.fromtimestamp(m.get("created", 0), dt.timezone.utc).date()
        if created < cutoff:
            continue
        arch = m.get("architecture", {})
        p = m.get("pricing", {})
        prompt_price, completion_price = per_million(p.get("prompt")), per_million(p.get("completion"))
        if (prompt_price == "" or completion_price == "") and m["id"] not in SHORTLIST:  # no fixed price (e.g. routers)
            skipped_no_price += 1
            continue
        rows.append({
            "model_id": m["id"],
            "name": m.get("name", ""),
            "release_date": created.isoformat(),
            "version": ".".join(map(str, parse_version(m["id"]))) if parse_version(m["id"]) else "",
            "input_usd_per_m_tokens": prompt_price,
            "output_usd_per_m_tokens": completion_price,
            "context_length": m.get("context_length", ""),
            "accepts_images": "image" in arch.get("input_modalities", []),
            "supports_reasoning": "reasoning" in m.get("supported_parameters", []),
        })
    uncommon = 0
    if not args.all_providers:
        common = [r for r in rows if r["model_id"].split("/")[0] in COMMON_PROVIDERS or r["model_id"] in SHORTLIST]
        uncommon, rows = len(rows) - len(common), common
    before = len(rows)
    if not args.all_generations:
        rows = keep_newest_generation(rows)
    if not args.all_models:
        found = {r["model_id"] for r in rows}
        missing = [i for i in SHORTLIST if i not in found]
        if missing:
            print(f"warning: shortlisted models not in the filtered list (renamed, older than the window, or "
                  f"removed from OpenRouter): {', '.join(missing)}")
        rows = [r for r in rows if r["model_id"] in SHORTLIST]
    dropped_dear = 0
    if not args.multi_per_provider:
        cheapest = {}
        exempt = [r for r in rows if r["model_id"] in KEEP_REGARDLESS_OF_PRICE]
        for r in rows:
            p = r["model_id"].split("/")[0]
            if r in exempt:
                continue
            if p not in cheapest or price_key(r) < price_key(cheapest[p]):
                cheapest[p] = r
        kept = list(cheapest.values()) + exempt
        dropped_dear = len(rows) - len(kept)
        rows = kept
    # cheapest first by output price (it dominates the cost of reasoning models), then input price;
    # models with no fixed price go last
    rows.sort(key=price_key)
    if not args.all_models and len(rows) > 15:
        raise SystemExit(f"{len(rows)} models after filtering; the cap is 15. Trim SHORTLIST.")

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} models listed since {cutoff} (of {len(models)} total) -> {args.out}")
    if not args.all_providers:
        print(f"models from lesser-known providers removed: {uncommon}")
    if not args.all_generations:
        print(f"older generations from the same provider removed: {before - len(rows)}")
    if not args.multi_per_provider:
        print(f"pricier models from providers with several models removed: {dropped_dear}")
    print(f"left out: {skipped_variants} ':' variants, {skipped_aliases} '~' aliases, "
          f"{skipped_no_price} recent models with no fixed price")


if __name__ == "__main__":
    main()
