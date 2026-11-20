"""Image -> text via a vision model on the gateway (gemma-4-31B-it, ~4 s; Qwen3-VL as slow fallback).

The model describes only what it sees and does NOT get the recipe, so the description is not biased towards
what the image is supposed to show. The comparison with the recipe is done separately by the review agent.
"""
import base64
import io
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
MODELS = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
VISION_MODELS = [MODELS.get("vision", "tesseracted-labs-gmbh/google/gemma-4-31B-it"),
                 MODELS.get("vision_fallback", "tesseracted-labs-gmbh/Qwen/Qwen3-VL-235B-A22B-Instruct-FP8")]

PROMPT = """Beschreibe sachlich und vollständig auf Deutsch, was auf diesem Food-Foto zu sehen ist (max. 150 Wörter):
- Gericht bzw. Speise, Gefäß/Geschirr, Besteck
- jede sichtbare Zutat bzw. Komponente mit Farbe, Form, Schnittgröße, Garzustand (roh, gebraten, geschmort, gebacken …),
  Anzahl und Lage (oben, innen, daneben)
- Konsistenz von Soße/Creme/Brühe
- Auffälligkeiten: unlogische Details, Text, Personen, Hände, Bildfehler
Beschreibe nur, was wirklich sichtbar ist; nichts vermuten oder ergänzen."""


class VisionError(RuntimeError):
    pass


def _data_url(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((768, 768))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def describe_image(path: Path, timeout: int = 240) -> dict:
    base = os.environ["TESSERACT_BASE_URL"].rstrip("/")
    url = _data_url(Path(path))
    errors = []
    for model in VISION_MODELS:
        started = time.time()
        try:
            r = requests.post(f"{base}/v1/chat/completions", timeout=(30, timeout), stream=True,
                              headers={"Authorization": f"Bearer {os.environ['TESSERACT_API_KEY']}"},
                              json={"model": model, "max_tokens": 800, "stream": True,
                                    "messages": [{"role": "user", "content": [
                                        {"type": "text", "text": PROMPT},
                                        {"type": "image_url", "image_url": {"url": url}}]}]})
            if r.status_code != 200:
                raise VisionError(f"HTTP {r.status_code}: {r.text[:200]}")
            r.encoding = "utf-8"
            out = []
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                for ch in json.loads(line[5:]).get("choices", []):
                    piece = (ch.get("delta") or {}).get("content")
                    if piece:
                        out.append(piece)
            text = "".join(out).strip()
            if text:
                return {"description": text, "model": model, "seconds": round(time.time() - started, 1)}
            raise VisionError("empty description")
        except (requests.RequestException, VisionError, ValueError) as exc:
            errors.append(f"{model}: {exc}")
    raise VisionError(" | ".join(errors))
