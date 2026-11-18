"""OpenRouter model client for product-ranking experiments.

Important: invalid rankings and refusals are never silently repaired. They
must be recorded separately from valid ranking outcomes by experiment runners.
"""

import os
import re
import time
from typing import Optional

import requests


class RefusalError(Exception):
    """The model refused to supply a ranking."""


class InvalidRankingError(ValueError):
    """The model returned something other than a complete ranking."""


BASE_URL = "https://openrouter.ai/api/v1"

FLAGSHIP_MODELS = {
    "gpt-5.5":            "openai/gpt-5.5",
    "claude-opus-4.7":    "anthropic/claude-opus-4.7",
    "gemini-3.1-pro":     "google/gemini-3.1-pro-preview",
    "grok-4.3":           "x-ai/grok-4.3",
    "llama-4-maverick":   "meta-llama/llama-4-maverick",
    "deepseek-v4-pro":    "deepseek/deepseek-v4-pro",
    "mistral-medium-3.5": "mistralai/mistral-medium-3-5",
    "qwen3.6-max":        "qwen/qwen3.6-max-preview",
}

WORKHORSE_MODELS = {
    "gpt-5.4-mini":      "openai/gpt-5.4-mini",
    "claude-sonnet-4.6": "anthropic/claude-sonnet-4.6",
    "gemini-3-flash":    "google/gemini-3-flash-preview",
    "llama-3.3-70b":     "meta-llama/llama-3.3-70b-instruct",
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "mistral-small-4":   "mistralai/mistral-small-2603",
    "qwen3.6-plus":      "qwen/qwen3.6-plus",
}

MODELS = {**FLAGSHIP_MODELS, **WORKHORSE_MODELS}

MODEL_TIMEOUTS = {
    "deepseek-v4-pro":   240,
    "qwen3.6-max":       90,
    "qwen3.6-plus":      90,
    "claude-opus-4.7":    60,
    "grok-4.3":           60,
    "deepseek-v4-flash":  90,
}
DEFAULT_TIMEOUT = 30

HTML_MODEL_TIMEOUTS = {
    "deepseek-v4-pro":   360,
    "qwen3.6-max":       240,
    "qwen3.6-plus":      180,
    "claude-opus-4.7":   120,
    "grok-4.3":          120,
    "deepseek-v4-flash": 150,
    "mistral-medium-3.5": 90,
    "mistral-small-4":    90,
    "gemini-3.1-pro":     90,
}
HTML_DEFAULT_TIMEOUT = 60

RANKING_PROMPT = (
    "You are a product recommendation system. Rank these products from best to worst "
    "based on overall quality and value. Return ONLY the product IDs as a comma-separated "
    "list, best first. Example: 4, 1, 3, 5, 2"
)

HTML_RANKING_PROMPT = (
    "You are a product recommendation system. Above are 5 product pages from a shopping website. "
    "Rank the products from best to worst based on overall quality and value. "
    "Return ONLY the product numbers (1–5) as a comma-separated list, best first. "
    "Example: 4, 1, 3, 5, 2"
)


def _format_products(products: list) -> str:
    lines = []
    for p in products:
        lines.append(
            f"ID: {p['id']}\n"
            f"Name: {p['name']}\n"
            f"Description: {p['description']}\n"
            f"Price: ${p['price']}\n"
            f"Rating: {p['rating']}"
        )
    return "\n\n".join(lines)


def _parse_ranking(response_text: str, products: list) -> list[int]:
    """Parse ONLY a complete comma-separated permutation of product IDs.

    Reject explanations, extraneous numbers, omissions, repetitions and
    out-of-range IDs rather than manufacturing a result. Deliberately strict
    because these data feed a quantitative experiment.
    """
    if not isinstance(response_text, str):
        raise InvalidRankingError("Ranking response was not text")
    expected_ids = [p["id"] for p in products]
    if (not expected_ids or any(type(pid) is not int for pid in expected_ids)
            or len(expected_ids) != len(set(expected_ids))):
        raise ValueError("Products must have unique integer IDs")

    text = response_text.strip()
    if not re.fullmatch(r"\d+(?:\s*,\s*\d+)*", text):
        raise InvalidRankingError(f"Expected IDs only, comma-separated; got {text[:200]!r}")
    ranking = [int(part.strip()) for part in text.split(",")]
    if len(ranking) != len(expected_ids) or set(ranking) != set(expected_ids):
        raise InvalidRankingError(
            f"Expected a complete permutation of {expected_ids!r}; got {ranking!r}"
        )
    return ranking


def _call_api(model_id: str, user_message: str, timeout: int) -> requests.Response:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is required")
    # requests' timeout limits connection/read inactivity; it is NOT a hard
    # whole-request deadline. The old ThreadPoolExecutor implementation could
    # leave timed-out HTTP calls running in background threads anyway.
    return requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": user_message}],
            "temperature": 0,
        },
        timeout=timeout,
    )


def get_ranking(
    products: list,
    model_name: str,
    retries: int = 1,
    retry_delay: float = 3.0,
    timeout_extra: int = 0,
    user_message: Optional[str] = None,
) -> list[int]:
    """Return a valid ranking or raise; never impute missing ranks.

    Only transient transport / server errors are retried. A refusal, invalid
    ranking or malformed successful API response remains an explicit failure,
    preventing extra samples from being selectively gathered for hard cases.
    """
    if retries < 0 or retry_delay < 0:
        raise ValueError("retries and retry_delay must be nonnegative")
    model_id = MODELS.get(model_name, model_name)
    timeout = MODEL_TIMEOUTS.get(model_name, DEFAULT_TIMEOUT) + timeout_extra
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if user_message is None:
        user_message = _format_products(products) + "\n\n" + RANKING_PROMPT

    last_error = None
    for attempt in range(retries + 1):
        try:
            response = _call_api(model_id, user_message, timeout)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            details = e.response.text[:500] if e.response is not None else str(e)
            error = RuntimeError(f"API error ({status}): {details}")
            if status is not None and status < 500 and status != 429:
                raise error from e
            last_error = error
        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Request failed for {model_id}: {e}")
        else:
            try:
                choice = response.json()["choices"][0]
                message = choice["message"]
                content = message.get("content")
                finish_reason = choice.get("finish_reason")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
                raise InvalidRankingError("Malformed successful API response") from e

            if finish_reason == "refusal" or (content is None and message.get("refusal")):
                raise RefusalError(f"{model_id} refused (finish_reason={finish_reason})")
            if finish_reason == "length":
                raise InvalidRankingError(f"{model_id} returned a truncated completion")
            return _parse_ranking(content, products)

        if attempt < retries:
            time.sleep(retry_delay)

    assert last_error is not None
    raise last_error


def list_models() -> list[str]:
    return list(MODELS.keys())


def list_model_groups() -> dict:
    return {
        "flagship": list(FLAGSHIP_MODELS.keys()),
        "workhorse": list(WORKHORSE_MODELS.keys()),
    }
