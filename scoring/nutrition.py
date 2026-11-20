"""Deterministic part of the nutrition agent: quantity -> grams, and the nutrient arithmetic.

recipe_total = sum(grams_i * value_per_100g_i / 100); per_serving = recipe_total / servings.
Every conversion returns the rule it used; nothing is estimated silently.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "config" / "unit_weights.json").read_text(encoding="utf-8"))
NUTRIENTS = ["kcal", "kj", "fat_g", "carbs_g", "protein_g"]
SALT_PEPPER = re.compile(r"^(salz|pfeffer|salz und pfeffer|meersalz|pfeffer aus der mühle|schwarzer pfeffer)\b", re.I)


def _n(v) -> str:
    """German number format for rule texts."""
    return f"{v:g}".replace(".", ",")


def _kw(name: str, keywords: list[str], exact: bool = False) -> bool:
    n = name.lower()
    if exact:
        return n.strip() in keywords
    return any(k in n for k in keywords)


def grams_from_note(note: str | None):
    m = re.search(r"(?:ca\.\s*)?(\d+(?:[.,]\d+)?)\s*g\b", note or "")
    return float(m.group(1).replace(",", ".")) if m else None


def to_grams(ing: dict, food: dict | None) -> dict:
    """Return {"grams": float|None, "rule": str, "confidence": high|medium|low|none}."""
    name = ing.get("name") or ""
    q, unit = ing.get("quantity"), (ing.get("unit") or "").strip()
    if not isinstance(q, (int, float)):
        if SALT_PEPPER.match(name):
            return {"grams": None, "rule": "nach Geschmack – ohne Mengenangabe, nicht berechnet", "confidence": "none"}
        return {"grams": None, "rule": "keine Mengenangabe", "confidence": "none"}
    u = unit.lower().rstrip(".")
    if u in ("g", "gramm"):
        return {"grams": q, "rule": "Gewichtsangabe", "confidence": "high"}
    if u in ("kg",):
        return {"grams": q * 1000, "rule": "kg → g", "confidence": "high"}
    if u in ("ml", "l"):
        ml = q * (1000 if u == "l" else 1)
        if food and food.get("density"):
            return {"grams": ml * food["density"], "rule": f"{_n(ml)} ml × Dichte {_n(food['density'])} g/ml (Datenbank)", "confidence": "high"}
        for r in RULES["spoon_grams"]:
            if "ml_density" in r and _kw(name, r["keywords"]):
                return {"grams": ml * r["ml_density"], "rule": f"{_n(ml)} ml × {r['rule']}", "confidence": "medium"}
        if "öl" in name.lower():
            return {"grams": ml * 0.92, "rule": f"{_n(ml)} ml × Dichte 0,92 g/ml (Speiseöl, angenommen)", "confidence": "medium"}
        return {"grams": ml, "rule": f"{_n(ml)} ml × Dichte 1,0 g/ml (angenommen)", "confidence": "low"}
    if u in ("el", "tl"):
        key = u.upper()
        for r in RULES["spoon_grams"]:
            if _kw(name, r["keywords"]):
                if key in r:
                    return {"grams": q * r[key], "rule": f"1 {key} ≈ {_n(r[key])} g ({r['rule']})", "confidence": "medium"}
                ml = q * RULES["spoon_ml"][key]
                dens = (food or {}).get("density") or r["ml_density"]
                return {"grams": ml * dens, "rule": f"1 {key} = {RULES['spoon_ml'][key]} ml × {_n(dens)} g/ml", "confidence": "medium"}
        ml = q * RULES["spoon_ml"][key]
        return {"grams": ml, "rule": f"1 {key} = {RULES['spoon_ml'][key]} ml × 1,0 g/ml (angenommen)", "confidence": "low"}
    note_g = grams_from_note(ing.get("note"))
    if note_g is not None:
        return {"grams": note_g, "rule": f"Gewichtsangabe im Rezept („{ing.get('note')}“)", "confidence": "high"}
    if u in ("stück", "stk", "") or u.startswith("zehe"):
        for r in RULES["piece_grams"]:
            if _kw(name, r["keywords"], r.get("exact", False)) or (u.startswith("zehe") and "zehe" in r["keywords"]):
                return {"grams": q * r["g"], "rule": f"1 Stück ≈ {_n(r['g'])} g (essbarer Anteil, Küchenkonvention)", "confidence": "medium"}
        return {"grams": None, "rule": f"kein Stückgewicht für „{name}“ hinterlegt", "confidence": "none"}
    for unit_name, r in RULES["other_units"].items():
        if u == unit_name.lower():
            g = next((v for k, v in r.get("overrides", {}).items() if k in name.lower()), r["g"])
            return {"grams": q * g, "rule": f"1 {unit_name} ≈ {_n(g)} g ({r['rule']})", "confidence": "medium"}
    return {"grams": None, "rule": f"keine Umrechnungsregel für Einheit „{unit}“", "confidence": "none"}


def calculate(lines: list[dict], servings: int | float) -> dict:
    """lines: [{"grams", "food"(or None), ...}] -> totals, per serving, coverage."""
    total = {n: 0.0 for n in NUTRIENTS}
    missing_values = set()
    counted_g = total_g = 0.0
    for line in lines:
        g = line.get("grams")
        if g is None:
            continue
        total_g += g
        food = line.get("food")
        if not food:
            continue
        counted_g += g
        contrib = {}
        for n in NUTRIENTS:
            v = food["per_100g"].get(n)
            if v is None:
                missing_values.add(f"{food['name']}: {n}")
                continue
            contrib[n] = g * v / 100
            total[n] += contrib[n]
        line["contribution"] = {k: round(v, 1) for k, v in contrib.items()}
    per = {n: total[n] / servings for n in NUTRIENTS} if servings else {}
    return {
        "total": {k: round(v, 1) for k, v in total.items()},
        "per_serving": {k: round(v) if k in ("kcal", "kj") else round(v, 1) for k, v in per.items()},
        "weight_coverage": round(counted_g / total_g, 3) if total_g else None,
        "missing_values": sorted(missing_values),
    }
