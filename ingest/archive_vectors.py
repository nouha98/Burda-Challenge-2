"""Vector index of the 5,000 archive recipes (built once, cached in runs/cache/).

Document text per recipe: title, subtitle, category, editorial labels, main ingredients (pantry staples removed)
and the beginning of the method. The cache is keyed by model and text version, so it rebuilds when either changes.

Run:  python -m ingest.archive_vectors      (builds the cache once, ~17 min measured)
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from ingest.archive import build_index
from scoring.archive_match import PANTRY
from services import embeddings

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "runs" / "cache"
TEXT_VERSION = "v1"


def recipe_text(r: dict) -> str:
    ingredients = [i["name"] for g in r["ingredient_groups"] for i in g["items"]
                   if i.get("name") and i["name"].lower() not in PANTRY][:12]
    method = " ".join(s["text"] for s in r["steps"])[:240]
    parts = [r["title"] or "", r.get("subtitle") or "", f"Kategorie: {r.get('category') or ''}",
             ("Merkmale: " + ", ".join(r["labels"])) if r.get("labels") else "",
             "Zutaten: " + ", ".join(ingredients), "Zubereitung: " + method]
    return ". ".join(p for p in parts if p).replace("\n", " ")


def _key() -> str:
    return hashlib.sha1(f"{embeddings.MODEL}|{TEXT_VERSION}".encode()).hexdigest()[:10]


def load(build: bool = True, progress=print) -> tuple[list[str], np.ndarray] | tuple[None, None]:
    vec_path, ids_path = CACHE_DIR / f"archive_vectors_{_key()}.npy", CACHE_DIR / f"archive_vectors_{_key()}.json"
    if vec_path.exists() and ids_path.exists():
        return json.loads(ids_path.read_text(encoding="utf-8")), np.load(vec_path)
    if not build:
        return None, None
    recipes = build_index()
    texts = [recipe_text(r) for r in recipes]
    # Checkpoint every chunk so an interrupted build resumes instead of starting over
    parts = CACHE_DIR / f"archive_vectors_{_key()}_parts"
    parts.mkdir(parents=True, exist_ok=True)
    chunk = 320
    for start in range(0, len(texts), chunk):
        part = parts / f"{start:05d}.npy"
        if part.exists():
            continue
        np.save(part, embeddings.embed(texts[start:start + chunk]))
        progress(f"Embeddings: {min(start + chunk, len(texts))}/{len(texts)} Rezepte")
    vecs = np.vstack([np.load(parts / f"{start:05d}.npy") for start in range(0, len(texts), chunk)])
    np.save(vec_path, vecs)
    ids_path.write_text(json.dumps([r["id"] for r in recipes]), encoding="utf-8")
    return [r["id"] for r in recipes], vecs


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import time
    t = time.time()
    ids, vecs = load()
    print(f"{len(ids)} vectors, shape {vecs.shape}, {time.time() - t:.0f} s")
