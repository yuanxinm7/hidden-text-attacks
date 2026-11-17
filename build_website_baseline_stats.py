#!/usr/bin/env python3
"""
Compute per-(model, product) baseline stats from website_baseline.json
for models with ≤2 unique rankings, and save as baseline_website_<date>.json
so the existing frontend annotations pick it up automatically.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
INPUT_PATH  = os.path.join(BASE_DIR, "results", "website_baseline.json")
DATE_STAMP  = datetime.now().strftime("%Y-%m-%d")
OUTPUT_PATH = os.path.join(BASE_DIR, "results", f"baseline_website_{DATE_STAMP}.json")


def stats_for_model(model: str, runs: list) -> dict:
    valid = [r["ranking"] for r in runs if r.get("ranking")]
    product_stats = {}

    for pid in range(1, 6):
        # Position of this product in each run (1-indexed)
        positions = [ranking.index(pid) + 1 for ranking in valid if pid in ranking]
        if not positions:
            continue

        lo, hi = min(positions), max(positions)
        mean = sum(positions) / len(positions)

        if lo == hi == 1:
            attackability = "impossible"
            ceiling = None
        elif lo != hi:
            attackability = "noisy"
            ceiling = lo - 1 if lo > 1 else None
        else:
            attackability = "ok"
            ceiling = lo - 1 if lo > 1 else None

        product_stats[str(pid)] = {
            "attackability":      attackability,
            "min":                lo,
            "max":                hi,
            "mean":               round(mean, 2),
            "ranks":              positions,
            "signal_rank_ceiling": ceiling,
        }

    return {"product_stats": product_stats}


def main():
    with open(INPUT_PATH) as f:
        data = json.load(f)

    eligible = {model: d for model, d in data["results"].items()}

    print(f"Computing stats for {len(eligible)} models ...")

    output = {}
    with ThreadPoolExecutor(max_workers=len(eligible)) as pool:
        futures = {
            pool.submit(stats_for_model, model, d["runs"]): model
            for model, d in eligible.items()
        }
        for future in as_completed(futures):
            model = futures[future]
            output[model] = future.result()
            print(f"  ✓ {model}")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved → {OUTPUT_PATH}")
    print("\n--- Attackability per model (product: status min–max) ---")
    for model in sorted(output):
        stats = output[model]["product_stats"]
        parts = []
        for pid in ["1","2","3","4","5"]:
            s = stats.get(pid, {})
            a = s.get("attackability","?")
            lo, hi = s.get("min","?"), s.get("max","?")
            tag = {"impossible": "🚫", "noisy": "~", "ok": "✓"}.get(a, "?")
            rng = f"{lo}" if lo == hi else f"{lo}–{hi}"
            parts.append(f"P{pid}:{tag}{rng}")
        print(f"  {model:<25}  {' | '.join(parts)}")


if __name__ == "__main__":
    main()
