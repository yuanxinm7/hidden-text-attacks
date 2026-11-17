import os
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

class RefusalError(Exception):
    pass


BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = os.environ["OPENROUTER_API_KEY"]

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
    "qwen3.6-max":        90,
    "qwen3.6-plus":       90,
    "claude-opus-4.7":    60,
    "grok-4.3":           60,
    "deepseek-v4-flash":  90,
}
DEFAULT_TIMEOUT = 30

# HTML pages are much larger — use these instead for html-mode calls
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
    valid_ids = {p["id"] for p in products}
    # extract all integers from the response, preserving order, deduplicating
    found = []
    seen = set()
    for match in re.finditer(r"\b(\d+)\b", response_text):
        num = int(match.group(1))
        if num in valid_ids and num not in seen:
            found.append(num)
            seen.add(num)
    # append any valid IDs the model omitted, so the list is always complete
    for pid in valid_ids:
        if pid not in seen:
            found.append(pid)
    return found


def _call_api(model_id: str, user_message: str, timeout: int) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": user_message}],
            "temperature": 0,
        },
        timeout=timeout,
    )


def get_ranking(products: list, model_name: str, retries: int = 1, retry_delay: float = 3.0, timeout_extra: int = 0, user_message: str = None) -> list[int]:
    model_id = MODELS.get(model_name, model_name)
    timeout = MODEL_TIMEOUTS.get(model_name, DEFAULT_TIMEOUT) + timeout_extra
    if user_message is None:
        user_message = _format_products(products) + "\n\n" + RANKING_PROMPT

    last_error = None
    for attempt in range(retries + 1):
        try:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_call_api, model_id, user_message, timeout)
            try:
                response = future.result(timeout=timeout)
            except FuturesTimeoutError:
                raise RuntimeError(f"Hard deadline of {timeout}s exceeded for {model_id}")
            finally:
                executor.shutdown(wait=False)

            response.raise_for_status()
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") == "refusal" or choice["message"]["content"] is None:
                raise RefusalError(f"{model_id} refused to respond (finish_reason: {choice.get('finish_reason')})")
            content = choice["message"]["content"]
            return _parse_ranking(content, products)
        except requests.exceptions.Timeout as e:
            last_error = RuntimeError(f"Request to {model_id} timed out.")
        except requests.exceptions.HTTPError as e:
            if response.status_code < 500:
                raise RuntimeError(f"API error ({response.status_code}): {response.text}") from e
            last_error = RuntimeError(f"API error ({response.status_code}): {response.text}")
        except requests.exceptions.RequestException as e:
            last_error = RuntimeError(f"Request failed: {e}")

        if attempt < retries:
            time.sleep(retry_delay)

    raise last_error


def list_models() -> list[str]:
    return list(MODELS.keys())


def list_model_groups() -> dict:
    return {
        "flagship":  list(FLAGSHIP_MODELS.keys()),
        "workhorse": list(WORKHORSE_MODELS.keys()),
    }
