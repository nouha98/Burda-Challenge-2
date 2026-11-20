"""Season / holiday context for a date, plus season signals from the current trends.

Weights 0-1 per archive label (labels as stored in the archive's CustomRecipeThesaurs field).
"""
import datetime as dt

SEASON_LABELS = ["Frühling", "Sommer", "Herbst", "Winter"]
OFF_SEASON = {  # labels that clash with a season
    "Herbst": {"Sommer", "Sommerparty", "Grillen", "Grillparty/ BBQ", "Frühling", "Ostern", "Eis"},
    "Winter": {"Sommer", "Sommerparty", "Grillen", "Grillparty/ BBQ", "Frühling", "Ostern", "Eis"},
    "Frühling": {"Herbst", "Winter", "Weihnachten", "Advent", "Silvester/ Neujahr", "Halloween"},
    "Sommer": {"Herbst", "Winter", "Weihnachten", "Advent", "Silvester/ Neujahr", "Halloween"},
}
CHRISTMAS_SPECIALITIES = ["lebkuchen", "spekulatius", "vanillekipferl", "zimtstern", "stollen", "dominostein",
                          "pfefferkuchen", "printen", "glühwein", "pfeffernüsse", "bethmännchen", "plätzchen",
                          "spritzgebäck", "engelsaugen", "husarenkrapferl", "linzer", "spitzbuben", "kokosmakronen",
                          "weihnacht", "gebrannte mandeln", "bratapfel"]


def first_advent(year: int) -> dt.date:
    christmas = dt.date(year, 12, 25)
    return christmas - dt.timedelta(days=christmas.weekday() + 1 + 21)  # 4th Sunday before Christmas


def date_weights(day: dt.date) -> dict:
    w = {}
    m = day.month
    season = ("Winter" if m in (12, 1, 2) else "Frühling" if m in (3, 4, 5) else "Sommer" if m in (6, 7, 8) else "Herbst")
    w[season] = 1.0
    if m == 11:  # winter dishes (Grünkohl after the first frost, Eintöpfe) are in season from mid-November
        w["Winter"] = 1.0 if day.day >= 15 else 0.8
    if m == 2:
        w["Frühling"] = 0.5
    if m == 8:
        w["Herbst"] = 0.4
    advent = first_advent(day.year)
    days_to_advent = (advent - day).days
    if day.month in (11, 12) and day <= dt.date(day.year, 12, 24):
        w["Advent"] = 1.0 if days_to_advent <= 0 else max(0.6, 1 - days_to_advent / 30)
        w["Weihnachten"] = 1.0 if day.month == 12 else max(0.6, 1 - days_to_advent / 40)
        w["Geschenke aus der Küche"] = 0.6
    if (m == 12 and day.day >= 20) or (m == 1 and day.day <= 2):
        w["Silvester/ Neujahr"] = 1.0
    elif m == 12 or (m == 11 and day.day >= 15):
        w["Silvester/ Neujahr"] = 0.3
    if m == 10 or (m == 11 and day.day <= 2):
        w["Halloween"] = 0.8 if m == 10 else 0.2
    if m in (3, 4):
        w["Ostern"] = 0.7
    if m in (6, 7, 8):
        w.update({"Grillen": 0.9, "Grillparty/ BBQ": 0.9, "Sommerparty": 0.8, "Eis": 0.8})
    return w


def trend_christmas_share(trend_candidates: list[dict]) -> float:
    """Share of the rising trends' score mass that comes from Christmas specialities."""
    total = xmas = 0.0
    for c in trend_candidates:
        t = c["scores"]["T"]
        total += t
        text = " ".join([c["classification"].get("name_de", ""), c.get("wikipedia_article") or ""]
                        + [r["term"] for r in c["records"]]).lower()
        if any(k in text for k in CHRISTMAS_SPECIALITIES):
            xmas += t
    return xmas / total if total else 0.0


def season_context(day: dt.date, trend_candidates: list[dict]) -> dict:
    weights = date_weights(day)
    share = trend_christmas_share(trend_candidates)
    if share >= 0.15:  # trends clearly show Christmas baking/occasion
        for label in ("Advent", "Weihnachten"):
            weights[label] = min(1.0, weights.get(label, 0) + 0.3)
    season = max((s for s in SEASON_LABELS if s in weights), key=lambda s: weights[s])
    off = set()
    for s in SEASON_LABELS:
        if weights.get(s, 0) >= 0.8:
            off |= OFF_SEASON[s]
    off -= set(weights)
    return {"date": str(day), "season": season, "weights": dict(sorted(weights.items(), key=lambda kv: -kv[1])),
            "off_season": sorted(off), "trend_christmas_share": round(share, 2),
            "reason": f"Datum {day:%d.%m.%Y}: {season}"
                      + (f", Advent ab {first_advent(day.year):%d.%m.}" if "Advent" in weights else "")
                      + f"; {share:.0%} der steigenden Trend-Punkte sind Weihnachtsspezialitäten"}


def season_fit(recipe: dict, ctx: dict) -> tuple[float, list[str]]:
    """0-1. Best matching current label; 0.4 if the recipe has no season label; 0 if only off-season labels."""
    labels = set(recipe.get("labels") or [])
    if recipe.get("christmas"):
        labels.add("Weihnachten")
    matched = {l: ctx["weights"][l] for l in labels if l in ctx["weights"]}
    if matched:
        best = max(matched.values())
        return best, sorted(matched, key=lambda l: -matched[l])
    clashes = sorted(labels & set(ctx["off_season"]))
    if clashes:
        return 0.0, [f"außer Saison: {', '.join(clashes)}"]
    return 0.4, []
