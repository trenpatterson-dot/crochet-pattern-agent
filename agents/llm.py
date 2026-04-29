"""
Shared LLM client — routes to Anthropic, OpenAI, or Ollama based on LLM_PROVIDER env var.
"""

import os
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from dotenv import dotenv_values

# Read .env values directly — bypasses any env-var caching issues
_env = dotenv_values(Path(__file__).parent.parent / ".env")

def _get(key: str, default: str = "") -> str:
    return _env.get(key) or os.getenv(key, default)

LLM_PROVIDER     = _get("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_MODEL  = _get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
OPENAI_MODEL     = _get("OPENAI_MODEL", "gpt-5-mini")
OPENAI_API_KEY   = _get("OPENAI_API_KEY")
OLLAMA_MODEL     = _get("OLLAMA_MODEL", "llama3.2:latest")
OLLAMA_BASE_URL  = _get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
ANTHROPIC_TIMEOUT_SECONDS = float(_get("ANTHROPIC_TIMEOUT_SECONDS", "90"))
OPENAI_TIMEOUT_SECONDS = float(_get("OPENAI_TIMEOUT_SECONDS", "25"))


def chat(system: str, user_msg: str, use_web_search: bool = False, max_tokens: int = 4096) -> str:
    if LLM_PROVIDER == "anthropic":
        return _anthropic(system, user_msg, use_web_search, max_tokens)
    if LLM_PROVIDER == "openai":
        return _openai(system, user_msg, max_tokens)
    return _ollama(system, user_msg, max_tokens)


def provider_debug_summary() -> dict:
    return {
        "llm_provider": LLM_PROVIDER,
        "anthropic_model": ANTHROPIC_MODEL,
        "openai_model": OPENAI_MODEL,
        "ollama_model": OLLAMA_MODEL,
        "openai_configured": bool(OPENAI_API_KEY),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "openai_timeout_seconds": OPENAI_TIMEOUT_SECONDS,
        "anthropic_timeout_seconds": ANTHROPIC_TIMEOUT_SECONDS,
    }


def _anthropic(system: str, user_msg: str, use_web_search: bool, max_tokens: int) -> str:
    import time
    import anthropic
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=ANTHROPIC_TIMEOUT_SECONDS,
    )
    kwargs = dict(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    if use_web_search:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]

    for attempt in range(3):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.messages.create, **kwargs)
                response = future.result(timeout=ANTHROPIC_TIMEOUT_SECONDS)
            return "".join(b.text for b in response.content if b.type == "text")
        except anthropic.RateLimitError:
            wait = 60  # always wait a full minute for rate limit to reset
            print(f"    [LLM] Rate limit — waiting {wait}s (attempt {attempt+1}/3)...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code == 529:
                wait = 30
                print(f"    [LLM] API overloaded — waiting {wait}s (attempt {attempt+1}/3)...")
                time.sleep(wait)
            else:
                raise
        except FutureTimeoutError:
            if use_web_search:
                print(
                    f"    [LLM] Anthropic call exceeded {ANTHROPIC_TIMEOUT_SECONDS:.0f}s. "
                    "Falling back to Ollama."
                )
                return _ollama(system, user_msg, max_tokens)
            raise RuntimeError(
                f"Anthropic call exceeded {ANTHROPIC_TIMEOUT_SECONDS:.0f}s."
            )
        except Exception as e:
            if use_web_search:
                print(f"    [LLM] Anthropic web search failed or timed out ({e}). Falling back to Ollama.")
                return _ollama(system, user_msg, max_tokens)
            raise
    raise RuntimeError("Anthropic API failed after 3 attempts")


def _openai(system: str, user_msg: str, max_tokens: int) -> str:
    from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        timeout=OPENAI_TIMEOUT_SECONDS,
    )
    kwargs = dict(
        model=OPENAI_MODEL,
        instructions=system,
        input=user_msg,
        max_output_tokens=max_tokens,
    )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.responses.create, **kwargs)
            response = future.result(timeout=OPENAI_TIMEOUT_SECONDS)
    except FutureTimeoutError as exc:
        raise RuntimeError(
            f"OpenAI call exceeded {OPENAI_TIMEOUT_SECONDS:.0f}s."
        ) from exc
    except APITimeoutError as exc:
        raise RuntimeError(
            f"OpenAI request timed out after {OPENAI_TIMEOUT_SECONDS:.0f}s."
        ) from exc
    except APIConnectionError as exc:
        raise RuntimeError(f"OpenAI connection failed: {exc}") from exc
    except RateLimitError as exc:
        raise RuntimeError("OpenAI rate limit reached. Check quota and retry.") from exc
    except APIError as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

    return getattr(response, "output_text", "") or ""


def _ollama(system: str, user_msg: str, max_tokens: int) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    try:
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=max_tokens,
        )
    except Exception as e:
        fallback_model = "llama3.2:latest"
        if OLLAMA_MODEL != fallback_model:
            print(f"    [LLM] Ollama model '{OLLAMA_MODEL}' failed ({e}). Retrying with {fallback_model}.")
            response = client.chat.completions.create(
                model=fallback_model,
                messages=messages,
                temperature=0.3,
                max_tokens=max_tokens,
            )
        else:
            raise
    return response.choices[0].message.content or ""


def ddg_search(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo search — used by Ollama provider instead of Claude's web_search."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=".*duckduckgo_search.*renamed to ddgs.*",
                )
                from duckduckgo_search import DDGS
    except ImportError:
        print("    [LLM] DDG client is not installed; continuing without DDG results.")
        return []

    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        print(f"    [LLM] DuckDuckGo search failed ({e}); continuing without DDG results.")
        return []


def parse_json(raw: str) -> dict | list | None:
    """Strip markdown fences and parse JSON. Returns None on failure."""
    import json
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None
