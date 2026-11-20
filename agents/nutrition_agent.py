"""Nutrition agent: matches recipe ingredients to the Swiss food database and computes values per serving.

1. Exact name match (code).
2. LLM (GLM-5.3-Flash) proposes database search terms (Swiss naming: Federkohl, Karotte, Rahm …).
3. Code builds candidate lists from the real database; the LLM picks one candidate ID per ingredient
   (or none) and labels it equivalent / closest substitute with a confidence.
4. Code converts quantities to grams with documented rules and does all arithmetic.

Run standalone:  python -m agents.nutrition_agent <run_id>
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from ingest.nutrition_db import SOURCE, candidates, foods, norm
from scoring.nutrition import calculate, to_grams
from services.gateway import GatewayError, chat_json
from storage import runs

MAJOR_SHARE = 0.05  # unresolved ingredient above 5 % of recipe weight blocks a complete label

SYSTEM = """Du bist der Nährwert-Agent der Zeitschrift "das schmeckt!". Du ordnest Rezeptzutaten Einträgen der
Schweizer Nährwertdatenbank zu. Du erfindest niemals Nährwerte. Antworte ausschließlich mit einem JSON-Objekt."""

TERMS_TEMPLATE = """Gib für jede Zutat 1–3 Suchbegriffe, unter denen sie in der Schweizer Nährwertdatenbank stehen könnte.
Die Datenbank nutzt Schweizer Bezeichnungen, z. B. Federkohl (= Grünkohl), Karotte (= Möhre), Rahm (= Sahne),
Saucen statt Soßen, Poulet (= Hähnchen), Bouillon (= Brühe), Weisswein, Rapsöl, Sauerrahm (≈ Schmand).
Bei verarbeiteten Produkten ohne eigenen Eintrag (z. B. Kassler) nenne die nächstliegende Grundzutat.

Zutaten:
{ingredients}

Format: {{"terms": {{"i1": ["...", "..."], "i2": ["..."]}}}}"""

PICK_TEMPLATE = """Wähle für jede Zutat den passenden Datenbankeintrag aus ihrer Kandidatenliste – nur IDs aus der jeweiligen Liste.
Achte auf den Zustand: rohe Zutaten → "roh"-Einträge; Konserven/gekochte Produkte entsprechend.
- match_type "equivalent": gleiches Lebensmittel, evtl. anderer Name (z. B. Grünkohl → Federkohl, roh)
- match_type "closest": nächstliegender Ersatz, weil es keinen passenden Eintrag gibt (z. B. Kassler → geräuchertes Schweinefleisch)
- db_id null, wenn kein Kandidat vertretbar ist.
- Gewürze, Kräuter und Würzmittel in Kleinstmengen ohne eigenen Eintrag (z. B. Piment, Muskat, Lorbeer): db_id null –
  niemals ein anderes Gewürz oder Lebensmittel als Ersatz wählen (Menge ist vernachlässigbar).
confidence: "high" (gleiches Lebensmittel und Zustand), "medium" (kleine Abweichung), "low" (grober Ersatz).

{blocks}

Format: {{"matches": [{{"id": "i1", "db_id": "13400", "match_type": "equivalent", "confidence": "high",
  "reason_de": "kurz, z. B. Grünkohl heißt in der Schweiz Federkohl"}}]}}"""


def _exact(name: str):
    n = norm(name)
    for f in foods().values():
        fn = norm(f["name"])
        if fn == n or fn == f"{n}, roh":
            return f
    return None


def match_ingredients(ingredients: list[dict]) -> dict:
    """ingredient id -> match record."""
    out, open_ = {}, []
    for ing in ingredients:
        f = _exact(ing.get("name", ""))
        if f:
            out[ing["id"]] = {"food": f, "match_type": "exact", "confidence": "high",
                              "reason_de": "Name stimmt mit dem Datenbankeintrag überein"}
        else:
            open_.append(ing)
    if not open_:
        return out
    listing = "\n".join(f'- {i["id"]}: {i.get("name")}' + (f' ({i["note"]})' if i.get("note") else "") for i in open_)
    try:
        data, _ = chat_json("nutrition_match", SYSTEM, TERMS_TEMPLATE.format(ingredients=listing),
                            max_tokens=6000, agent="nutrition_terms")
        terms = data.get("terms", {})
    except GatewayError:
        terms = {}
    cands = {i["id"]: candidates([i.get("name", "")] + list(terms.get(i["id"], []))) for i in open_}
    blocks = []
    for i in open_:
        lines = "\n".join(f'    {c["id"]}: {c["name"]}' for c in cands[i["id"]]) or "    (keine Kandidaten)"
        blocks.append(f'Zutat {i["id"]}: {i.get("name")}' + (f' ({i["note"]})' if i.get("note") else "") + f"\n{lines}")
    try:
        data, meta = chat_json("nutrition_match", SYSTEM, PICK_TEMPLATE.format(blocks="\n\n".join(blocks)),
                               max_tokens=8000, agent="nutrition_pick")
        picks = {m["id"]: m for m in data.get("matches", []) if "id" in m}
    except GatewayError:
        picks = {}
    for i in open_:
        m = picks.get(i["id"], {})
        allowed = {c["id"] for c in cands[i["id"]]}
        db_id = str(m.get("db_id")) if m.get("db_id") is not None else None
        if db_id and db_id in allowed:
            out[i["id"]] = {"food": foods()[db_id], "match_type": m.get("match_type", "closest"),
                            "confidence": m.get("confidence", "low"), "reason_de": m.get("reason_de"),
                            "search_terms": terms.get(i["id"], [])}
        else:
            out[i["id"]] = {"food": None, "match_type": "unmatched", "confidence": "none",
                            "reason_de": m.get("reason_de") or "kein vertretbarer Datenbankeintrag gefunden",
                            "search_terms": terms.get(i["id"], []),
                            "rejected_id": db_id if db_id and db_id not in allowed else None}
    return out


def nutrition_for(recipe: dict) -> dict:
    ingredients = recipe.get("ingredients") or []
    matches = match_ingredients(ingredients)
    lines = []
    for ing in ingredients:
        m = matches[ing["id"]]
        conv = to_grams(ing, m["food"])
        qty = ing.get("quantity")
        lines.append({
            "ingredient_id": ing["id"],
            "display": f'{qty:g} {ing.get("unit") or ""} {ing.get("name")}'.replace("  ", " ") if isinstance(qty, (int, float))
                       else ing.get("name"),
            "grams": round(conv["grams"], 1) if conv["grams"] is not None else None,
            "conversion_rule": conv["rule"],
            "conversion_confidence": conv["confidence"],
            "db_id": m["food"]["id"] if m["food"] else None,
            "db_name": m["food"]["name"] if m["food"] else None,
            "match_type": m["match_type"],
            "match_confidence": m["confidence"],
            "assumption_de": m.get("reason_de"),
            "food": m["food"],
        })
    result = calculate(lines, recipe.get("servings") or 1)
    total_g = sum(l["grams"] or 0 for l in lines)
    unresolved = []
    for l in lines:
        excluded = l["grams"] is None and "nach Geschmack" in l["conversion_rule"]
        if excluded:
            continue
        if l["grams"] is None or l["db_id"] is None:
            share = (l["grams"] or 0) / total_g if total_g else 0
            unresolved.append({"display": l["display"], "reason": l["conversion_rule"] if l["grams"] is None else l["assumption_de"],
                               "weight_share": round(share, 3),
                               "major": l["grams"] is None or share >= MAJOR_SHARE})
    for l in lines:
        l.pop("food")
    complete = not any(u["major"] for u in unresolved)
    return {
        "recipe_id": recipe["recipe_id"], "slot": recipe["slot"], "recipe_version": recipe["version"],
        "servings": recipe.get("servings"), "source": SOURCE, "basis": "pro 100 g essbarer Anteil",
        "lines": lines, **result, "unresolved": unresolved, "complete": complete,
        "note_de": "Berechnete Schätzwerte aus der Datenbank, keine Labormessung. Garverluste nicht berücksichtigt; "
                   "Salz und Pfeffer nach Geschmack nicht eingerechnet.",
    }


def run_nutrition(run_id: str) -> dict:
    recipes = runs.latest_recipes(run_id)
    runs.log_event(run_id, "nutrition_running", "Matching ingredients to the Swiss food database")
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(nutrition_for, recipes.values()))
    for res in results:
        runs.write_json(runs.run_dir(run_id) / f"nutrition_{res['slot']}_v{res['recipe_version']}.json", res)
    ok = all(r["complete"] for r in results)
    runs.log_event(run_id, "nutrition_ready" if ok else "nutrition_incomplete",
                   "; ".join(f"{r['slot']}: {r['per_serving'].get('kcal')} kcal/Portion, "
                             f"Abdeckung {r['weight_coverage']:.0%}" for r in results))
    return {r["slot"]: r for r in results}


def latest_nutrition(run_id: str, recipe: dict) -> dict | None:
    return runs.read_json(runs.run_dir(run_id) / f"nutrition_{recipe['slot']}_v{recipe['version']}.json")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for slot, res in run_nutrition(sys.argv[1]).items():
        print(f"\n== {slot} (v{res['recipe_version']}): per serving {res['per_serving']}  coverage {res['weight_coverage']}  complete={res['complete']}")
        for l in res["lines"]:
            print(f"  {l['display'][:34]:34} {str(l['grams']):>7} g  {l['match_type']:10} {l['match_confidence']:6} "
                  f"→ {l['db_name'] or '-'}  [{l['conversion_rule'][:50]}]")
        for u in res["unresolved"]:
            print("  UNRESOLVED:", u)
