"""Archiv-Revival ranking: existing archive recipes that match rising trends and the current season mood.

score = 100 * (0.55 * trend relevance + 0.35 * season fit + 0.10 * completeness)
trend relevance = trend score T/100 * match strength (title 1.0, ingredient 0.4); a recipe keeps its best trend.
Publication date is deliberately ignored. Max. 2 recipes per trend in the top list.
"""
from scoring.archive_match import _matches, search_terms
from scoring.season import season_fit

WEIGHTS = {"trend": 0.55, "season": 0.35, "complete": 0.10}
STRENGTH = {"title": 1.0, "ingredient": 0.4}
MAX_PER_TREND = 2


def completeness(r: dict) -> float:
    checks = [len(r.get("steps") or []) >= 2, bool((r.get("servings") or {}).get("amount")),
              any(t.get("minutes") for t in r.get("times") or []),
              sum(len(g["items"]) for g in r.get("ingredient_groups") or []) >= 3]
    return sum(checks) / len(checks)


def rank(trend_candidates: list[dict], recipes: list[dict], ctx: dict, top_n: int = 10) -> list[dict]:
    best: dict[str, dict] = {}
    for c in trend_candidates:
        terms = search_terms(c)
        T = c["scores"]["T"]
        for r in recipes:
            if _matches(r["title"], terms) or _matches(r.get("subtitle"), terms):
                match = "title"
            elif any(_matches(i["name"], terms) for g in r["ingredient_groups"] for i in g["items"]):
                match = "ingredient"
            else:
                continue
            rel = T / 100 * STRENGTH[match]
            if r["id"] not in best or rel > best[r["id"]]["trend_relevance"]:
                best[r["id"]] = {"recipe": r, "trend": c["classification"]["name_de"], "trend_id": c["id"],
                                 "trend_T": T, "match": match, "trend_relevance": rel}
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
