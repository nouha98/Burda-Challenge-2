"""Trend score T (plan §5). Weights and smoothing are design choices, not organiser rules.

G = 0.60 * p(Google growth) + 0.40 * p(Google interest)      (percentiles within each Google cohort)
W = 0.60 * p(latest 7d views) + 0.40 * p(clipped log growth)
T = 100 * (0.65 * G + 0.35 * W)
"""
import math

WIKI_SMOOTHING = 20
WIKI_CLIP = math.log(4)
STABLE_BAND = 0.05


def percentiles(values: list[float]) -> list[float]:
    """p(x) = (average tied rank - 1) / (n - 1); 0.5 when n == 1."""
    n = len(values)
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return [(r - 1) / (n - 1) for r in ranks]


def wiki_log_growth(previous: int, latest: int) -> float:
    g = math.log((latest + WIKI_SMOOTHING) / (previous + WIKI_SMOOTHING))
    return max(-WIKI_CLIP, min(WIKI_CLIP, g))


def wiki_label(previous: int, latest: int) -> str:
    if previous == 0:
        return "growing" if latest > 0 else "stable"
    change = latest / previous - 1
    if change > STABLE_BAND:
        return "growing"
    if change < -STABLE_BAND:
        return "declining"
    return "stable"


def score_candidates(candidates: list[dict]) -> None:
    """Adds `scores` to each candidate in place. Expects candidate['records'] and candidate['wikimedia']."""
    # Google: percentiles within each cohort (signal_type x source_kind), over eligible records only
    cohorts: dict[tuple, list] = {}
    for c in candidates:
        for r in c["records"]:
            cohorts.setdefault((r["signal_type"], r["source_kind"]), []).append(r)
    for recs in cohorts.values():
        growth = [r["increase_percent"] if r["increase_percent"] is not None else 0 for r in recs]
        interest = [r["search_interest"] for r in recs]
        for r, pg, pi in zip(recs, percentiles(growth), percentiles(interest)):
            r["_p_growth"], r["_p_interest"] = pg, pi

    wiki_ok = [c for c in candidates if c["wikimedia"] and c["wikimedia"].get("latest_7d_views") is not None]
    p_views = percentiles([c["wikimedia"]["latest_7d_views"] for c in wiki_ok]) if wiki_ok else []
    p_wgrowth = percentiles([wiki_log_growth(c["wikimedia"]["previous_7d_views"], c["wikimedia"]["latest_7d_views"])
                             for c in wiki_ok]) if wiki_ok else []
    wiki_p = {id(c): (pv, pg) for c, pv, pg in zip(wiki_ok, p_views, p_wgrowth)}

    for c in candidates:
        best_growth = max((r["increase_percent"] for r in c["records"] if r["increase_percent"] is not None), default=None)
        G = max(0.60 * r["_p_growth"] + 0.40 * r["_p_interest"] for r in c["records"])
        for r in c["records"]:
            r.pop("_p_growth", None)
            r.pop("_p_interest", None)
        w = c["wikimedia"]
        if id(c) in wiki_p:
            pv, pg = wiki_p[id(c)]
            W = 0.60 * pv + 0.40 * pg
            prev, latest = w["previous_7d_views"], w["latest_7d_views"]
            change = (latest / prev - 1) if prev else None
            label = wiki_label(prev, latest)
            T = 100 * (0.65 * G + 0.35 * W)
            T_note = "complete"
        else:
            W, change, label = None, None, "unknown"
            T = 100 * 0.65 * G
            T_note = "Wikimedia unknown: score covers 65 of 100 points"
        flags = []
        if best_growth is None or best_growth <= 0:
            flags.append("no_positive_google_growth")
        if w and w.get("previous_7d_views", 0) < 100:
            flags.append("low_wikipedia_baseline")
        c["scores"] = {
            "T": round(T, 1),
            "T_note": T_note,
            "G": round(G, 3),
            "W": round(W, 3) if W is not None else None,
            "best_google_growth_percent": best_growth,
            "max_search_interest": max(r["search_interest"] for r in c["records"]),
            "wikipedia_change": round(change, 3) if change is not None else None,
            "wikipedia_trend": label,
            "is_rising": bool(best_growth and best_growth > 0),
            "flags": flags,
        }
