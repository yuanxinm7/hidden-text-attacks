[README.md](https://github.com/user-attachments/files/35011163/README.md)
# The Dumbest Attacks Work Best: Hidden Text and AI Shopping Agents

Code and data for my study of whether hidden text on a product page can change how AI models rank products. Stanford, advised by Andy Hall. Tests ran in May 2026.

**[Read the full research article](https://yuanxinm7.github.io/hidden-text-attacks/)**

## What this is

Five fake headphone listings with realistic specs, prices, and ratings. A model ranks them. Then one listing gets a hidden instruction (in an HTML comment, invisible CSS, zero-width characters, etc.), and I check whether that product's rank moved.

Two formats:

- **JSON:** Clean structured product data, like what shopping tools and APIs pass to a model.
- **HTML:** The raw source of a Walmart-style product page (`mock-walmart/`).

23 models through OpenRouter, 15 of them in the main comparison.

## Repo layout

| Path | What's in it |
|---|---|
| `attacks/payloads.py` | The 11 hiding techniques, plus the extra blunter injections |
| `data/products.json` | The five products |
| `mock-walmart/` | The HTML product pages |
| `api/models.py` | Model list and calls through OpenRouter |
| `app.py` | Local web app for running and viewing tests |
| `runner.py` | JSON experiment helpers (single tests, baselines) |
| `run_html_attacks.py` | HTML attack sweep |
| `run_website_baseline.py` | Clean HTML baselines |
| `run_targeted_validation.py` | Extra runs on the most resistant models and noisy baselines (`--mode html` or `--mode json`) |
| `results/` | Raw results and call logs (see below) |

## Results

- `results/baseline_*.json`, `results/website_baseline.json`: clean rankings (5 runs per model in JSON, 20 in HTML, 40 for Mistral Medium)
- `results/run_*.json`: main JSON sweeps
- `results/run_html_*.json`: main HTML sweep, one file per product
- `results/targeted_validation_*.json`: extra runs
- `results/calls2.log` (JSON) and `results/calls3.log` (HTML): every logged model call

For stable rankings, a hit means the product moved above its clean baseline position. For rankings that wobble, only the increase over the clean baseline rate counts. Products already locked at #1 are excluded because they can't move higher.

## Run it yourself

```bash
pip install -r requirements.txt

export OPENROUTER_API_KEY=your_key_here

# Web app
python app.py

# Extra runs on resistant models, HTML format
python run_targeted_validation.py --mode html --reps 10
```

Model calls cost money and model outputs change over time, so reruns won't match exactly. Some model versions used in May 2026 may no longer be available.

## Limits

There was no placebo condition, so some movement could come from the added text itself rather than the instruction. The main HTML sweep ran each attack once per model and product; the toughest models got extra runs. See ["What I'm not sure about yet"](https://yuanxinm7.github.io/hidden-text-attacks/#what-im-not-sure-about-yet) in the write-up.
