"""Brand agent: rates brand fit, feasibility and archive gap for trend candidates (GLM-5.3-Flash).

The model gives anchored 0-5 ratings with reasons; all weighting and totals are computed in code.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.gateway import GatewayError, chat_json

ROOT = Path(__file__).resolve().parents[1]
BRAND_RULES = (ROOT / "config" / "brand_rules.md").read_text(encoding="utf-8")

BRAND_WEIGHTS = {"seasonality_regional": 0.25, "ingredient_accessibility": 0.25, "everyday_practicality": 0.20,
                 "culinary_appeal": 0.15, "magazine_style": 0.15}
FEASIBILITY_KEYS = ["shopping", "equipment", "effort", "recipe_development"]

SYSTEM = f"""Du bist der Brand-Agent der Zeitschrift "das schmeckt!" (Burda). Du bewertest Food-Trends
für die Rezeptentwicklung streng anhand der Markenregeln. Antworte ausschließlich mit einem JSON-Objekt.

{BRAND_RULES}

Skala für JEDE Bewertung (0–5):
0 = unvereinbar; 1 = schwach; 2 = starke Anpassung nötig; 3 = akzeptabel mit Änderungen;
4 = starker Fit; 5 = starker Fit, belegt durch konkrete Hinweise aus den gelieferten Daten.
Jede Bewertung braucht eine kurze Begründung (max. 20 Wörter). Erfinde keine Zahlen und keine Quellen."""

USER_TEMPLATE = """Bewerte diese Trend-Kandidaten. Heute ist der 20.11.2026 (Spätherbst, Adventszeit beginnt).

{candidates}

Für jeden Kandidaten:
- brand: seasonality_regional, ingredient_accessibility, everyday_practicality, culinary_appeal, magazine_style
- feasibility: shopping (Zutaten im Supermarkt), equipment (normale Küche), effort (alltagstauglicher Aufwand), recipe_development (lässt sich daraus ein neues, gutes Rezept entwickeln)
- archive: gap_fit (0–5: gibt es eine konkrete, sinnvolle Lücke gegenüber den vorhandenen Archivrezepten?), content_gap_de (1 Satz: welche Lücke – z. B. fehlendes Format, Zubereitungsart oder Anlass), repetition_risk ("low" | "medium" | "high"), repetition_reason_de (1 Satz)
- unsuitable: true nur, wenn das Thema grundsätzlich nicht zu das schmeckt! passt; dann unsuitable_reason_de

Format:
{{"assessments": [{{"id": "...",
  "brand": {{"seasonality_regional": {{"score": 0, "reason": "..."}}, "ingredient_accessibility": {{...}}, "everyday_practicality": {{...}}, "culinary_appeal": {{...}}, "magazine_style": {{...}}}},
  "feasibility": {{"shopping": {{"score": 0, "reason": "..."}}, "equipment": {{...}}, "effort": {{...}}, "recipe_development": {{...}}}},
  "archive": {{"gap_fit": {{"score": 0, "reason": "..."}}, "content_gap_de": "...", "repetition_risk": "...", "repetition_reason_de": "..."}},
  "unsuitable": false, "unsuitable_reason_de": null}}]}}"""


def describe(c: dict) -> str:
    s, a, w = c["scores"], c["archive"], c.get("wikimedia") or {}
    brave = c.get("brave", {}).get("results", [])[:3]
    lines = [
        f'### id {c["id"]}: {c["classification"]["name_de"]} ({c["classification"]["kind"]})',
        f'Relevanz laut Trend-Agent: {c["classification"]["relevance_de"]}',
        f'Google Trends: bestes Wachstum {s["best_google_growth_percent"]:.0f} %, Suchbegriffe: '
        + ", ".join(sorted({r["term"] for r in c["records"]})),
        f'Wikipedia ({c.get("wikipedia_article")}): {w.get("latest_7d_views")} Aufrufe in 7 Tagen, '
        f'Veränderung {s["wikipedia_change"]:+.0%}' if s["wikipedia_change"] is not None else "Wikipedia: unbekannt",
        f'Archiv (Stichprobe von 5.000 Rezepten): {a["title_matches"]} Rezepte mit dem Thema im Titel, '
        f'davon {a["title_matches_recent"]} in den letzten 24 Monaten; häufige Formate: {", ".join(a["recurring_formats"]) or "–"}; '
        f'häufige weitere Zutaten: {", ".join(a["recurring_ingredients"][:6]) or "–"}',
        "Beispiele aus dem Archiv: " + ("; ".join(f'„{r["title"]}" ({r["date_imported"]})' for r in a["closest_recipes"]) or "keine"),
    ]
    if brave:
        lines.append("Aktuelle Web-Ergebnisse (Brave): " + " | ".join(f'{b["title"]}: {(b["description"] or "")[:120]}' for b in brave))
    return "\n".join(lines)


def _rating(block: dict, key: str) -> float | None:
    try:
        v = float(block[key]["score"])
        return max(0.0, min(5.0, v))
    except (KeyError, TypeError, ValueError):
        return None


def compute_scores(assessment: dict) -> dict:
    brand = assessment.get("brand", {})
    feas = assessment.get("feasibility", {})
    b_vals = {k: _rating(brand, k) for k in BRAND_WEIGHTS}
    f_vals = [_rating(feas, k) for k in FEASIBILITY_KEYS]
    B = 20 * sum(BRAND_WEIGHTS[k] * v for k, v in b_vals.items()) if None not in b_vals.values() else None
    F = 20 * sum(f_vals) / len(f_vals) if None not in f_vals else None
    gap = _rating(assessment.get("archive", {}), "gap_fit")
    return {"B": round(B, 1) if B is not None else None, "F": round(F, 1) if F is not None else None,
            "gap_fit_0_100": round(gap * 20, 1) if gap is not None else None}


def assess(candidates: list[dict], batch_size: int = 4) -> dict:
    batches = [candidates[i:i + batch_size] for i in range(0, len(candidates), batch_size)]

    def run(batch):
        user = USER_TEMPLATE.format(candidates="\n\n".join(describe(c) for c in batch))
        try:
            data, meta = chat_json("brand", SYSTEM, user, max_tokens=14000, agent="brand")
        except GatewayError as exc:
            print(f"  brand batch failed: {exc}")
            return {}
        ids = {c["id"] for c in batch}
        return {a["id"]: dict(a, model=meta["model"]) for a in data.get("assessments", []) if a.get("id") in ids}

    out = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for part in pool.map(run, batches):
            out.update(part)
    return out


if __name__ == "__main__":
    print(json.dumps(BRAND_WEIGHTS))
