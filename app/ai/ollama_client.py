"""The ONLY file that talks to an AI service. It supports two providers, chosen by AI_PROVIDER:
  ollama  - a local model (POST /api/chat, GET /api/tags). The default.
  openai  - any online service with an OpenAI-compatible /chat/completions endpoint.
Every problem is turned into one of our own exceptions, so the rest of the app never has to
understand raw network errors, and API keys are never logged or shown."""
import re

import requests
from flask import current_app


class OllamaError(Exception):
    code = "error"


class OllamaNotConfigured(OllamaError):
    code = "not_configured"


class OllamaUnavailable(OllamaError):
    code = "unavailable"


class OllamaModelMissing(OllamaError):
    code = "model_missing"


class OllamaTimeout(OllamaError):
    code = "timeout"


class OllamaBadResponse(OllamaError):
    code = "bad_response"


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _settings():
    cfg = current_app.config
    return cfg["OLLAMA_BASE_URL"].rstrip("/"), cfg["OLLAMA_MODEL"], cfg["OLLAMA_TIMEOUT"]


def _clean_reply(content):
    """Tidy the model's text. Some reasoning models print <think>...</think>; remove it."""
    if not isinstance(content, str):
        raise OllamaBadResponse()
    content = _THINK.sub("", content)                                             # finished blocks
    content = re.sub(r"<think>.*", "", content, flags=re.DOTALL | re.IGNORECASE)  # cut-off ones
    content = content.strip()
    if not content:
        raise OllamaBadResponse()
    return content


# ---------- provider 1: Ollama (local) ----------
def _ollama_chat(messages, temperature, json_mode, max_tokens):
    base, model, timeout = _settings()
    if not model:
        raise OllamaNotConfigured()

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,   # wait for the whole answer instead of streaming pieces
        "options": {"temperature": temperature,
                    "num_predict": max_tokens or current_app.config["OLLAMA_MAX_TOKENS"]},
    }
    if json_mode:
        payload["format"] = "json"
    try:
        # (3, timeout): give up connecting after 3 s, wait `timeout` s for the answer
        response = requests.post(f"{base}/api/chat", json=payload, timeout=(3, timeout))
    except requests.exceptions.ConnectionError as error:
        raise OllamaUnavailable() from error
    except requests.exceptions.Timeout as error:
        raise OllamaTimeout() from error
    except requests.exceptions.RequestException as error:
        raise OllamaUnavailable() from error

    if response.status_code == 404:          # Ollama answers 404 when the model is not installed
        raise OllamaModelMissing()
    if response.status_code != 200:
        current_app.logger.warning("Ollama returned HTTP %s", response.status_code)
        raise OllamaBadResponse()

    try:
        data = response.json()
    except ValueError as error:
        raise OllamaBadResponse() from error

    message = data.get("message") if isinstance(data, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return _clean_reply(content)


# ---------- provider 2: an OpenAI-compatible online service ----------
def _openai_chat(messages, temperature, json_mode, max_tokens):
    cfg = current_app.config
    key, model = cfg.get("AI_API_KEY"), cfg.get("AI_MODEL")
    base = (cfg.get("AI_BASE_URL") or "").rstrip("/")
    if not (key and model and base):
        raise OllamaNotConfigured()

    payload = {"model": model, "messages": messages, "temperature": temperature,
               "max_tokens": max_tokens or cfg["OLLAMA_MAX_TOKENS"]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        response = requests.post(f"{base}/chat/completions", json=payload,
                                 headers={"Authorization": f"Bearer {key}"},
                                 timeout=(5, cfg["OLLAMA_TIMEOUT"]))
    except requests.exceptions.ConnectionError as error:
        raise OllamaUnavailable() from error
    except requests.exceptions.Timeout as error:
        raise OllamaTimeout() from error
    except requests.exceptions.RequestException as error:
        raise OllamaUnavailable() from error

    status = response.status_code
    if status in (401, 403):                 # wrong or missing permission: treat as "not configured"
        current_app.logger.warning("The AI service rejected the API key (HTTP %s)", status)
        raise OllamaNotConfigured()
    if status == 404:
        raise OllamaModelMissing()
    if status == 429 or status >= 500:       # busy or down
        raise OllamaUnavailable()
    if status != 200:
        current_app.logger.warning("The AI service returned HTTP %s", status)
        raise OllamaBadResponse()

    try:
        data = response.json()
    except ValueError as error:
        raise OllamaBadResponse() from error
    choices = data.get("choices") if isinstance(data, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return _clean_reply(content)


# ---------- the two functions the rest of the app uses ----------
def chat(messages, temperature=0.3, json_mode=False, max_tokens=None):
    """Send messages [{"role": ..., "content": ...}] and return the reply text.
    json_mode=True asks for JSON output. max_tokens overrides the default answer length."""
    provider = current_app.config.get("AI_PROVIDER", "ollama")
    if provider == "ollama":
        return _ollama_chat(messages, temperature, json_mode, max_tokens)
    if provider == "openai":
        return _openai_chat(messages, temperature, json_mode, max_tokens)
    raise OllamaNotConfigured()              # an unknown AI_PROVIDER value


def check_status():
    """Is the AI usable? Never raises, and never reveals addresses, models or keys."""
    cfg = current_app.config
    provider = cfg.get("AI_PROVIDER", "ollama")
    if provider == "openai":                 # no cheap, safe test call exists: check the settings only
        ready = bool(cfg.get("AI_API_KEY") and cfg.get("AI_MODEL") and cfg.get("AI_BASE_URL"))
        return {"running": ready, "model_ready": ready}
    if provider != "ollama":
        return {"running": False, "model_ready": False}

    base, model, _ = _settings()
    try:
        response = requests.get(f"{base}/api/tags", timeout=3)
        response.raise_for_status()
        data = response.json()
    except (requests.exceptions.RequestException, ValueError):
        return {"running": False, "model_ready": False}

    models = data.get("models", []) if isinstance(data, dict) else []
    names = {m.get("name") for m in models if isinstance(m, dict)}
    ready = bool(model) and (model in names or f"{model}:latest" in names)
    return {"running": True, "model_ready": ready}