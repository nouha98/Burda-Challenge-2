"""Swiss Food Composition Database V 7.1 (generic foods): values per 100 g edible portion."""
import csv
import difflib
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "challenge-2" / "data" / "nutrition" / "Schweizer_Nahrwertdatenbank(Generische Lebensmittel).csv"
SOURCE = "Schweizer Nährwertdatenbank – Generische Lebensmittel V 7.1"
COLUMNS = {"kj": "Energie, Kilojoule (kJ)", "kcal": "Energie, Kilokalorien (kcal)", "fat_g": "Fett, total (g)",
           "carbs_g": "Kohlenhydrate, verfügbar (g)", "protein_g": "Protein (g)"}


def parse_value(v: str):
    """German decimals; 'Sp.' (traces) and '<x' are treated as 0 and reported as such."""
    v = (v or "").strip()
    if not v or v == "k.A.":
        return None, "keine Angabe"
    if v == "Sp." or v.startswith("<"):
        return 0.0, f"Spur ({v})"
    return float(v.replace(",", ".")), None


def norm(text: str) -> str:
    t = (text or "").lower().replace("ß", "ss")
    return re.sub(r"\s+", " ", t).strip()


@lru_cache(maxsize=1)
def foods() -> dict:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    header, data = rows[2], rows[3:]
    idx = {name: header.index(col) for name, col in COLUMNS.items()}
    out = {}
    for r in data:
        values, notes = {}, {}
        for name, i in idx.items():
            values[name], note = parse_value(r[i])
            if note:
                notes[name] = note
        out[r[0]] = {"id": r[0], "name": r[3], "synonyms": r[4], "category": r[5],
                     "density": float(r[6].replace(",", ".")) if r[6] else None,
                     "per_100g": values, "value_notes": notes}
    return out


def candidates(terms: list[str], limit: int = 12) -> list[dict]:
    """Lexical candidates for a list of search terms (name before the comma weighs most)."""
    scored = {}
    for food in foods().values():
        name = norm(food["name"])
        head = name.split(",")[0].split("(")[0].strip()
        hay = name + " " + norm(food["synonyms"])
        best = 0.0
        for term in terms:
            t = norm(term)
            if not t:
                continue
            s = difflib.SequenceMatcher(None, t, head).ratio()
            if t == head:
                s += 1.0
            elif re.search(r"\b" + re.escape(t) + r"\b", hay):
                s += 0.6
            elif t in hay:
                s += 0.3
            if ", roh" in name or name.endswith("roh"):
                s += 0.05
            best = max(best, s)
        if best > 0.55:
            scored[food["id"]] = best
    top = sorted(scored, key=scored.get, reverse=True)[:limit]
    return [foods()[i] for i in top]
