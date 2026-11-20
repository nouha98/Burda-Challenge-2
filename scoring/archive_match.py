"""Archive check (deterministic): similar recipes, recurring ingredients/formats, most recent comparable recipe.

Matching is lexical on lowercased German text. A title match is strong evidence of a comparable
recipe; an ingredient match only shows the ingredient has been used. Results describe the
5,000-recipe sample, not the full 81,798-recipe archive.
"""
import collections
import datetime
import re

PANTRY = {"salz", "pfeffer", "zucker", "öl", "olivenöl", "rapsöl", "sonnenblumenöl", "butter", "wasser",
          "mehl", "eier", "ei", "milch", "zwiebel", "zwiebeln", "knoblauch", "knoblauchzehe", "knoblauchzehen",
          "muskat", "paprikapulver", "backpulver", "speisestärke", "puderzucker", "vanillezucker", "gemüsebrühe",
          "pflanzenöl", "salz und pfeffer", "pfeffer aus der mühle"}
FORMAT_WORDS = ["suppe", "eintopf", "auflauf", "gratin", "salat", "pfanne", "curry", "quiche", "tarte", "pasta",
                "nudeln", "risotto", "bowl", "braten", "schmorgericht", "kuchen", "torte", "plätzchen", "kekse",
                "muffins", "brot", "strudel", "gnocchi", "lasagne", "burger", "wrap", "pizza", "flammkuchen",
                "rouladen", "gulasch", "chips", "pesto", "dip", "smoothie", "punsch", "ofen", "blech", "frittata",
                "omelett", "püree", "stampf", "creme", "dessert", "tiramisu", "schnitten", "taler", "plätzchen"]
RECENT_SINCE = str(datetime.date.today() - datetime.timedelta(days=730))  # "recent" = last 24 months


def _variants(term: str) -> set[str]:
    t = re.sub(r"\s+", " ", term.lower()).strip()
    out = {t}
    for suffix in ("en", "n", "e", "s"):
        if len(t) >= 7 and t.endswith(suffix):
            out.add(t[: -len(suffix)])
    return {v for v in out if len(v) >= 4}


def search_terms(candidate: dict) -> list[str]:
    raw = [candidate["classification"].get("name_de", ""), candidate.get("wikipedia_article") or ""]
    raw += [r["term"] for r in candidate["records"] if r["source_kind"] == "query"]
    terms = set()
    for t in raw:
        for part in re.split(r"[()/,]", t):
            part = re.sub(r"\b(rezepte?|klassisch|recipe)\b", "", part.lower()).strip()
            if part:
                terms |= _variants(part)
    return sorted(terms)


def _matches(text: str | None, terms: list[str]) -> bool:
    return bool(text) and any(t in text.lower() for t in terms)


def check(candidate: dict, recipes: list[dict]) -> dict:
    terms = search_terms(candidate)
    title_hits = [r for r in recipes if _matches(r["title"], terms) or _matches(r.get("subtitle"), terms)]
    ingr_hits = [r for r in recipes if r not in title_hits and any(
        _matches(i["name"], terms) for g in r["ingredient_groups"] for i in g["items"])]
    title_hits.sort(key=lambda r: r["date_imported"] or "", reverse=True)
    ingr_hits.sort(key=lambda r: r["date_imported"] or "", reverse=True)

    co = collections.Counter()
    fmt = collections.Counter()
    for r in title_hits:
        names = {(i["name"] or "").lower() for g in r["ingredient_groups"] for i in g["items"]}
        co.update(n for n in names if n and n not in PANTRY and not any(t in n for t in terms))
        tl = (r["title"] or "").lower()
        fmt.update({w for w in FORMAT_WORDS if w in tl})

    def brief(r):
        return {"id": r["id"], "title": r["title"], "date_imported": r["date_imported"], "category": r["category"]}

    latest = title_hits[0] if title_hits else (ingr_hits[0] if ingr_hits else None)
    return {
        "search_terms": terms,
        "title_matches": len(title_hits),
        "title_matches_recent": sum(1 for r in title_hits if (r["date_imported"] or "") >= RECENT_SINCE),
        "ingredient_only_matches": len(ingr_hits),
        "most_recent_comparable": dict(brief(latest), match="title" if title_hits else "ingredient") if latest else None,
        "closest_recipes": [brief(r) for r in title_hits[:6]] or [brief(r) for r in ingr_hits[:3]],
        "recurring_ingredients": [n for n, _ in co.most_common(8)],
        "recurring_formats": [w for w, _ in fmt.most_common(6)],
        "coverage_note": "5,000-recipe sample of 81,798; date = DateImported (CMS import, not print date); lexical matching",
    }


def saturation_score(archive: dict) -> float:
    """0-100: higher = less covered in the archive sample (more room for something new)."""
    recent = archive["title_matches_recent"]
    total = archive["title_matches"]
    saturation = min(1.0, (recent * 2 + total) / 20)
    return round(100 * (1 - saturation), 1)
