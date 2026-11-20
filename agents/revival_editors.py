"""Archiv-Revival review agent (DeepSeek-V4.1-Flash): checks every randomly drawn recipe against its trend and the
season and returns keep/replace per recipe; it can also ask the retrieval step to search a trend more widely.
"""
import json
from pathlib import Path

from services.gateway import GatewayError, chat_json

ROOT = Path(__file__).resolve().parents[1]
BRAND_RULES = (ROOT / "config" / "brand_rules.md").read_text(encoding="utf-8")

REVIEW_SYSTEM = f"""Du bist die Schlussredaktion von "das schmeckt!" und prüfst eine Archiv-Strecke streng.
{BRAND_RULES}
Antworte ausschließlich mit einem JSON-Objekt."""

REVIEW_USER = """Saison/Anlass: {season}

Ausgewählte Rezepte:
{items}

Prüfe jedes Rezept:
- trend_match: "strong" (Trend ist Kern des Gerichts), "weak" (Trend nur am Rand/als Nebenzutat), "none" (passt nicht)
- season_ok: passt das Rezept jetzt (Saison/Anlass)?
- verdict: "keep" oder "replace" (replace bei trend_match none, bei weak nur wenn es klar bessere Alternativen geben dürfte,
  oder wenn die Saison nicht passt)
Prüfe die Strecke als Ganzes: variety_ok (Abwechslung innerhalb und zwischen den Trends).
Wenn für einen Trend offenbar nur unpassende Kandidaten vorliegen, setze ihn in retrieve_again (dann wird breiter gesucht).

Format: {{"items": [{{"recipe_id": "...", "trend_match": "strong|weak|none", "season_ok": true,
                      "verdict": "keep|replace", "reason_de": "1 Satz"}}],
          "variety_ok": true, "variety_reason_de": "1 Satz", "retrieve_again": ["trend_id"]}}"""


def _ingredients(r: dict, n: int = 8) -> str:
    return ", ".join(i["name"] for g in r["ingredient_groups"] for i in g["items"] if i.get("name"))[:200]


def review(selection: list[dict], pool: dict, season: str) -> dict:
    items = []
    for s in selection:
        r = s["recipe"]
        desc = pool.get(s["trend_id"], {}).get("description") or s["trend"]
        method = " ".join(st["text"] for st in r["steps"])[:300]
        items.append(f'- {r["id"]}: „{r["title"]}" – Trend: {s["trend"]} ({desc}) | Kategorie: {r["category"]} | '
                     f'Saison-Labels: {", ".join(s["season_labels"]) or "–"} | Zutaten: {_ingredients(r)} | '
                     f'Zubereitung: {method}')
    try:
        data, meta = chat_json("reviewer", REVIEW_SYSTEM,
                               REVIEW_USER.format(season=season, items="\n".join(items)),
                               max_tokens=10000, agent="revival_review")
    except GatewayError as exc:
        # A failed review must never count as approval: every recipe stays unreviewed
        return {"items": [{"recipe_id": s["recipe"]["id"], "title": s["recipe"]["title"], "verdict": "unreviewed",
                           "trend_match": "unknown", "reason_de": "Review nicht verfügbar (Gateway-Fehler)"}
                          for s in selection],
                "variety_ok": None, "error": str(exc)[:200], "model": None, "all_ok": False, "retrieve_again": []}
    verdicts = {v.get("recipe_id"): v for v in data.get("items", [])}
    for s in selection:
        v = verdicts.get(s["recipe"]["id"]) or {"verdict": "unreviewed", "trend_match": "unknown",
                                                "reason_de": "keine Bewertung erhalten"}
        if v.get("trend_match") == "none":
            v["verdict"] = "replace"  # rule enforced in code
        verdicts[s["recipe"]["id"]] = v
    retrieve_again = [t for t in data.get("retrieve_again", []) if t in pool]
    # Only per-recipe verdicts decide; variety within a trend comes from the random draw and is informational
    all_ok = all(verdicts[s["recipe"]["id"]].get("verdict") == "keep" for s in selection)
    return {"items": [dict(verdicts[s["recipe"]["id"]], recipe_id=s["recipe"]["id"], title=s["recipe"]["title"])
                      for s in selection],
            "variety_ok": data.get("variety_ok", True), "variety_reason_de": data.get("variety_reason_de"),
            "retrieve_again": retrieve_again, "all_ok": all_ok, "model": meta["model"]}
