"""Archiv-Revival editors: a selector agent (editor role) and a review agent.

Selector (GLM-5.3-Flash): picks 5 recipes from the per-trend candidate pool – 5 different trends, max. 2 per
archive category, a mix of dish types – and explains each pick. Code validates the answer and fills gaps.
Reviewer (DeepSeek-V4.1-Flash): checks every pick against its trend and the season and the set for variety;
returns keep/replace per recipe and can ask the retrieval step to search a trend again.
"""
import json
from pathlib import Path

from services.gateway import GatewayError, chat_json

ROOT = Path(__file__).resolve().parents[1]
BRAND_RULES = (ROOT / "config" / "brand_rules.md").read_text(encoding="utf-8")
N_SELECT = 5
MAX_PER_CATEGORY = 2

SELECT_SYSTEM = f"""Du bist Redakteurin bei "das schmeckt!" und stellst eine Archiv-Strecke zusammen: 5 vorhandene
Rezepte, die zu aktuellen Food-Trends und zur Saison passen. Du achtest auf Abwechslung für die Leserinnen.
{BRAND_RULES}
Antworte ausschließlich mit einem JSON-Objekt."""

SELECT_USER = """Saison/Anlass: {season}

Kandidaten je Trend (nur diese IDs verwenden):
{pool}
{feedback}
Wähle genau {n} Rezepte:
- 5 verschiedene Trends
- höchstens {max_cat} Rezepte aus derselben Archiv-Kategorie
- eine abwechslungsreiche Mischung (z. B. Hauptgericht, Suppe/Eintopf, Beilage/Gemüse, Gebäck, Dessert) –
  nicht nur Süßes, nicht nur Plätzchen
- jedes Rezept muss wirklich zum Trend passen (der Trend ist Kern des Gerichts, nicht nur Randzutat)

Format: {{"selection": [{{"recipe_id": "...", "trend_id": "...", "why_de": "1 Satz"}}],
          "variety_de": "1 Satz zur Mischung"}}"""

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
Prüfe die Strecke als Ganzes: variety_ok (verschiedene Trends, Gerichtsarten, nicht zu süßlastig/einseitig).
Wenn für einen Trend offenbar nur unpassende Kandidaten vorliegen, setze ihn in retrieve_again (dann wird breiter gesucht).

Format: {{"items": [{{"recipe_id": "...", "trend_match": "strong|weak|none", "season_ok": true,
                      "verdict": "keep|replace", "reason_de": "1 Satz"}}],
          "variety_ok": true, "variety_reason_de": "1 Satz", "retrieve_again": ["trend_id"]}}"""


def _ingredients(r: dict, n: int = 8) -> str:
    return ", ".join(i["name"] for g in r["ingredient_groups"] for i in g["items"] if i.get("name"))[:200]


def pool_text(pool: dict, excluded: set) -> str:
    blocks = []
    for tid, entry in pool.items():
        c = entry["trend"]
        lines = [f'Trend {tid}: {c["classification"]["name_de"]} (Trend-Score {c["scores"]["T"]:.0f}) – '
                 f'{entry.get("description") or c["classification"].get("relevance_de", "")}']
        for s in entry["candidates"]:
            r = s["recipe"]
            if r["id"] in excluded:
                continue
            lines.append(f'  - {r["id"]}: „{r["title"]}" | Kategorie: {r["category"]} | Saison: '
                         f'{", ".join(s["season_labels"]) or "–"} | Treffer: {s["match"]} | Score {s["score"]:.0f} | '
                         f'Zutaten: {_ingredients(r)}')
        if len(lines) > 1:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _fallback_fill(chosen: list[dict], pool: dict, excluded: set) -> list[dict]:
    """Deterministic completion: best remaining candidates respecting trend and category limits."""
    used_trends = {c["trend_id"] for c in chosen}
    cats = {}
    for c in chosen:
        cats[c["recipe"]["category"]] = cats.get(c["recipe"]["category"], 0) + 1
    rest = sorted((s for e in pool.values() for s in e["candidates"]
                   if s["recipe"]["id"] not in excluded and s["trend_id"] not in used_trends),
                  key=lambda s: -s["score"])
    for s in rest:
        if len(chosen) >= N_SELECT:
            break
        if s["trend_id"] in used_trends or cats.get(s["recipe"]["category"], 0) >= MAX_PER_CATEGORY:
            continue
        chosen.append(dict(s, why_de="automatisch ergänzt (bester verbleibender Kandidat)", picked_by="fallback"))
        used_trends.add(s["trend_id"])
        cats[s["recipe"]["category"]] = cats.get(s["recipe"]["category"], 0) + 1
    return chosen


def select(pool: dict, season: str, excluded: set, feedback: list[str]) -> dict:
    by_id = {s["recipe"]["id"]: s for e in pool.values() for s in e["candidates"]}
    fb = ("\nRückmeldung der Schlussredaktion zur letzten Auswahl (berücksichtigen!):\n- " + "\n- ".join(feedback)
          + "\nAusgeschlossene Rezepte nicht erneut wählen.\n") if feedback else ""
    user = SELECT_USER.format(season=season, pool=pool_text(pool, excluded), feedback=fb, n=N_SELECT,
                              max_cat=MAX_PER_CATEGORY)
    try:
        data, meta = chat_json("revival_selector", SELECT_SYSTEM, user, max_tokens=10000, agent="revival_selector")
    except (GatewayError, KeyError):
        data, meta = {"selection": []}, {"model": None}
    chosen, trends, cats, notes = [], set(), {}, []
    for pick in data.get("selection", []):
        s = by_id.get(pick.get("recipe_id"))
        if not s or s["recipe"]["id"] in excluded:
            notes.append(f"ungültige/ausgeschlossene ID verworfen: {pick.get('recipe_id')}")
            continue
        cat = s["recipe"]["category"]
        if s["trend_id"] in trends or cats.get(cat, 0) >= MAX_PER_CATEGORY:
            notes.append(f"Regelverstoß verworfen (Trend/Kategorie doppelt): {s['recipe']['title']}")
            continue
        chosen.append(dict(s, why_de=pick.get("why_de"), picked_by="selector"))
        trends.add(s["trend_id"])
        cats[cat] = cats.get(cat, 0) + 1
        if len(chosen) == N_SELECT:
            break
    chosen = _fallback_fill(chosen, pool, excluded)
    return {"selection": chosen, "variety_de": data.get("variety_de"), "validation_notes": notes,
            "model": meta.get("model")}


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
        return {"items": [], "variety_ok": True, "error": str(exc)[:200], "model": None, "all_ok": True}
    verdicts = {v.get("recipe_id"): v for v in data.get("items", [])}
    for s in selection:
        v = verdicts.get(s["recipe"]["id"]) or {"verdict": "keep", "trend_match": "unknown", "season_ok": True,
                                                "reason_de": "keine Bewertung erhalten"}
        if v.get("trend_match") == "none":
            v["verdict"] = "replace"  # rule enforced in code
        verdicts[s["recipe"]["id"]] = v
    retrieve_again = [t for t in data.get("retrieve_again", []) if t in pool]
    all_ok = all(v.get("verdict") == "keep" for v in verdicts.values()) and data.get("variety_ok", True)
    return {"items": [dict(verdicts[s["recipe"]["id"]], recipe_id=s["recipe"]["id"], title=s["recipe"]["title"])
                      for s in selection],
            "variety_ok": data.get("variety_ok", True), "variety_reason_de": data.get("variety_reason_de"),
            "retrieve_again": retrieve_again, "all_ok": all_ok, "model": meta["model"]}
