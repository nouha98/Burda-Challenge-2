"""Hybrid archive retrieval: semantic similarity (embeddings) + lexical matches (title / ingredient).

Raw cosine similarities of this model sit close together, and the useful signal is in the top 1 % per trend, so
the semantic score is calibrated per trend against its own top group:
    sem = clip((sim − p99) / (max − p99), 0, 1)        → best recipe 1, 99th percentile 0
    lex = 1.0 title match · 0.4 ingredient match · 0
    relevance = 0.6 · sem + 0.4 · lex
Keyword matches are always kept (their semantic part re-ranks them: a typical Grünkohl stew beats a Grünkohl
smoothie). Recipes found only via embeddings must be in the upper half of the top group (sem ≥ 0.5) with a raw
similarity ≥ 0.5, and at most SEMANTIC_ONLY_MAX of them are kept per trend.
(Calibration chosen after inspecting raw scores: e.g. for Rosenkohl the top 10 were all Rosenkohl dishes and
"Blumenkohlsuppe" came 11th at 0.588 → sem 0.44, excluded.)
"""
import numpy as np

from scoring.archive_match import _matches, search_terms

W_SEM, W_LEX = 0.6, 0.4
LEX = {"title": 1.0, "ingredient": 0.4}
SEMANTIC_ONLY_MIN_SEM = 0.5
SEMANTIC_ONLY_MIN_RAW = 0.5
SEMANTIC_ONLY_MAX = 10


def lexical_match(r: dict, terms: list[str]) -> str | None:
    if _matches(r["title"], terms) or _matches(r.get("subtitle"), terms):
        return "title"
    if any(_matches(i["name"], terms) for g in r["ingredient_groups"] for i in g["items"]):
        return "ingredient"
    return None


def calibrate(sims: np.ndarray) -> np.ndarray:
    low = float(np.percentile(sims, 99))
    top = float(sims.max())
    return np.clip((sims - low) / max(top - low, 1e-6), 0.0, 1.0)


def retrieve(candidate: dict, query_vec: np.ndarray | None, recipes: list[dict], vectors: np.ndarray | None,
             limit: int | None = None) -> list[dict]:
    """All archive recipes relevant to one trend, best first."""
    terms = search_terms(candidate)
    raw = vectors @ query_vec if vectors is not None and query_vec is not None else None
    sem = calibrate(raw) if raw is not None else None
    hits, semantic_only = [], []
    for k, r in enumerate(recipes):
        lex_type = lexical_match(r, terms)
        s = float(sem[k]) if sem is not None else 0.0
        hit = {"recipe": r, "semantic": round(s, 3), "raw_similarity": round(float(raw[k]), 3) if raw is not None else None,
               "lexical": lex_type, "match": lex_type or "semantic"}
        if lex_type:
            hit["relevance"] = round(W_SEM * s + W_LEX * LEX[lex_type], 3) if sem is not None else LEX[lex_type]
            hits.append(hit)
        elif sem is not None and s >= SEMANTIC_ONLY_MIN_SEM and raw[k] >= SEMANTIC_ONLY_MIN_RAW:
            hit["relevance"] = round(W_SEM * s, 3)
            semantic_only.append(hit)
    semantic_only.sort(key=lambda h: -h["relevance"])
    hits += semantic_only[:SEMANTIC_ONLY_MAX]
    hits.sort(key=lambda h: -h["relevance"])
    return hits[:limit] if limit else hits
