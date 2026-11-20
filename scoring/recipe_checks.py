"""Deterministic recipe checks, run before the LLM review.

Maps to the review checklist (Recipe Review Criteria.docx):
 4 every ingredient has a quantity (except salt/pepper) · 5 every ingredient is used ·
 6 quantities/units consistent incl. split quantities · 7 EL vs TL · 8 step order (numbering).
Severity: critical = recipe unusable · major = must be fixed · minor = should be fixed.
"""
import re

SALT_PEPPER = re.compile(r"^(salz|pfeffer|salz und pfeffer|meersalz|pfeffer aus der mühle|schwarzer pfeffer|"
                         r"fleur de sel|cayennepfeffer|muskat|muskatnuss|zucker zum bestreuen|puderzucker zum bestäuben)\b", re.I)
MAX_INGREDIENTS = 14


def _issue(code, severity, field, message, criterion=None):
    return {"source": "code", "code": code, "severity": severity, "field": field, "message_de": message,
            "criterion": criterion}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_recipe(r: dict, spec: dict | None = None) -> list[dict]:
    issues = []
    for f in ("title", "introduction", "servings", "times", "ingredients", "steps", "serving_tip"):
        if not r.get(f):
            issues.append(_issue("missing_field", "critical" if f in ("ingredients", "steps", "title") else "major",
                                 f, f"Pflichtfeld „{f}“ fehlt oder ist leer."))
    ingredients = r.get("ingredients") or []
    steps = r.get("steps") or []
    by_id = {}
    for i in ingredients:
        iid = i.get("id")
        if not iid or iid in by_id:
            issues.append(_issue("ingredient_id", "major", "ingredients", f"Zutat „{i.get('name')}“ hat keine eindeutige ID."))
        by_id[iid] = i
        exempt = bool(SALT_PEPPER.match((i.get("name") or "").strip()))
        if not exempt and not _num(i.get("quantity")):
            issues.append(_issue("missing_quantity", "major", f"ingredients.{iid}",
                                 f"„{i.get('name')}“ hat keine Mengenangabe.", 4))
        if not exempt and _num(i.get("quantity")) and not i.get("unit"):
            issues.append(_issue("missing_unit", "minor", f"ingredients.{iid}",
                                 f"„{i.get('name')}“ hat keine Einheit (z. B. Stück, g).", 6))

    used = {}
    for s in steps:
        for u in s.get("uses") or []:
            iid = u.get("ingredient_id")
            if iid not in by_id:
                issues.append(_issue("unknown_ingredient", "major", f"steps.{s.get('number')}",
                                     f"Schritt {s.get('number')} verwendet „{iid}“, das nicht in der Zutatenliste steht.", 5))
                continue
            used.setdefault(iid, []).append((s.get("number"), u))

    for iid, i in by_id.items():
        if iid not in used:
            issues.append(_issue("unused_ingredient", "major", f"ingredients.{iid}",
                                 f"„{i.get('name')}“ steht in der Zutatenliste, wird aber in keinem Schritt verwendet.", 5))
            continue
        if not _num(i.get("quantity")):
            continue
        unit = (i.get("unit") or "").strip()
        parts, units_ok = [], True
        for step_no, u in used[iid]:
            uu = (u.get("unit") or "").strip()
            if _num(u.get("quantity")):
                if uu and unit and uu != unit:
                    units_ok = False
                    sev = "major" if {uu.upper(), unit.upper()} == {"EL", "TL"} else "minor"
                    issues.append(_issue("unit_mismatch", sev, f"steps.{step_no}",
                                         f"„{i.get('name')}“: Liste {i['quantity']:g} {unit}, Schritt {step_no} nennt {u['quantity']:g} {uu}.",
                                         7 if sev == "major" else 6))
                parts.append(u["quantity"])
        if units_ok and parts and abs(sum(parts) - i["quantity"]) > 1e-6 * max(1, i["quantity"]):
            issues.append(_issue("split_mismatch", "major", f"ingredients.{iid}",
                                 f"„{i.get('name')}“: Liste {i['quantity']:g} {unit}, Summe in den Schritten {sum(parts):g} {unit}.", 6))

    numbers = [s.get("number") for s in steps]
    if numbers != list(range(1, len(steps) + 1)):
        issues.append(_issue("step_numbering", "minor", "steps", f"Schrittnummern sind nicht fortlaufend: {numbers}.", 8))

    t = r.get("times") or {}
    prep, cook, total = t.get("prep_minutes"), t.get("cook_minutes"), t.get("total_minutes")
    if not all(_num(x) for x in (prep, cook, total)):
        issues.append(_issue("times", "major", "times", "Zubereitungs-, Gar- und Gesamtzeit müssen als Minuten angegeben sein."))
    elif total < max(prep, cook) or total > prep + cook + 30:
        issues.append(_issue("times", "minor", "times",
                             f"Gesamtzeit {total} Min. passt nicht zu Arbeitszeit {prep} + Garzeit {cook} Min."))
    if spec:
        if spec.get("servings") and r.get("servings") != spec["servings"]:
            issues.append(_issue("servings", "major", "servings",
                                 f"Rezept ist für {r.get('servings')} Portionen, die Redaktion wünscht {spec['servings']}."))
        if spec.get("max_total_minutes") and _num(total) and total > spec["max_total_minutes"]:
            issues.append(_issue("max_time", "major", "times",
                                 f"Gesamtzeit {total} Min. überschreitet die Vorgabe von {spec['max_total_minutes']} Min."))
    if len(ingredients) > MAX_INGREDIENTS:
        issues.append(_issue("long_list", "minor", "ingredients",
                             f"{len(ingredients)} Zutaten – die Marke wünscht keine langen Zutatenlisten (Richtwert ≤ {MAX_INGREDIENTS})."))
    return issues


PANTRY = {"salz", "pfeffer", "öl", "rapsöl", "olivenöl", "butter", "zucker", "mehl", "wasser", "zwiebel", "zwiebeln",
          "knoblauch", "knoblauchzehe", "knoblauchzehen", "muskat", "gemüsebrühe", "fleischbrühe", "milch", "eier", "ei"}


def main_ingredients(r: dict) -> set[str]:
    return {(i.get("name") or "").lower().strip() for i in r.get("ingredients") or []} - PANTRY - {""}


def check_pair(a: dict, b: dict) -> list[dict]:
    """Recipes A and B must differ in more than garnish."""
    ma, mb = main_ingredients(a), main_ingredients(b)
    if not ma or not mb:
        return []
    overlap = len(ma & mb) / len(ma | mb)
    if overlap > 0.6:
        return [_issue("too_similar", "major", "ingredients",
                       f"Rezept A und B teilen {overlap:.0%} der Hauptzutaten – sie müssen sich deutlicher unterscheiden.")]
    return []


def check_archive_duplicate(r: dict, archive_titles: set[str]) -> list[dict]:
    if (r.get("title") or "").strip().lower() in archive_titles:
        return [_issue("archive_duplicate", "major", "title", f"Titel „{r['title']}“ existiert bereits im Archiv.")]
    return []
