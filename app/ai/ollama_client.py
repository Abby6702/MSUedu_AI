"""The ONLY file that talks to Ollama. It uses two documented Ollama endpoints:
  POST /api/chat  - send a conversation, get a reply
  GET  /api/tags  - list the models that are installed
Every problem is turned into one of our own exceptions, so the rest of the app
never has to understand raw network errors."""
import requests
import re
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


def chat(messages, temperature=0.3, json_mode=False, max_tokens=None):
    """Send messages [{"role": ..., "content": ...}] and return the reply text.
    json_mode=True asks Ollama to answer with valid JSON.
    max_tokens overrides the default answer length (OLLAMA_MAX_TOKENS)."""
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
    if not isinstance(content, str):
        raise OllamaBadResponse()
    content = _THINK.sub("", content)                        # finished thinking blocks
    content = re.sub(r"<think>.*", "", content, flags=re.DOTALL | re.IGNORECASE)   # cut-off ones
    content = content.strip()
    if not content:
        raise OllamaBadResponse()
    return content

def check_status():
    """Is Ollama running, and is our model installed? Never raises."""
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