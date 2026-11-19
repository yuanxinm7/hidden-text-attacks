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
| `run_html_attacks.py` | HTML attack experiments |
| `run_website_baseline.py` | Clean HTML baseline collection |
| `run_targeted_validation.py` | Additional validation for resistant models or variable baselines (`--mode html` or `--mode json`) |
| `results/` | Experiment outputs and call logs |

## Results

- `results/baseline_*.json` and `results/website_baseline.json` contain clean rankings. Baseline repetition counts were five per model for JSON and twenty for HTML, with forty for Mistral Medium.
- `results/run_*.json` contains the primary JSON attack sweeps.
- `results/run_html_*.json` contains the main HTML sweep results, organized by targeted product.
- `results/targeted_validation_*.json` contains additional validation trials.
- `results/calls2.log` and `results/calls3.log` contain JSON and HTML model-call logs, respectively.

For stable baselines, a successful ranking movement means the targeted product rises above its clean position. For variable clean rankings, the analysis considers improvement beyond the baseline frequency of that ranking. Products consistently ranked first are excluded from upward-movement calculations because they cannot improve further.

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
