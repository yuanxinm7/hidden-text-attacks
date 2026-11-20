# The Dumbest Attacks Work Best: Hidden Text and AI Shopping Agents

This repository contains the code and data for a Stanford research project, advised by Andy Hall, investigating whether hidden instructions in product listings can change how language models rank shopping results. Experiments took place in May 2026.

**[Read the research article](https://yuanxinm7.github.io/hidden-text-attacks/)**

## What this is

The experiments ask models to rank five fictional headphone products with plausible prices, specifications, and ratings. One product's listing is modified to include an instruction hidden in a form such as an HTML comment, CSS-hidden text, or zero-width characters. The model's subsequent ranking is compared with its clean behavior.

Two input formats are studied:

- **JSON:** Structured product records, representative of information passed through shopping tools and APIs.
- **HTML:** Source HTML for a simulated Walmart-style product page in `mock-walmart/`.

The project tested 23 models through OpenRouter; 15 were included in the principal comparison.

## Repo layout

| Path | Purpose |
|---|---|
| `attacks/payloads.py` | Eleven hiding strategies and additional more direct injection variants |
| `data/products.json` | Five fictional product records |
| `mock-walmart/` | Simulated product-page HTML |
| `api/models.py` | Model definitions and OpenRouter requests |
| `app.py` | Local Flask demo |
| `app_public.py` | Backend entry point for the public deployment |
| `runner.py` | Helpers for JSON experiments and clean baselines |
| `run_html_attacks.py` | Updated repeated-measures HTML experiment runner (not the May 2026 single-run runner) |
| `run_website_baseline.py` | Clean HTML baseline collection |
| `run_targeted_validation.py` | Additional validation for resistant models or variable baselines (`--mode html` or `--mode json`) |
| `results/` | Experiment outputs and call logs |

## Results

- `results/baseline_*.json` contains JSON clean baselines. `results/html_baseline_website_2026-05-31.json` contains the historical HTML clean baseline used by targeted validation; `results/website_baseline.json` is a separate website-baseline file. Baseline repetition counts were five per model for JSON and twenty for HTML, with forty for Mistral Medium.
- `results/run_*.json` contains the primary JSON attack sweeps.
- Historical `results/run_html_*.json` files (including `run_html_recovered_product1_from_calls3.json`) contain the original exploratory, single-run HTML sweep results, organized by targeted product. These files are **not** output from the current `run_html_attacks.py`.
- `results/targeted_validation_*.json` contains additional validation trials.
- `results/calls2.log` and `results/calls3.log` contain historical JSON and HTML model-call logs, respectively. The **updated** HTML runner writes a separate `results/html_calls.jsonl` log and timestamped `results/run_html_YYYY-MM-DD_HH-MM-SS_UTC_productN.json` results. New targeted-validation runs create `results/targeted_validation_calls_<run-id>_<mode>.jsonl`, leaving `calls2.log` and `calls3.log` untouched.

For stable baselines, a successful ranking movement means the targeted product rises above its clean position. For variable clean rankings, the analysis considers improvement beyond the baseline frequency of that ranking. Products consistently ranked first are excluded from upward-movement calculations because they cannot improve further.

## HTML experiment versions and provenance

**May 2026 published study (exploratory).** The article and the historical HTML output files describe an earlier runner: the primary HTML sweep evaluated each attack **once per model–target-product combination**, against previously collected clean baselines. For stable baselines, an upward movement relative to the clean ranking counted as success; for variable baselines, the article considers improvement beyond the clean ranking frequency. Selected models also received separate targeted-validation runs. The historical HTML outputs and `results/calls3.log` are the source records for these published observations.

**Current `run_html_attacks.py` (updated after May 2026).** This runner implements a *different* protocol: 12 repeated clean requests per model and 8 requests per attack/model by default, shuffled execution, a one-sided permutation test for lower mean attack rank, and Benjamini–Hochberg correction over model–attack comparisons for each target-product run. It has **no neutral/placebo payload condition**. It writes `results/html_calls.jsonl` and distinct timestamped `_UTC_productN.json` files. The current script **cannot exactly reproduce the May 2026 single-run procedure**, and its statistical tests have **not retrospectively validated** the historical observations.

**Combining-character encoding caveat.** Historical May 2026 targeted-validation runs using the extended `combining_inject` attack may have embedded only a prefix of the intended message when the product description was shorter than the bitstream. The main original HTML sweep did not include `combining_inject`. The current encoder appends remaining accent bits and has a round-trip regression test; this fix must not be projected backward onto historical runs.

**Updated-runner sample and testing rules.** The HTML runner requests 12 clean and 8 attack calls by default, but now tests comparisons with at least 10 valid clean and 6 valid attack rankings (configurable with `--min-clean` and `--min-attack`). It reports attempted/valid/failed counts, failure rates, and flags differences in failure rates. Condition-dependent failures can bias valid-only comparisons even if thresholds are met; these flags require inspection rather than automatic statistical correction. The prespecified BH testing family is all model × attack comparisons **within a target product**. If highlighting the strongest findings across multiple products, apply study-wide correction or label the selection as exploratory. The original May 2026 sweep is not retroactively subject to these new tests. Neutral/placebo controls remain a proposed next experiment, not part of the published dataset.

Do not combine the two output schemas or interpret historical single-run success counts as permutation-test findings. To reproduce the historical workflow exactly, obtain the original runner revision from version control if available; the current runner is for new experiments. Original research results in `results/` should be preserved as-is.

## Run it yourself

```bash
pip install -r requirements.txt

export OPENROUTER_API_KEY=your_key_here

# Local web demo
python app.py

# Extra runs on resistant models, HTML format
python run_targeted_validation.py --mode html --reps 10
```

### Web demo configuration

The interactive demo is separate from the research experiment runners. A demo cell shows an individual observed ranking change, whereas the published findings use repeated clean baselines and the study's stated evaluation method.

The Flask backends recognize these environment variables:

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | API credentials for model requests |
| `LIVE_API_ENABLED=1` | Enables live model execution; off by default |
| `APP_ADMIN_TOKEN` | Secret supplied through `X-Admin-Token` for protected POST endpoints; do not embed it in public client-side JavaScript |
| `PERSIST=1` | Enables writing demo snapshots and logs under `results/demo/`; off by default |
| `ENABLE_BATCH=1` | Enables the batch endpoint (also requires live execution and admin authorization) |
| `JSON_BASELINE_FILE` | Optional path selecting the JSON baseline file for the dashboard |
| `HTML_BASELINE_FILE` | Optional path selecting the HTML baseline file for the dashboard |

A standard local launch is `python app.py`; the deployed public app uses `app_public.py`. To make live requests through protected API routes, configure `LIVE_API_ENABLED=1` and `APP_ADMIN_TOKEN` on the server and send the token only from a trusted client or private proxy.

If multiple baseline files contain overlapping models, explicitly configure the corresponding baseline file instead of relying on an implicit merge. Demo persistence does not overwrite the study's original results in `results/`.

Model API requests incur costs, and regenerated rankings may differ. Model versions used in May 2026 might also no longer be available.

## Limits

The study did not include a placebo condition, so the results do not separately isolate the effect of an instruction's meaning from the effect of adding text. Each attack in the main HTML sweep was evaluated once for each model–product combination, with extra runs for the most resistant models. See [“What I'm not sure about yet”](https://yuanxinm7.github.io/hidden-text-attacks/#what-im-not-sure-about-yet) in the article for additional qualifications.


