"""Recipe agent (Kimi-K3.1-Pro): two clearly differentiated recipes for the selected proposal.

Run standalone:  python -m agents.recipe_agent <run_id>
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ingest.archive import build_index
from services.gateway import chat_json
from storage import runs

ROOT = Path(__file__).resolve().parents[1]
BRAND_RULES = (ROOT / "config" / "brand_rules.md").read_text(encoding="utf-8")

RECIPE_FORMAT = """{
  "title": "Rezepttitel",
  "subtitle": "optionale Unterzeile oder null",
  "introduction": "2–3 Sätze Einleitung im das-schmeckt!-Ton",
  "servings": 2,
  "servings_unit": "Portionen",
  "times": {"prep_minutes": 20, "cook_minutes": 30, "total_minutes": 50},
  "ingredients": [
    {"id": "i1", "group": "Für den Teig", "name": "Mehl", "quantity": 200, "unit": "g", "note": "Type 405", "optional": false}
  ],
  "steps": [
    {"number": 1, "group": "Für den Teig", "text": "Anweisung …",
     "uses": [{"ingredient_id": "i1", "quantity": 200, "unit": "g"}],
     "duration_minutes": 10, "temperature": "180 °C Ober-/Unterhitze (Umluft 160 °C)"}
  ],
  "serving_tip": "Kurzer praktischer Tipp (Unser Tipp)"
}"""

SYSTEM = f"""Du bist der Rezept-Agent der Zeitschrift "das schmeckt!" (Burda) und entwickelst neue Rezepte auf Deutsch.
{BRAND_RULES}

Regeln für jedes Rezept:
- Originale Formulierungen; keine Archivrezepte kopieren.
- Jede Zutat mit exakter Menge und Einheit (Ausnahme: Salz, Pfeffer – dann quantity null, unit null).
- Einheiten wie im Heft: g, kg, ml, l, EL, TL, Prise, Stück, Bund, Zehe(n), Dose, Packung. EL ≠ TL.
- Jede Zutat wird in mindestens einem Schritt verwendet ("uses"); jeder Schritt nennt nur Zutaten aus der Liste.
- Wird eine Zutat auf mehrere Schritte verteilt, müssen die Teilmengen in "uses" exakt die Gesamtmenge ergeben.
- "group" = Zwischenüberschrift (z. B. "Für den Teig", "Für die Soße"); null, wenn das Rezept keine Gruppen braucht.
- Temperaturen mit Ober-/Unterhitze und Umluft angeben, Garzeiten in den Schritten.
- prep_minutes = aktive Arbeitszeit, cook_minutes = Gar-/Backzeit, total_minutes = Gesamtdauer (kann kleiner als die Summe sein).
- Keine langen Zutatenlisten (Richtwert max. 12 Zutaten), keine exotischen Zutaten, alltagstauglich mit gehobenem Anspruch.
- Keine Gesundheitsversprechen.
Antworte ausschließlich mit einem JSON-Objekt."""

USER_TEMPLATE = """Die Redaktion hat dieses Thema ausgewählt:

Thema: {topic}
Vorschlag: {title}
{teaser}
Content-Lücke im Archiv: {gap}
Wiederholungsrisiko: {risk}

Vorgaben der Redaktion:
- Portionen: {servings}
- Maximale Gesamtzeit: {max_minutes}
- Hinweise: {notes}

Vorhandene Archivrezepte zum Thema – NICHT wiederholen, sondern davon abheben:
{archive}

Stilbeispiel eines Archivrezepts (nur Ton und Aufbau, nicht kopieren):
{style}

Entwickle jetzt Rezept {slot} nach dieser Richtung:
{dir_self}

Ein zweites Rezept wird parallel nach dieser anderen Richtung entwickelt:
{dir_other}
Dein Rezept muss sich davon klar unterscheiden – in Format bzw. Zubereitungsart UND in den Hauptkomponenten,
nicht nur in Garnitur oder Gewürz.

Antworte mit genau einem Rezept in diesem Format:
{fmt}"""

REVISION_TEMPLATE = """Überarbeite dieses Rezept anhand des Review-Berichts. Ändere nur, was nötig ist, und behalte Format und IDs bei.

Rezept (JSON):
{recipe}

Review-Bericht:
{report}

Antworte nur mit dem vollständigen überarbeiteten Rezept als JSON-Objekt im selben Format (ohne "slot"/"version")."""


def _archive_context(proposal: dict) -> tuple[str, str]:
    arch = proposal["evidence"]["archive"]
    lines = [f'- „{r["title"]}" ({r["date_imported"]}, {r["category"]})' for r in arch["closest_recipes"]]
    style = "–"
    index = {r["id"]: r for r in build_index()}
    for ref in arch["closest_recipes"]:
        r = index.get(ref["id"])
        if r and r["steps"] and 4 <= sum(len(g["items"]) for g in r["ingredient_groups"]) <= 12:
            ingr = "; ".join(f'{i["amount"] if i["amount"] is not None else ""} {i["unit"] or ""} {i["name"]}'.strip()
                             for g in r["ingredient_groups"] for i in g["items"])
            steps = " / ".join(s["text"] for s in r["steps"])[:900]
            style = f'„{r["title"]}"\nZutaten: {ingr}\nZubereitung: {steps}'
            break
    return "\n".join(lines) or "- keine", style


def _direction(d: dict) -> str:
    return f'{d.get("title_de")} – {d.get("idea_de")} (Format: {d.get("format")})'


def _finalize(raw: dict, slot: str, version: int, run_id: str, proposal_id: str, model: str, origin: str) -> dict:
    raw = {k: v for k, v in raw.items() if k not in ("slot", "version")}
    tip = raw.get("serving_tip")
    if isinstance(tip, str):
        raw["serving_tip"] = re.sub(r"^\s*unser tipp\s*:\s*", "", tip, flags=re.I)
    return {"recipe_id": f"{run_id}_{slot}", "slot": slot, "version": version, "proposal_id": proposal_id,
            "language": "de", **raw, "status": "draft", "model": model, "origin": origin}


def create_recipes(run_id: str) -> dict:
    """Two parallel calls (one per recipe); each knows the other's direction to keep them distinct."""
    sel = runs.selection(run_id)
    p, spec = sel["proposal"], sel["spec"]
    dirs = p.get("recipe_directions", [{}, {}])
    archive, style = _archive_context(p)
    common = dict(
        topic=p["topic"], title=p.get("title_de"), teaser=p.get("teaser_de", ""), gap=p.get("content_gap_de", "–"),
        risk=p.get("repetition_risk_de", "–"), servings=spec.get("servings", 2),
        max_minutes=f'{spec["max_total_minutes"]} Minuten' if spec.get("max_total_minutes") else "keine Vorgabe",
        notes=spec.get("notes") or "keine", archive=archive, style=style, fmt=RECIPE_FORMAT)
    runs.log_event(run_id, "drafting", "Recipe agent writing recipes A and B")

    def one(slot):
        mine, other = (dirs[0], dirs[1]) if slot == "A" else (dirs[1], dirs[0])
        user = USER_TEMPLATE.format(slot=slot, dir_self=_direction(mine), dir_other=_direction(other), **common)
        data, meta = chat_json("recipe_author", SYSTEM, user, max_tokens=16000, timeout=400, agent=f"recipe_{slot}")
        data = data.get("recipe", data)
        return _finalize(data, slot, 1, run_id, sel["proposal_id"], meta["model"], "recipe_agent"), meta

    try:
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(one, ["A", "B"]))
    except Exception as exc:
        runs.log_event(run_id, "draft_failed", str(exc)[:300])
        raise
    recipes = {}
    for recipe, meta in results:
        runs.save_recipe(run_id, recipe)
        recipes[recipe["slot"]] = recipe
    secs = max(m["seconds"] for _, m in results)
    runs.log_event(run_id, "drafted", f"2 recipes drafted by {results[0][1]['model'].split('/')[-1]} in {secs} s")
    return recipes


def revise_recipe(run_id: str, recipe: dict, report: str) -> dict:
    """Used by the review loop (block 4)."""
    body = {k: v for k, v in recipe.items() if k not in ("slot", "version", "status", "model", "origin", "recipe_id", "proposal_id", "language")}
    data, meta = chat_json("recipe_author", SYSTEM, REVISION_TEMPLATE.format(
        recipe=json.dumps(body, ensure_ascii=False, indent=1), report=report),
        max_tokens=12000, timeout=300, agent="recipe_revision")
    data = data.get("recipe", data)
    new = _finalize(data, recipe["slot"], recipe["version"] + 1, run_id, recipe["proposal_id"], meta["model"], "revision")
    runs.save_recipe(run_id, new)
    return new


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    out = create_recipes(sys.argv[1])
    for slot, r in out.items():
        print(f"\n== {slot}: {r['title']} ({r['servings']} {r.get('servings_unit')}, {r['times']})")
        for i in r["ingredients"]:
            print(f"   [{i.get('group') or '-'}] {i.get('quantity')} {i.get('unit') or ''} {i['name']}")
        for s in r["steps"]:
            print(f"   {s['number']}. {s['text'][:110]}")
        print(f"   Tipp: {r.get('serving_tip')}")
