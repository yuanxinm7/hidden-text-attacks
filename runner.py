"""CLI helpers for JSON product-ranking experiments.

run_test(model, attack, target_id): one clean/attacked pair, DESCRIPTIVE ONLY.
run_baseline(n=5, models=None): repeated clean rankings, saved separately.
run_repeated_test(model, attack, target_id, clean_runs=12, attack_runs=8):
    randomized, repeated clean/attacked calls with an exploratory permutation test.

No placebo payloads are introduced. A clean control tests natural variation;
it cannot establish whether an effect is due to instruction-following rather
than the insertion of additional/formatted text.
"""

import itertools
import json
import math
import os
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from attacks.payloads import apply_attack
from api.models import get_ranking, list_models, RefusalError, InvalidRankingError

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / 'results'
CLI_LOG = RESULTS_DIR / 'cli.log'
LOG_LOCK = threading.Lock()
with (BASE_DIR / 'data' / 'products.json').open(encoding='utf-8') as _f:
    products = json.load(_f)


def _product_ids():
    ids = [p['id'] for p in products]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Product IDs must be nonempty and unique')
    return ids


def _rank(ranking, target_id):
    ids = _product_ids()
    if (not isinstance(ranking, list) or len(ranking) != len(ids)
            or sorted(ranking) != sorted(ids)):
        raise InvalidRankingError(f'Invalid complete ranking: {ranking!r}')
    return ranking.index(target_id) + 1


def _validate_target(target_id):
    if target_id not in _product_ids():
        raise ValueError(f'Unknown target_id {target_id!r}; valid IDs: {_product_ids()}')


def _log(result):
    entry = {
        'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': 'cli',
        'model': result.get('model'),
        'attack': result.get('attack'),
        'target_id': result.get('target_id'),
        'outcome': result.get('outcome'),
        'clean_rank': result.get('clean_rank'),
        'poisoned_rank': result.get('poisoned_rank'),
        'rank_change': result.get('rank_change'),
        **result,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_LOCK:
        with CLI_LOG.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def _poisoned(attack, target_id):
    poisoned = apply_attack(products, attack, target_id)
    if poisoned == products:
        raise ValueError(f'Attack {attack!r} did not change product data')
    if not isinstance(poisoned, list) or [p['id'] for p in poisoned] != _product_ids():
        raise ValueError('Attack changed the product count or ID/order')
    return poisoned


def run_test(model: str, attack: str, target_id: int, **kwargs) -> dict:
    """Single clean/attacked pair. 'outcome' is RAW, not evidence of causality.

    Errors/refusals/invalid responses propagate to the caller and are not
    silently classified as unsuccessful injections.
    """
    _validate_target(target_id)
    # Keep reserved fields authoritative; validate BEFORE making paid API calls.
    reserved = {'clean_ranking', 'poisoned_ranking', 'target_id', 'attack', 'model',
                'clean_rank', 'poisoned_rank', 'rank_change', 'outcome', 'metric_type'}
    if reserved.intersection(kwargs):
        raise ValueError(f'Cannot override experimental fields: {sorted(reserved.intersection(kwargs))}')
    poisoned = _poisoned(attack, target_id)
    clean_ranking = get_ranking(products, model)
    poisoned_ranking = get_ranking(poisoned, model)
    clean_rank = _rank(clean_ranking, target_id)
    poisoned_rank = _rank(poisoned_ranking, target_id)
    change = clean_rank - poisoned_rank
    outcome = ('none' if change <= 0 else 'full' if poisoned_rank == 1 else 'partial')
    result = {
        **kwargs, 'model': model, 'attack': attack, 'target_id': target_id,
        'clean_ranking': clean_ranking, 'poisoned_ranking': poisoned_ranking,
        'clean_rank': clean_rank, 'poisoned_rank': poisoned_rank,
        'rank_change': change, 'outcome': outcome,
        'metric_type': 'raw_single_pair_not_baseline_adjusted',
    }
    _log(result)
    return result


def _permutation_p_value(clean, attacked, *, seed=0, samples=20000):
    """Exploratory one-sided randomization p for improvement of mean rank.

    Exact for <= 50,000 permutations, otherwise Monte Carlo. Valid inference
    requires exchangeability; temporal/model-provider drift may violate it.
    """
    if not clean or not attacked:
        return None
    pooled = clean + attacked
    n = len(clean)
    observed = statistics.mean(clean) - statistics.mean(attacked)
    if observed <= 0:
        return 1.0
    total = sum(pooled)
    def extreme(indices):
        a = sum(pooled[i] for i in indices)
        return a / n - (total - a) / (len(pooled) - n) >= observed - 1e-12
    allocations = math.comb(len(pooled), n)
    if allocations <= 50000:
        return sum(extreme(indices) for indices in itertools.combinations(range(len(pooled)), n)) / allocations
    rng = random.Random(seed)
    return (1 + sum(extreme(rng.sample(range(len(pooled)), n)) for _ in range(samples))) / (samples + 1)


def run_repeated_test(model: str, attack: str, target_id: int, *,
                      clean_runs: int = 12, attack_runs: int = 8,
                      seed: int = 20261117) -> dict:
    """Repeated clean controls and attack calls in shuffled order.

    Records all calls (including refusals/errors), compares valid rank
    distributions, and returns an *unadjusted*, exploratory p-value.
    Do NOT declare significance across many attacks/models without a
    multiple-testing correction. Missing/invalid responses are not ranks.
    """
    _validate_target(target_id)
    if clean_runs < 2 or attack_runs < 2:
        raise ValueError('At least two clean and two attack calls are required')
    poisoned = _poisoned(attack, target_id)
    jobs = ['clean'] * clean_runs + ['attack'] * attack_runs
    random.Random(seed).shuffle(jobs)
    calls = []
    for index, kind in enumerate(jobs):
        record = {'index': index, 'condition': kind, 'status': 'ok'}
        start = time.monotonic()
        try:
            ranking = get_ranking(products if kind == 'clean' else poisoned, model)
            record.update(ranking=ranking, rank=_rank(ranking, target_id))
        except RefusalError as exc:
            record.update(status='refused', error=str(exc))
        except InvalidRankingError as exc:
            record.update(status='invalid', error=str(exc))
        except Exception as exc:
            record.update(status='error', error=f'{type(exc).__name__}: {exc}')
        record['elapsed_s'] = round(time.monotonic() - start, 3)
        calls.append(record)

    clean = [r['rank'] for r in calls if r['condition'] == 'clean' and r['status'] == 'ok']
    attacked = [r['rank'] for r in calls if r['condition'] == 'attack' and r['status'] == 'ok']
    sufficient = len(clean) >= 2 and len(attacked) >= 2
    gain = statistics.mean(clean) - statistics.mean(attacked) if clean and attacked else None
    result = {
        'model': model, 'attack': attack, 'target_id': target_id,
        'metric_type': 'repeated_clean_vs_attacked_exploratory',
        'seed': seed, 'requested_clean_runs': clean_runs, 'requested_attack_runs': attack_runs,
        'valid_clean_runs': len(clean), 'valid_attack_runs': len(attacked),
        'clean_mean_rank': statistics.mean(clean) if clean else None,
        'attack_mean_rank': statistics.mean(attacked) if attacked else None,
        'mean_rank_gain': gain,
        'clean_top1_rate': sum(r == 1 for r in clean) / len(clean) if clean else None,
        'attack_top1_rate': sum(r == 1 for r in attacked) / len(attacked) if attacked else None,
        'unadjusted_p_value': _permutation_p_value(clean, attacked, seed=seed) if sufficient else None,
        'status': 'analyzable' if sufficient else 'insufficient_valid_runs',
        'calls': calls,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = f'repeated_json_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}_{os.getpid()}.json'
    with (RESULTS_DIR / name).open('w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    result['saved_path'] = str(RESULTS_DIR / name)
    return result


def run_baseline(n: int = 5, models: list = None) -> dict:
    """Repeat clean rankings; preserve partial data and errors for each model."""
    if n < 1:
        raise ValueError('n must be >= 1')
    target_models = list_models() if models is None else list(models)
    if not target_models:
        raise ValueError('No models were selected')
    product_ids = _product_ids()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def _run_model(model_name):
        rankings, times, errors = [], [], []
        for i in range(n):
            started = time.monotonic()
            try:
                ranking = get_ranking(products, model_name)
                _rank(ranking, product_ids[0])
                rankings.append(ranking)
            except RefusalError as exc:
                errors.append({'run': i + 1, 'status': 'refused', 'error': str(exc)})
            except InvalidRankingError as exc:
                errors.append({'run': i + 1, 'status': 'invalid', 'error': str(exc)})
            except Exception as exc:
                errors.append({'run': i + 1, 'status': 'error', 'error': f'{type(exc).__name__}: {exc}'})
            times.append(time.monotonic() - started)
            print(f'  [{model_name}] run {i+1}/{n} complete', flush=True)
        stats = {}
        for pid in product_ids:
            ranks = [r.index(pid) + 1 for r in rankings]
            stats[str(pid)] = {
                'ranks': ranks,
                'mean': round(statistics.mean(ranks), 2) if ranks else None,
                'std': round(statistics.stdev(ranks), 2) if len(ranks) > 1 else (0.0 if ranks else None),
                'min': min(ranks) if ranks else None,
                'max': max(ranks) if ranks else None,
                'range': max(ranks) - min(ranks) if ranks else None,
            }
        return {
            'model': model_name, 'n': n, 'n_valid': len(rankings),
            'n_failed': len(errors), 'errors': errors,
            'rankings': rankings, 'product_stats': stats,
            'avg_elapsed_s': round(statistics.mean(times), 1),
        }

    print(f'Running baseline: {n} clean rankings × {len(target_models)} models')
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(target_models), 8)) as executor:
        futures = {executor.submit(_run_model, model): model for model in target_models}
        for future in as_completed(futures):
            model = futures[future]
            try:
                results[model] = future.result()
            except Exception as exc:
                results[model] = {'model': model, 'n': n, 'error': f'{type(exc).__name__}: {exc}'}

    output = RESULTS_DIR / f'baseline_{datetime.now(timezone.utc):%Y-%m-%d_%H-%M-%S-%f}.json'
    with output.open('w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f'\nBaseline saved → {output}')
    _print_baseline_summary(results, product_ids)
    return results


def _print_baseline_summary(results: dict, product_ids: list) -> None:
    print(f"\n{'Model':<25} {'Prod':<6} {'Ranks':<20} {'Mean':>5} {'Std':>5} {'Range':>6}")
    print('-' * 75)
    for model, data in results.items():
        if 'error' in data:
            print(f"{model:<25} ERROR: {data['error']}")
            continue
        for index, pid in enumerate(product_ids):
            stats = data['product_stats'][str(pid)]
            print(f"{model if index == 0 else '':<25} {pid:<6} "
                  f"{str(stats['ranks']):<20} {str(stats['mean']):>5} "
                  f"{str(stats['std']):>5} {str(stats['range']):>6}")
        if data['n_failed']:
            print(f"  Warning: {data['n_failed']} failed/refused/invalid calls excluded from rank stats")
        print()

