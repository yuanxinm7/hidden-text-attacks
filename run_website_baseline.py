#!/usr/bin/env python3
"""Collect clean HTML-page rankings for the same prompt used in HTML attacks.

Usage:
    python3 run_website_baseline.py [runs_per_model] [--append]

Output is compatible with existing consumers of results/website_baseline.json:
    {"meta": {...}, "results": {model: {"runs": [...], "consistent": bool}}}

A run is valid only if it supplies a complete permutation of product IDs 1..5.
Existing data is preserved in a timestamped backup before a non-append overwrite.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from api.models import (
    get_ranking, list_models, HTML_RANKING_PROMPT, RefusalError,
    HTML_MODEL_TIMEOUTS, HTML_DEFAULT_TIMEOUT, MODEL_TIMEOUTS, DEFAULT_TIMEOUT,
)
try:
    from api.models import InvalidRankingError
except ImportError:  # allow use with the original API module
    class InvalidRankingError(ValueError):
        pass

RUNS_PER_MODEL = 3  # Retained for CLI compatibility; use more for inference.
MAX_WORKERS = 8
MOCK_WALMART_DIR = os.path.join(BASE_DIR, "mock-walmart")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
OUTPUT_PATH = os.path.join(RESULTS_DIR, "website_baseline.json")
PRODUCT_IDS = tuple(range(1, 6))

# Keep in sync with run_html_attacks.py, which removes these blocks.
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
    for pattern in _STRIP_PATTERNS:
        html = pattern.sub('', html)
    return html.strip()


def build_clean_message() -> str:
    parts = []
    for pid in PRODUCT_IDS:
        with open(os.path.join(MOCK_WALMART_DIR, f"product-{pid}.html"), encoding="utf-8") as f:
            html = f.read()
        parts.append(f"=== PRODUCT {pid} ===\n{_product_content(html)}")
    return "\n\n".join(parts) + "\n\n" + HTML_RANKING_PROMPT


def _valid_ranking(ranking) -> bool:
    return (isinstance(ranking, list) and len(ranking) == len(PRODUCT_IDS)
            and all(type(pid) is int for pid in ranking)
            and set(ranking) == set(PRODUCT_IDS))


def _html_timeout_extra(model: str) -> int:
    return max(0, HTML_MODEL_TIMEOUTS.get(model, HTML_DEFAULT_TIMEOUT)
               - MODEL_TIMEOUTS.get(model, DEFAULT_TIMEOUT))


def run_one(model: str, run_idx: int, clean_message: str, dummy_products: list) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {"model": model, "run": run_idx, "ranking": None, "ts": timestamp}
    try:
        ranking = get_ranking(dummy_products, model, user_message=clean_message,
                              timeout_extra=_html_timeout_extra(model))
        if not _valid_ranking(ranking):
            raise InvalidRankingError(f"Incomplete or invalid ranking: {ranking!r}")
        record["ranking"] = ranking
        _log(f"  ✓ {model:<25} run {run_idx} → {ranking}")
    except RefusalError as exc:
        record.update(status="refused", error=str(exc))
        _log(f"  ~ {model:<25} run {run_idx} → refusal: {exc}")
    except InvalidRankingError as exc:
        record.update(status="invalid", error=str(exc))
        _log(f"  ! {model:<25} run {run_idx} → invalid: {exc}")
    except Exception as exc:
        record.update(status="error", error=str(exc))
        _log(f"  ✗ {model:<25} run {run_idx} → error: {exc}")
    else:
        record["status"] = "ok"
    return record


def _atomic_write_json(path: str, value: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".website_baseline_", suffix=".json",
                               dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _backup_existing():
    if not os.path.exists(OUTPUT_PATH):
        return None
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup_path = os.path.join(RESULTS_DIR, f'website_baseline.backup_{stamp}.json')
    # Copy first, then replace primary atomically. Never overwrite a backup.
    with open(OUTPUT_PATH, 'rb') as src, open(backup_path, 'xb') as dst:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)
    return backup_path


def _summarize(records: list) -> dict:
    valid = [record['ranking'] for record in records if _valid_ranking(record.get('ranking'))]
    return {
        'consistent': len(valid) >= 2 and len(valid) == len(records)
                      and all(r == valid[0] for r in valid),
        'valid_count': len(valid),
        'invalid_count': len(records) - len(valid),
        'unique_rankings': len({tuple(r) for r in valid}),
    }


def main(runs_per_model: int = RUNS_PER_MODEL, append: bool = False):
    if runs_per_model < 1:
        raise ValueError('runs_per_model must be >= 1')
    os.makedirs(RESULTS_DIR, exist_ok=True)
    models = list_models()
    if not models:
        raise ValueError('No models configured')
    dummy_products = [{'id': pid} for pid in PRODUCT_IDS]
    clean_message = build_clean_message()
    total = len(models) * runs_per_model

    prompt_hash = hashlib.sha256(clean_message.encode('utf-8')).hexdigest()
    prior_results = {}
    if append and os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding='utf-8') as f:
            previous = json.load(f)
        if previous.get('meta', {}).get('mode') != 'html_pages':
            raise ValueError('Cannot append: existing baseline is not HTML-page mode')
        prior_hash = previous.get('meta', {}).get('prompt_sha256')
        if prior_hash != prompt_hash:
            raise ValueError('Cannot append: HTML prompt changed since previous baseline')
        prior_results = previous.get('results', {})
        if not isinstance(prior_results, dict):
            raise ValueError('Existing results must be an object')
        _log(f'Loaded prior runs for {len(prior_results)} models')

    _log(f'Models: {len(models)} | New runs/model: {runs_per_model} | '
         f'Total API calls: {total} | Workers: {min(MAX_WORKERS, len(models))} | Append: {append}')
    if runs_per_model < 10:
        _log('Note: a small clean sample cannot establish that rank #1 is permanently stable.')

    grouped = {model: [] for model in models}

    # Within each model, keep requests sequential to avoid simultaneous calls
    # to the same model; different models still run in parallel.
    def run_model(model):
        return [run_one(model, i + 1, clean_message, dummy_products)
                for i in range(runs_per_model)]

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(models))) as pool:
        futures = {pool.submit(run_model, model): model for model in models}
        for future in as_completed(futures):
            model = futures[future]
            grouped[model] = future.result()
            _log(f'  [{model}] {len(grouped[model])}/{runs_per_model} done')

    results = {}
    for model in models:
        prev = prior_results.get(model, {}).get('runs', []) if append else []
        if not isinstance(prev, list):
            raise ValueError(f'Invalid prior runs list for {model}')
        # Preserve prior records verbatim; normalized new records remain compatible.
        new = [
            {key: record[key] for key in ('ranking', 'ts', 'status', 'error') if key in record}
            for record in grouped[model]
        ]
        all_records = prev + new
        results[model] = {'runs': all_records, **_summarize(all_records)}

    # Preserve results for models no longer in list_models() when appending.
    if append:
        for model, data in prior_results.items():
            if model not in results:
                results[model] = data

    counts = {model: len(data.get('runs', [])) for model, data in results.items()}
    output = {
        'meta': {
            'runs_per_model': counts[models[0]] if len(set(counts.values())) == 1 else None,
            'run_counts_by_model': counts,
            'new_runs_per_model': runs_per_model,
            'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'mode': 'html_pages',
            'prompt_sha256': prompt_hash,
        },
        'results': results,
    }

    if not append:
        backup = _backup_existing()
        if backup:
            _log(f'Prior baseline backed up → {backup}')
    _atomic_write_json(OUTPUT_PATH, output)
    _log(f'\nSaved → {OUTPUT_PATH}')
    _log('\n--- Consistency summary ---')
    for model, data in results.items():
        mark = '✓' if data.get('consistent') else '–'
        _log(f"  {mark} {model:<25} {data.get('unique_rankings', '?')} unique ranking(s), "
             f"{data.get('valid_count', '?')} valid, {data.get('invalid_count', '?')} invalid")
    return output


if __name__ == '__main__':
    args = sys.argv[1:]
    append = '--append' in args
    args = [a for a in args if a != '--append']
    if len(args) > 1:
        raise SystemExit('Usage: python3 run_website_baseline.py [runs_per_model] [--append]')
    runs = int(args[0]) if args else RUNS_PER_MODEL
    main(runs, append=append)
