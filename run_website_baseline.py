#!/usr/bin/env python3
"""
Baseline: rank all 5 clean product pages N times per model, parallelized.
Results saved to results/website_baseline.json
Usage: python3 run_website_baseline.py [runs_per_model]
"""
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from api.models import get_ranking, list_models, HTML_RANKING_PROMPT

RUNS_PER_MODEL   = 3
MAX_WORKERS      = 8   # concurrent API calls
MOCK_WALMART_DIR = os.path.join(BASE_DIR, "mock-walmart")
RESULTS_DIR      = os.path.join(BASE_DIR, "results")
OUTPUT_PATH      = os.path.join(RESULTS_DIR, "website_baseline.json")

_STRIP_PATTERNS = [
    re.compile(r'<head>.*?</head>', re.DOTALL),
    re.compile(r'<header[^>]*>.*?</header>', re.DOTALL),
    re.compile(r'<footer[^>]*>.*?</footer>', re.DOTALL),
    re.compile(r'<script[^>]*>.*?</script>', re.DOTALL),
]

_print_lock = threading.Lock()

def _log(*args):
    with _print_lock:
        print(*args, flush=True)


def _product_content(html: str) -> str:
    for pat in _STRIP_PATTERNS:
        html = pat.sub('', html)
    return html.strip()


def build_clean_message() -> str:
    parts = []
    for pid in range(1, 6):
        with open(os.path.join(MOCK_WALMART_DIR, f"product-{pid}.html"), encoding="utf-8") as f:
            html = f.read()
        parts.append(f"=== PRODUCT {pid} ===\n{_product_content(html)}")
    return "\n\n".join(parts) + "\n\n" + HTML_RANKING_PROMPT


def run_one(model: str, run_idx: int, clean_message: str, dummy_products: list) -> dict:
    try:
        ranking = get_ranking(dummy_products, model, user_message=clean_message)
        ts = datetime.now().isoformat(timespec="seconds")
        _log(f"  ✓ {model:<25} run {run_idx}  →  {ranking}")
        return {"model": model, "run": run_idx, "ranking": ranking, "ts": ts}
    except Exception as e:
        ts = datetime.now().isoformat(timespec="seconds")
        _log(f"  ✗ {model:<25} run {run_idx}  →  ERROR: {e}")
        return {"model": model, "run": run_idx, "ranking": None, "error": str(e), "ts": ts}


def main(runs_per_model: int = RUNS_PER_MODEL, append: bool = False):
    models = list_models()
    dummy_products = [{"id": i} for i in range(1, 6)]
    total = len(models) * runs_per_model

    print(f"Models: {len(models)}  |  New runs: {runs_per_model}  |  Total calls: {total}  |  Workers: {MAX_WORKERS}  |  Append: {append}")
    print()

    clean_message = build_clean_message()

    # Submit all (model, run) pairs at once
    raw = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(run_one, model, run_idx, clean_message, dummy_products): (model, run_idx)
            for model in models
            for run_idx in range(1, runs_per_model + 1)
        }
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            raw.append(result)
            with _print_lock:
                print(f"  [{i}/{total} done]", flush=True)

    # Group new runs by model
    grouped: dict[str, list] = {m: [] for m in models}
    for r in raw:
        grouped[r["model"]].append(r)

    # Load existing results if appending
    existing_results = {}
    if append and os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH) as f:
            existing = json.load(f)
        existing_results = existing.get("results", {})
        print(f"  (loaded {sum(len(v['runs']) for v in existing_results.values())} existing runs)")

    results = {}
    for model in models:
        new_runs = sorted(grouped[model], key=lambda x: x["run"])
        new_records = [{"ranking": r["ranking"], "ts": r["ts"], **({"error": r["error"]} if r.get("error") else {})} for r in new_runs]
        prior_records = existing_results.get(model, {}).get("runs", []) if append else []
        all_records = prior_records + new_records
        valid = [r["ranking"] for r in all_records if r.get("ranking")]
        consistent = len(valid) > 1 and all(r == valid[0] for r in valid)
        results[model] = {"runs": all_records, "consistent": consistent}

    total_runs = runs_per_model + (len(next(iter(existing_results.values()), {}).get("runs", [])) if append else 0)
    output = {
        "meta": {
            "runs_per_model": total_runs,
            "generated_at":   datetime.now().isoformat(timespec="seconds"),
            "mode":           "html_pages",
        },
        "results": results,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved → {OUTPUT_PATH}")
    print("\n--- Consistency summary ---")
    for model in models:
        data = results[model]
        mark = "✓" if data["consistent"] else "✗"
        valid = [r["ranking"] for r in data["runs"] if r.get("ranking")]
        unique = len(set(tuple(r) for r in valid))
        print(f"  {mark} {model:<25}  {unique} unique ranking(s) across {len(valid)} valid run(s)")


if __name__ == "__main__":
    args = sys.argv[1:]
    append = "--append" in args
    args = [a for a in args if a != "--append"]
    runs = int(args[0]) if args else RUNS_PER_MODEL
    main(runs, append=append)
