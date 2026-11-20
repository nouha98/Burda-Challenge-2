"""Recipe archive: 5,000 das schmeckt! recipe XMLs (a category-stratified sample of 81,798).

Parsing follows challenge-2/data/recipe-archive/README.txt: read from d:head, keep group order,
sort ingredients by position only when all positions are numeric, keep raw quantities,
missing values stay missing, don't sum preparation-time types.
Ingredient/unit IDs are resolved with the topic map (rezepte_export_topicmap.sql).
"""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = ROOT / "challenge-2" / "data" / "recipe-archive"
XML_DIR = ARCHIVE_DIR / "rezepte_export"
MANIFEST = ARCHIVE_DIR / "auswahl_manifest.json"
TOPIC_SQL = ARCHIVE_DIR / "rezepte_export_topicmap.sql"
CACHE = ROOT / "runs" / "cache" / "archive_index.json"
NS = "{http://www.digicol.com/xmlns/dcx}"

_STR = r"'((?:[^'\\]|\\.)*)'"
_ROW = re.compile(r"\(\d+, " + _STR + ", " + _STR + r", (?:NULL|'(?:[^'\\]|\\.)*'), " + _STR + r"\)")


def load_topic_names() -> dict:
    """Topic ID -> first readable name. The SQL dump is parsed as text, never executed."""
    names = {}
    for tid, name, _inst in _ROW.findall(TOPIC_SQL.read_text(encoding="utf-8")):
        names.setdefault(tid, name.replace("\\'", "'"))
    return names


def _text(el):
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return v  # keep unusual raw values (e.g. "1-2") as text


def parse_recipe(path: Path, names: dict) -> dict:
    root = ET.parse(path).getroot()
    h = root.find(NS + "head")
    title = _text(h.find(NS + "Headline")) or _text(h.find(NS + "Title"))

    groups = []
    for grp in h.findall(NS + "CustomRecipeIngredients"):
        items = []
        for ing in grp.findall(NS + "CustomRecipeIngredient"):
            unit_topic = ing.get("unit_topic")
            unit = ing.get("unit") or (names.get(unit_topic) if unit_topic and unit_topic != "tm_topic_default_unit" else None)
            if unit and unit.strip("() ").lower() == "keine einheit":
                unit = None
            items.append({
                "name": ing.get("plural") or names.get(ing.get("topic")),
                "topic": ing.get("topic"),
                "amount": _num(ing.get("amount")),
                "amount_max": _num(ing.get("amount_max") or ing.get("max_amount")),
                "unit": unit,
                "prefix": ing.get("prefix"),
                "suffix": (ing.get("suffix") or "").strip() or None,
                "position": ing.get("position"),
                "quality_flags": {k: ing.get(k) for k in ("amount_error", "amount_max_error", "ingredient_error") if ing.get(k)},
            })
        if items and all(i["position"] and i["position"].isdigit() for i in items):
            items.sort(key=lambda i: int(i["position"]))
        groups.append({"header": _text(grp.find(NS + "CustomRecipeIngredientsHeader")), "items": items})

    steps = []
    for grp in h.findall(NS + "CustomRecipePreparationSteps"):
        content = _text(grp.find(NS + "CustomRecipePreparationsStepsContent"))
        if content:
            steps.append({"header": _text(grp.find(NS + "CustomRecipePreparationsStepsHeader")), "text": content})

    serving = h.find(NS + "CustomRecipeServing")
    nutrition = {}
    for key, tag in (("kcal", "Calories"), ("kj", "Kilojoule"), ("carbs_g", "Carbs"),
                     ("protein_g", "Protein"), ("fat_g", "Fat")):
        v = _text(h.find(NS + "CustomRecipeNutritionalValue" + tag))
        if v is not None:
            nutrition[key] = _num(v)

    return {
        "id": root.get("id"),
        "file": f"rezepte_export/{path.name}",
        "title": title,
        "subtitle": _text(h.find(NS + "SubHeadline")),
        "date_imported": (_text(h.find(NS + "DateImported")) or "")[:10] or None,
        "servings": {"amount": _num(serving.get("amount")), "unit": serving.get("plural")} if serving is not None else None,
        "times": [{"type": names.get(p.get("topic"), p.get("topic")), "minutes": _num(p.get("minutes"))}
                  for p in h.findall(NS + "CustomRecipePreparation")],
        "ingredient_groups": groups,
        "steps": steps,
        "tips": [t for t in (_text(x) for x in h.iter(NS + "CustomRecipeTippsContent")) if t],
        "nutrition_raw": nutrition or None,  # reference quantity not established (README)
        "keywords": sorted({names.get(k.get("topic"), "") for k in h.findall(NS + "Keywords")} - {""}),
    }


def build_index(force: bool = False) -> list[dict]:
    if CACHE.exists() and not force:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    names = load_topic_names()
    manifest = {r["id"]: r for r in json.loads(MANIFEST.read_text(encoding="utf-8"))["rezepte"]}
    recipes = []
    for path in sorted(XML_DIR.glob("*.xml")):
        r = parse_recipe(path, names)
        m = manifest.get(r["id"], {})
        r["category"] = m.get("hauptkategorie")
        r["christmas"] = m.get("weihnachtsrezept")
        recipes.append(r)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(recipes, ensure_ascii=False), encoding="utf-8")
    return recipes


def get_recipe(recipe_id: str) -> dict | None:
    return next((r for r in build_index() if r["id"] == recipe_id), None)
