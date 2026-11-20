import numpy as np

from scoring.hybrid import calibrate, retrieve


def trend(name):
    return {"id": "t1", "classification": {"name_de": name}, "wikipedia_article": name,
            "records": [], "scores": {"T": 80}}


def recipe(rid, title, ingredients=()):
    return {"id": rid, "title": title, "subtitle": None,
            "ingredient_groups": [{"header": None, "items": [{"name": n} for n in ingredients]}]}


def unit(v):
    v = np.array(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_calibrate_uses_the_top_group():
    sims = np.linspace(0.2, 0.7, 1000)
    cal = calibrate(sims)
    assert cal.max() == 1.0 and cal[-1] == 1.0       # best recipe = 1
    assert cal[500] == 0.0 and (cal > 0).sum() <= 11  # only the top 1 % carries signal


def test_semantic_hit_without_keyword_and_lexical_bonus():
    recipes = [recipe("a", "Rinderschmorbraten mit Paprika"), recipe("b", "Rindergulasch"),
               recipe("c", "Erdbeerkuchen")] + [recipe(f"x{k}", f"Anderes {k}") for k in range(200)]
    q = unit([1, 0, 0])
    vecs = np.vstack([unit([0.95, 0.3, 0]), unit([0.9, 0.4, 0]), unit([0, 1, 0])]
                     + [unit([0.1, 0.5, 1]) for _ in range(200)])
    hits = retrieve(trend("Gulasch"), q, recipes, vecs)
    ids = [h["recipe"]["id"] for h in hits]
    assert ids[0] == "b" and hits[0]["match"] == "title"          # keyword + semantic beats semantic only
    assert "a" in ids and next(h for h in hits if h["recipe"]["id"] == "a")["match"] == "semantic"
    assert "c" not in ids


def test_lexical_fallback_without_vectors():
    hits = retrieve(trend("Gulasch"), None, [recipe("b", "Rindergulasch"), recipe("a", "Schmorbraten")], None)
    assert [h["recipe"]["id"] for h in hits] == ["b"]
