"""Text embeddings via the Tesseracted gateway (Qwen3-Embedding-8B, 4096 dims).

Documents are embedded as-is; queries get Qwen3's instruction prefix, which the model is trained to use.
Vectors are returned L2-normalised (float32), so cosine similarity is a dot product.
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
MODELS = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
MODEL = MODELS.get("embedding", "tesseracted-labs-gmbh/Qwen/Qwen3-Embedding-8B")
BATCH = 32
WORKERS = 4
QUERY_TASK = "Given a current food trend, retrieve German magazine recipes that are about this dish or ingredient"


def _post(texts: list[str], retries: int = 3) -> np.ndarray:
    base = os.environ["TESSERACT_BASE_URL"].rstrip("/")
    for attempt in range(retries):
        try:
            r = requests.post(f"{base}/v1/embeddings", timeout=120,
                              headers={"Authorization": f"Bearer {os.environ['TESSERACT_API_KEY']}"},
                              json={"model": MODEL, "input": texts})
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            return np.array([d["embedding"] for d in data], dtype=np.float32)
        except (requests.RequestException, KeyError, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def embed(texts: list[str], query: bool = False, progress=None) -> np.ndarray:
    if query:
        texts = [f"Instruct: {QUERY_TASK}\nQuery: {t}" for t in texts]
    batches = [texts[i:i + BATCH] for i in range(0, len(texts), BATCH)]
    out = [None] * len(batches)
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_post, b): k for k, b in enumerate(batches)}
        for fut in futures:
            out[futures[fut]] = fut.result()
            done += 1
            if progress and done % 10 == 0:
                progress(f"Embeddings: {done}/{len(batches)} Pakete")
    vecs = np.vstack(out) if out else np.zeros((0, 4096), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.maximum(norms, 1e-12)
