"""Archiv-Revival scoring: archive recipes per rising trend, scored on trend relevance and season mood.

score = 100 * (0.55 * trend relevance + 0.35 * season fit + 0.10 * completeness)
trend relevance = trend score T/100 * hybrid relevance (scoring/hybrid.py: semantic + title/ingredient match);
without vectors it falls back to lexical matching only. Publication date is deliberately ignored.

`candidates_per_trend` feeds the selector agent (top N per trend); `rank` is the deterministic fallback
(top 5 overall, max. 1 per trend) used when the selector agent is unavailable.
"""
import numpy as np

from scoring.hybrid import retrieve
from scoring.season import season_fit

WEIGHTS = {"trend": 0.55, "season": 0.35, "complete": 0.10}
TOP_N = 5
MAX_PER_TREND = 1
PER_TREND = 3
MAX_TRENDS = 12


def completeness(r: dict) -> float:
    checks = [len(r.get("steps") or []) >= 2, bool((r.get("servings") or {}).get("amount")),
              any(t.get("minutes") for t in r.get("times") or []),
              sum(len(g["items"]) for g in r.get("ingredient_groups") or []) >= 3]
    return sum(checks) / len(checks)


def score_hit(c: dict, hit: dict, ctx: dict) -> dict:
    r = hit["recipe"]
    rel = c["scores"]["T"] / 100 * hit["relevance"]
    fit, labels = season_fit(r, ctx)
    comp = completeness(r)
    score = 100 * (WEIGHTS["trend"] * rel + WEIGHTS["season"] * fit + WEIGHTS["complete"] * comp)
    return {"recipe": r, "trend": c["classification"]["name_de"], "trend_id": c["id"], "trend_T": c["scores"]["T"],
            "match": hit["match"], "semantic": hit["semantic"], "hybrid_relevance": hit["relevance"],
            "trend_relevance": rel, "season_fit": round(fit, 2), "season_labels": labels,
            "completeness": round(comp, 2), "score": round(score, 1)}


def candidates_for_trend(c: dict, recipes: list[dict], ctx: dict, vectors=None, query_vec=None,
                         per_trend: int = PER_TREND, exclude: set | None = None) -> list[dict]:
    exclude = exclude or set()
    hits = retrieve(c, query_vec, recipes, vectors if query_vec is not None else None)
    scored = [score_hit(c, h, ctx) for h in hits if h["recipe"]["id"] not in exclude]
    scored.sort(key=lambda x: (-x["score"], x["recipe"]["title"] or ""))
    out, titles = [], set()
    for s in scored:
        t = (s["recipe"]["title"] or "").strip().lower()
        if t not in titles:
            out.append(s)
            titles.add(t)
        if len(out) == per_trend:
            break
    return out


def candidates_per_trend(trend_candidates: list[dict], recipes: list[dict], ctx: dict,
                         vectors: np.ndarray | None = None, query_vecs: dict | None = None,
                         per_trend: int = PER_TREND, max_trends: int = MAX_TRENDS) -> dict:
    """trend id -> {"trend": candidate, "candidates": [scored recipes, best first]} for the top trends by T."""
    top_trends = sorted(trend_candidates, key=lambda c: -c["scores"]["T"])[:max_trends]
    out = {}
    for c in top_trends:
        qv = query_vecs.get(c["id"]) if query_vecs else None
        cands = candidates_for_trend(c, recipes, ctx, vectors, qv, per_trend)
        if cands:
            out[c["id"]] = {"trend": c, "candidates": cands}
    return out


def rank(trend_candidates: list[dict], recipes: list[dict], ctx: dict, top_n: int = TOP_N,
         vectors: np.ndarray | None = None, query_vecs: dict | None = None) -> list[dict]:
    """Deterministic top list (best per trend, max. MAX_PER_TREND per trend). `recipes` aligned with `vectors`."""
    pool = candidates_per_trend(trend_candidates, recipes, ctx, vectors, query_vecs,
                                per_trend=MAX_PER_TREND, max_trends=len(trend_candidates))
    scored = [s for entry in pool.values() for s in entry["candidates"]]
    scored.sort(key=lambda x: (-x["score"], x["recipe"]["title"] or ""))
    top, seen = [], set()
    for s in scored:
        if s["recipe"]["id"] in seen:
            continue
        top.append(s)
        seen.add(s["recipe"]["id"])
        if len(top) == top_n:
            break
    return top
