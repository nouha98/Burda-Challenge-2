"""Client for the Tesseracted Labs gateway (OpenAI-compatible chat completions).

All LLM agents go through `chat_json`, which asks for a JSON object, retries once
with a repair prompt if the answer isn't valid JSON, then tries the fallback model.
Every call is appended to runs/llm_log.jsonl (model, latency, tokens; no secrets).
"""
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
MODELS = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
LOG_PATH = ROOT / "runs" / "llm_log.jsonl"


class GatewayError(RuntimeError):
    pass


def _post(model: str, messages: list, max_tokens: int, timeout: int) -> dict:
    """Streams the completion: the gateway's proxy closes connections that stay silent for ~100 s
    (HTTP 524), and long reasoning + recipe generation exceeds that without streaming."""
    base = os.environ["TESSERACT_BASE_URL"].rstrip("/")
    resp = requests.post(
        f"{base}/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['TESSERACT_API_KEY']}"},
        json={
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        timeout=(30, timeout),
        stream=True,
    )
    if resp.status_code != 200:
        raise GatewayError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    content, finish, usage = [], None, {}
    resp.encoding = "utf-8"
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        chunk = json.loads(payload)
        if chunk.get("usage"):
            usage = chunk["usage"]
        for ch in chunk.get("choices", []):
            piece = (ch.get("delta") or {}).get("content")
            if piece:
                content.append(piece)
            finish = ch.get("finish_reason") or finish
    return {"choices": [{"message": {"content": "".join(content)}, "finish_reason": finish}], "usage": usage}


def _parse_json(text: str):
    text = (text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def chat_json(role: str, system: str, user: str, max_tokens: int | None = None,
              timeout: int = 180, agent: str = "") -> dict:
    """Call the model configured for `role` and return (parsed_json, meta)."""
    max_tokens = max_tokens or MODELS["max_tokens"]
    models = [MODELS[role]]
    if MODELS["fallback"] not in models:
        models.append(MODELS["fallback"])
    errors = []
    for model in models:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in ("first", "repair"):
            started = time.time()
            try:
                data = _post(model, messages, max_tokens, timeout)
            except (requests.RequestException, GatewayError) as exc:
                errors.append(f"{model} {attempt}: {exc}")
                _log({"agent": agent, "model": model, "attempt": attempt, "ok": False,
                      "error": str(exc)[:300], "seconds": round(time.time() - started, 2)})
                break  # transport error: go to fallback model
            choice = data["choices"][0]
            content = choice["message"].get("content")
            usage = data.get("usage", {})
            try:
                parsed = _parse_json(content)
                _log({"agent": agent, "model": model, "attempt": attempt, "ok": True,
                      "seconds": round(time.time() - started, 2), "usage": usage})
                return parsed, {"model": model, "attempt": attempt, "usage": usage,
                                "seconds": round(time.time() - started, 2)}
            except (json.JSONDecodeError, TypeError) as exc:
                errors.append(f"{model} {attempt}: invalid JSON ({exc}); finish={choice.get('finish_reason')}")
                _log({"agent": agent, "model": model, "attempt": attempt, "ok": False,
                      "error": f"invalid JSON, finish={choice.get('finish_reason')}",
                      "seconds": round(time.time() - started, 2), "usage": usage})
                messages = messages + [
                    {"role": "assistant", "content": content or ""},
                    {"role": "user", "content": "Deine Antwort war kein gültiges JSON. "
                     "Antworte ausschließlich mit dem korrigierten JSON-Objekt."},
                ]
    raise GatewayError("All attempts failed: " + " | ".join(errors))
