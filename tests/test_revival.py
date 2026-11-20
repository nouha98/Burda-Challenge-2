import datetime as dt

from scoring.revival import MAX_PER_TREND, rank
from scoring.season import date_weights, first_advent, season_context, season_fit


def trend(cid, name, T, terms=()):
    return {"id": cid, "classification": {"name_de": name}, "wikipedia_article": name,
            "records": [{"term": t, "source_kind": "query"} for t in terms], "scores": {"T": T, "is_rising": True}}


def recipe(rid, title, labels=(), christmas=False, ingredients=("Zutat a", "Zutat b", "Zutat c")):
    return {"id": rid, "title": title, "subtitle": None, "labels": list(labels), "christmas": christmas,
            "category": "x", "date_imported": "2024-01-01", "servings": {"amount": 4}, "times": [{"minutes": 30}],
            "steps": [{"text": "a"}, {"text": "b"}],
            "ingredient_groups": [{"header": None, "items": [{"name": n} for n in ingredients]}]}


def test_first_advent_and_calendar():
    assert first_advent(2026) == dt.date(2026, 11, 29)
    nov = date_weights(dt.date(2026, 11, 20))
    assert nov["Herbst"] == 1.0 and nov["Winter"] == 1.0 and nov["Advent"] >= 0.6 and nov["Weihnachten"] >= 0.6
    jul = date_weights(dt.date(2026, 7, 10))
    assert jul["Sommer"] == 1.0 and "Weihnachten" not in jul


def test_trend_christmas_boost_and_season_fit():
    trends = [trend("t1", "Vanillekipferl", 70), trend("t2", "Grünkohl", 80)]
    ctx = season_context(dt.date(2026, 11, 5), trends)
    assert ctx["trend_christmas_share"] > 0.15
    assert season_fit(recipe("r1", "x", ["Winter"]), ctx)[0] > 0.5
    assert season_fit(recipe("r2", "x", christmas=True), ctx)[1] == ["Weihnachten"]
    assert season_fit(recipe("r3", "x", ["Sommer"]), ctx)[0] == 0.0  # off-season, still ranked (bonus, not filter)
    assert season_fit(recipe("r4", "x"), ctx)[0] == 0.4             # no season label = neutral


def test_rank_prefers_title_matches_and_limits_per_trend():
    trends = [trend("t1", "Grünkohl", 80), trend("t2", "Gulasch", 70)]
    ctx = season_context(dt.date(2026, 11, 20), trends)
    recipes = [recipe(f"g{k}", f"Grünkohl-Gericht {k}", ["Winter"]) for k in range(5)]
    recipes += [recipe("s1", "Sommersalat", ["Sommer"], ingredients=("Grünkohl", "Gurke", "Tomate")),
                recipe("u1", "Rindergulasch", ["Winter"])]
    top = rank(trends, recipes, ctx, top_n=10)
    per_trend = {}
    for t in top:
        per_trend[t["trend"]] = per_trend.get(t["trend"], 0) + 1
    assert max(per_trend.values()) <= MAX_PER_TREND
    assert top[0]["match"] == "title" and top[0]["trend"] == "Grünkohl"
    assert "Rindergulasch" in [t["recipe"]["title"] for t in top]
