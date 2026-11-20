#!/usr/bin/env python3
"""
Retry all error/timeout runs in website_baseline.json with bumped timeouts.
Replaces error entries in-place, re-saves the file.
"""
import json
import os
import re
import sys
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from api.models import get_ranking, list_models, HTML_RANKING_PROMPT, MODEL_TIMEOUTS, DEFAULT_TIMEOUT

OUTPUT_PATH      = os.path.join(BASE_DIR, "results", "website_baseline.json")
MOCK_WALMART_DIR = os.path.join(BASE_DIR, "mock-walmart")

# Extra seconds added on top of each model's base timeout for retry
TIMEOUT_EXTRA = {
    "llama-4-maverick":  120,   # base 30s → 150s
    "deepseek-v4-pro":   180,   # base 240s → 420s
    "qwen3.6-max":        90,   # base 90s → 180s
    "mistral-medium-3.5": 30,   # 429s, just need a retry with a gap
}
DEFAULT_EXTRA = 60

# Delay before retrying 429 rate-limit errors
RATE_LIMIT_DELAY = 8

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

def retry_one(model: str, run_idx: int, clean_message: str, dummy_products: list, is_rate_limit: bool) -> dict:
    if is_rate_limit:
        time.sleep(RATE_LIMIT_DELAY)
    timeout_extra = TIMEOUT_EXTRA.get(model, DEFAULT_EXTRA)
    try:
        ranking = get_ranking(dummy_products, model, user_message=clean_message, timeout_extra=timeout_extra)
        ts = datetime.now().isoformat(timespec="seconds")
        _log(f"  ✓ {model:<25} run_idx {run_idx}  →  {ranking}")
        return {"run_idx": run_idx, "model": model, "ranking": ranking, "ts": ts}
    except Exception as e:
        ts = datetime.now().isoformat(timespec="seconds")
        _log(f"  ✗ {model:<25} run_idx {run_idx}  →  ERROR: {e}")
        return {"run_idx": run_idx, "model": model, "ranking": None, "error": str(e), "ts": ts}

def main():
    with open(OUTPUT_PATH) as f:
        data = json.load(f)

    dummy_products = [{"id": i} for i in range(1, 6)]
    clean_message = build_clean_message()

    # Collect all error runs
    retry_jobs = []
    for model, d in data["results"].items():
        for i, run in enumerate(d["runs"]):
            if run.get("error"):
                is_rate_limit = "429" in run["error"]
                retry_jobs.append((model, i, is_rate_limit))

    if not retry_jobs:
        print("No errors found — nothing to retry.")
        return

    print(f"Retrying {len(retry_jobs)} failed run(s) across {len({j[0] for j in retry_jobs})} model(s)")
    print()

    results_map = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(retry_one, model, idx, clean_message, dummy_products, is_rl): (model, idx)
            for model, idx, is_rl in retry_jobs
        }
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            results_map[(r["model"], r["run_idx"])] = r
            _log(f"  [{i}/{len(retry_jobs)} done]")

    # Patch results back in
    for model, idx, _ in retry_jobs:
        r = results_map[(model, idx)]
        record = {"ranking": r["ranking"], "ts": r["ts"]}
        if r.get("error"):
            record["error"] = r["error"]
        data["results"][model]["runs"][idx] = record

    # Recompute consistency
    for model, d in data["results"].items():
        valid = [r["ranking"] for r in d["runs"] if r.get("ranking")]
        d["consistent"] = len(valid) > 1 and all(r == valid[0] for r in valid)

    data["meta"]["generated_at"] = datetime.now().isoformat(timespec="seconds")

    retry_path = OUTPUT_PATH.replace(".json", f"_retry_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.json")
    with open(retry_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nSaved → {retry_path}")
    print("\n--- Updated consistency summary ---")
    for model in list_models():
        d = data["results"].get(model)
        if not d:
            continue
        mark = "✓" if d["consistent"] else "✗"
        valid = [r["ranking"] for r in d["runs"] if r.get("ranking")]
        errors = sum(1 for r in d["runs"] if r.get("error"))
        unique = len(set(tuple(r) for r in valid))
        err_str = f"  ({errors} still erroring)" if errors else ""
        print(f"  {mark} {model:<25}  {unique} unique ranking(s) across {len(valid)} valid run(s){err_str}")

if __name__ == "__main__":
    main()
