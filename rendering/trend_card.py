"""A4 overview card (no image) for the top trends of an Archiv-Revival result: trendiness figures + drawn recipes.

  python -m rendering.trend_card <revival_id> <out_file>
"""
import sys
from pathlib import Path

from rendering.card import ENV, LOGO, de_num
from storage import runs

ROOT = Path(__file__).resolve().parents[1]


def _date(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}"


def build(revival_id: str) -> str:
    data = runs.read_json(runs.RUNS / revival_id / "revival.json")
    trends = runs.read_json(runs.TRENDS)
    by_id = {c["id"]: c for c in trends["candidates"]}
    window = trends["sources"]["wikimedia"]["live_window"]
    period = trends["sources"]["google_trends"]["period"]
    rows = []
    for tid in data["candidate_pool"]:
        c = by_id[tid]
        s, w = c["scores"], c["wikimedia"] or {}
        change = s.get("wikipedia_change")
        rows.append({
            "name": c["classification"]["name_de"], "T": de_num(round(s["T"], 1)),
            "why": c["classification"].get("relevance_de", ""),
            "growth": de_num(round(s["best_google_growth_percent"] or 0)), "interest": s["max_search_interest"],
            "views": f"{w.get('latest_7d_views', 0):,}".replace(",", "."),
            "change": f"{change * 100:+.0f} %".replace("+", "+ ").replace("-", "− ") if change is not None else "–",
            "wiki_label": {"growing": "steigend", "stable": "stabil", "declining": "fallend"}.get(s.get("wikipedia_trend"), "unbekannt"),
            "recipes": [{"title": i["title"], "category": i["category"]} for i in data["items"] if i.get("trend_id") == tid],
        })
    return ENV.get_template("trend_card.html.j2").render(
        logo=LOGO, trends=rows, seed=data.get("seed"), season=data["season_context"]["reason"].split(";")[0],
        google_period=f"{_date(period['start'])}–{_date(period['end'])}",
        wiki_latest=f"{_date(window['latest'][0])}–{_date(window['latest'][1])}",
        wiki_previous=f"{_date(window['previous'][0])}–{_date(window['previous'][1])}",
        generated=_date(data["generated_at"]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    out = ROOT / sys.argv[2]
    out.write_text(build(sys.argv[1]), encoding="utf-8")
    print(out)
