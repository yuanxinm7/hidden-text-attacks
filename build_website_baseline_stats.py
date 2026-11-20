#!/usr/bin/env python3
"""Summarize clean HTML ranking runs by model and product.

Reads results/website_baseline.json and writes
results/html_baseline_website_<YYYY-MM-DD_HH-MM-SS>.json.

The output retains ``product_stats`` and ``attackability`` for compatibility
with older visualization and experiment code.  ``impossible`` means only that
all *observed valid clean rankings* put the target at #1; it is not a proof
that the model can never rank it lower.

Usage:
    python build_website_baseline_stats.py
    python build_website_baseline_stats.py --min-valid-runs 5
    python build_website_baseline_stats.py --input results/website_baseline.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
INPUT_PATH = RESULTS_DIR / "website_baseline.json"
EXPECTED_IDS = frozenset(range(1, 6))


def _is_valid_ranking(value: Any) -> bool:
    """A full, unambiguous five-product permutation, not a partial response."""
    return (
        isinstance(value, list)
        and len(value) == len(EXPECTED_IDS)
        and all(type(item) is int for item in value)
        and set(value) == EXPECTED_IDS
    )


def stats_for_model(model: str, runs: list, min_valid_runs: int = 5) -> dict:
    """Generate stats without silently accepting partial/malformed rankings.

    ``unknown`` denotes insufficient valid baseline observations.
    ``impossible`` denotes only no *observed* opportunity to move upward.
    The experimental runner must not treat that as proof of zero attackability.
    """
    if min_valid_runs < 1:
        raise ValueError("min_valid_runs must be >= 1")
    if not isinstance(runs, list):
        raise ValueError(f"{model}: runs must be a list")

    valid = [r["ranking"] for r in runs if isinstance(r, dict) and _is_valid_ranking(r.get("ranking"))]
    invalid_count = len(runs) - len(valid)
    product_stats = {}
    for pid in sorted(EXPECTED_IDS):
        positions = [ranking.index(pid) + 1 for ranking in valid]
        if not positions:
            product_stats[str(pid)] = {
                "attackability": "unknown", "min": None, "max": None,
                "mean": None, "ranks": [], "signal_rank_ceiling": None,
                "n_valid": 0,
            }
            continue
        lo, hi = min(positions), max(positions)
        mean = sum(positions) / len(positions)
        if len(valid) < min_valid_runs:
            status = "unknown"
        elif lo == hi == 1:
            status = "impossible"  # observed ceiling only, not a universal claim
        elif lo != hi:
            status = "noisy"
        else:
            status = "ok"

        product_stats[str(pid)] = {
            "attackability": status,
            "min": lo,
            "max": hi,
            "mean": round(mean, 2),
            "ranks": positions,
            "signal_rank_ceiling": lo - 1 if lo > 1 else None,
            "n_valid": len(valid),
        }

    return {
        "product_stats": product_stats,
        "n_total": len(runs),
        "n_valid": len(valid),
        "n_invalid": invalid_count,
        "n_unique_valid_rankings": len({tuple(r) for r in valid}),
        "min_valid_runs_required": min_valid_runs,
    }


def build_stats(data: dict, min_valid_runs: int = 5) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("results"), dict):
        raise ValueError("Expected a JSON object with a 'results' mapping")
    output = {}
    for model, entry in data["results"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("runs"), list):
            # Keep a diagnostic record rather than silently excluding a model.
            output[model] = {"product_stats": {}, "error": "Missing or invalid 'runs' list"}
            continue
        output[model] = stats_for_model(model, entry["runs"], min_valid_runs)
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--min-valid-runs", type=int, default=5)
    args = parser.parse_args(argv)

    if args.min_valid_runs < 1:
        parser.error("--min-valid-runs must be >= 1")
    with args.input.open(encoding="utf-8") as f:
        data = json.load(f)
    output = build_stats(data, min_valid_runs=args.min_valid_runs)

    if args.output is None:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_path = RESULTS_DIR / f"html_baseline_website_{stamp}.json"
    else:
        out_path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved → {out_path} ({len(output)} models)")
    print("Note: 'impossible' means only all observed valid clean ranks were #1.")
    for model in sorted(output):
        entry = output[model]
        if "error" in entry:
            print(f"  {model}: ERROR {entry['error']}")
            continue
        parts = []
        for pid in range(1, 6):
            s = entry["product_stats"][str(pid)]
            lo, hi = s["min"], s["max"]
            range_text = "?" if lo is None else str(lo) if lo == hi else f"{lo}–{hi}"
            parts.append(f"P{pid}:{s['attackability']}({range_text})")
        print(f"  {model:<25} valid={entry['n_valid']}/{entry['n_total']}  {' | '.join(parts)}")


if __name__ == "__main__":
    main()
