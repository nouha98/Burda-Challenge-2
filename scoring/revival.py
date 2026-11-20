"""Archiv-Revival ranking: existing archive recipes that match rising trends and the current season mood.

score = 100 * (0.55 * trend relevance + 0.35 * season fit + 0.10 * completeness)
trend relevance = trend score T/100 * hybrid relevance (scoring/hybrid.py: semantic + title/ingredient match);
without vectors it falls back to lexical matching only. A recipe keeps its best trend.
Publication date is deliberately ignored. Top 5, max. 1 recipe per trend.
"""
import numpy as np

from scoring.hybrid import retrieve
from scoring.season import season_fit

WEIGHTS = {"trend": 0.55, "season": 0.35, "complete": 0.10}
TOP_N = 5
MAX_PER_TREND = 1


def completeness(r: dict) -> float:
    checks = [len(r.get("steps") or []) >= 2, bool((r.get("servings") or {}).get("amount")),
              any(t.get("minutes") for t in r.get("times") or []),
              sum(len(g["items"]) for g in r.get("ingredient_groups") or []) >= 3]
    return sum(checks) / len(checks)


def rank(trend_candidates: list[dict], recipes: list[dict], ctx: dict, top_n: int = TOP_N,
         vectors: np.ndarray | None = None, query_vecs: dict | None = None) -> list[dict]:
    """`recipes` must be in the same order as the rows of `vectors`."""
    best: dict[str, dict] = {}
    for c in trend_candidates:
        qv = query_vecs.get(c["id"]) if query_vecs else None
        for hit in retrieve(c, qv, recipes, vectors if qv is not None else None):
            r = hit["recipe"]
            rel = c["scores"]["T"] / 100 * hit["relevance"]
            if r["id"] not in best or rel > best[r["id"]]["trend_relevance"]:
                best[r["id"]] = {"recipe": r, "trend": c["classification"]["name_de"], "trend_id": c["id"],
                                 "trend_T": c["scores"]["T"], "match": hit["match"], "semantic": hit["semantic"],
                                 "hybrid_relevance": hit["relevance"], "trend_relevance": rel}
    scored = []
    for item in best.values():
        r = item["recipe"]
        fit, labels = season_fit(r, ctx)
        comp = completeness(r)
        score = 100 * (WEIGHTS["trend"] * item["trend_relevance"] + WEIGHTS["season"] * fit + WEIGHTS["complete"] * comp)
        scored.append({**item, "season_fit": round(fit, 2), "season_labels": labels, "completeness": round(comp, 2),
                       "score": round(score, 1)})
    scored.sort(key=lambda x: (-x["score"], x["recipe"]["title"] or ""))
    top, per_trend, seen_titles = [], {}, set()
    for s in scored:
        title = (s["recipe"]["title"] or "").strip().lower()
        if per_trend.get(s["trend_id"], 0) >= MAX_PER_TREND or title in seen_titles:
            continue
        top.append(s)
        per_trend[s["trend_id"]] = per_trend.get(s["trend_id"], 0) + 1
        seen_titles.add(title)
        if len(top) == top_n:
            break
    return top
