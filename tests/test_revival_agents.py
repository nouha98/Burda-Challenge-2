from pathlib import Path

import random

from agents import image_agent, revival_editors
from scoring.revival import draw


def cand(rid, trend_id, cat, score=80):
    r = {"id": rid, "title": f"Rezept {rid}", "category": cat, "steps": [{"text": "x"}],
         "ingredient_groups": [{"header": None, "items": [{"name": "Zutat"}]}]}
    return {"recipe": r, "trend_id": trend_id, "trend": f"Trend {trend_id}", "score": score, "match": "title",
            "season_labels": ["Winter"]}


def pool_of(spec):
    pool = {}
    for rid, tid, cat, score in spec:
        pool.setdefault(tid, {"trend": {"classification": {"name_de": tid}, "scores": {"T": 70}}, "candidates": []})
        pool[tid]["candidates"].append(cand(rid, tid, cat, score))
    return pool


POOL = pool_of([("a1", "t1", "Suppen", 90), ("a2", "t1", "Suppen", 80), ("b1", "t2", "Suppen", 88),
                ("c1", "t3", "Suppen", 87), ("d1", "t4", "Desserts", 86), ("e1", "t5", "Fleisch", 85),
                ("f1", "t6", "Gebäck", 70)])


def test_review_forces_replace_when_trend_does_not_match(monkeypatch):
    selection = [cand("a1", "t1", "Suppen"), cand("d1", "t4", "Desserts")]
    answer = {"items": [{"recipe_id": "a1", "trend_match": "none", "verdict": "keep"},
                        {"recipe_id": "d1", "trend_match": "strong", "verdict": "keep"}], "variety_ok": True,
              "retrieve_again": ["t1", "unknown"]}
    monkeypatch.setattr(revival_editors, "chat_json", lambda *a, **k: (answer, {"model": "m"}))
    rev = revival_editors.review(selection, POOL, "Winter")
    verdicts = {v["recipe_id"]: v["verdict"] for v in rev["items"]}
    assert verdicts == {"a1": "replace", "d1": "keep"} and not rev["all_ok"] and rev["retrieve_again"] == ["t1"]


def test_image_is_regenerated_once_on_mismatch(monkeypatch, tmp_path):
    calls = {"gen": [], "check": 0}

    def fake_generate(view, path, agent="", corrections=None):
        calls["gen"].append(corrections)
        Path(path).write_bytes(b"img")
        return {"file": Path(path).name, "prompt": "p", "seed": 1, "cost_credits": 0.9}

    def fake_validate(path, view):
        calls["check"] += 1
        if calls["check"] == 1:
            return {"verdict": "mismatch", "wrong": ["Löffelbiskuits liegen oben"], "missing": [], "extra": [],
                    "fix_instructions_en": "ladyfingers only inside the layers"}
        return {"verdict": "match"}

    monkeypatch.setattr(image_agent, "generate_image", fake_generate)
    monkeypatch.setattr(image_agent, "validate_image", fake_validate)
    monkeypatch.setattr(image_agent.runs, "write_json", lambda *a, **k: None)
    info = image_agent.generate_validated({"title": "Tiramisu"}, tmp_path / "x.jpg", progress=lambda m: None)
    assert len(calls["gen"]) == 2 and calls["gen"][0] is None and "inside the layers" in calls["gen"][1]
    assert info["status"] == "ok" and info["attempts"][0]["rejected_file"] == "x_rejected1.jpg"
    assert (tmp_path / "x_rejected1.jpg").exists()


def test_image_regeneration_is_bounded(monkeypatch, tmp_path):
    n = {"gen": 0}

    def fake_generate(view, path, agent="", corrections=None):
        n["gen"] += 1
        Path(path).write_bytes(b"img")
        return {"file": Path(path).name, "prompt": "p"}

    monkeypatch.setattr(image_agent, "generate_image", fake_generate)
    monkeypatch.setattr(image_agent, "validate_image", lambda p, v: {"verdict": "mismatch", "fix_instructions_en": "x"})
    monkeypatch.setattr(image_agent.runs, "write_json", lambda *a, **k: None)
    info = image_agent.generate_validated({"title": "t"}, tmp_path / "y.jpg", progress=lambda m: None)
    assert n["gen"] == image_agent.MAX_REGENERATIONS + 1 and info["status"] == "needs_editor_review"


def test_draw_is_random_per_seed_but_reproducible():
    pool = [cand(f"r{k}", "t1", "Suppen") for k in range(10)]
    a = [s["recipe"]["id"] for s in draw(pool, 3, random.Random(1))]
    b = [s["recipe"]["id"] for s in draw(pool, 3, random.Random(1))]
    others = {tuple(s["recipe"]["id"] for s in draw(pool, 3, random.Random(seed))) for seed in range(2, 12)}
    assert a == b and len(set(a)) == 3                # same seed -> same picks, no duplicates
    assert len(others) > 5                            # different seeds -> different picks


def test_draw_respects_exclusions_and_small_pools():
    pool = [cand(f"r{k}", "t1", "Suppen") for k in range(4)]
    picks = draw(pool, 3, random.Random(7), exclude={"r0", "r1"})
    assert {s["recipe"]["id"] for s in picks} == {"r2", "r3"}
