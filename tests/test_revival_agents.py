from pathlib import Path

from agents import image_agent, revival_editors


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


def test_selector_rejects_rule_breaks_and_fills(monkeypatch):
    answer = {"selection": [{"recipe_id": "a1"}, {"recipe_id": "a2"},  # same trend twice
                            {"recipe_id": "b1"}, {"recipe_id": "c1"},  # 3rd soup -> category limit
                            {"recipe_id": "zz"}]}                      # unknown id
    monkeypatch.setattr(revival_editors, "chat_json", lambda *a, **k: (answer, {"model": "m"}))
    sel = revival_editors.select(POOL, "Winter", excluded=set(), feedback=[])
    ids = [s["recipe"]["id"] for s in sel["selection"]]
    assert len(ids) == 5 and len({s["trend_id"] for s in sel["selection"]}) == 5
    cats = [s["recipe"]["category"] for s in sel["selection"]]
    assert max(cats.count(c) for c in set(cats)) <= revival_editors.MAX_PER_CATEGORY
    assert "a2" not in ids and "zz" not in ids and len(sel["validation_notes"]) == 3
    assert any(s["picked_by"] == "fallback" for s in sel["selection"])


def test_selector_respects_exclusions(monkeypatch):
    monkeypatch.setattr(revival_editors, "chat_json", lambda *a, **k: ({"selection": [{"recipe_id": "a1"}]}, {"model": "m"}))
    sel = revival_editors.select(POOL, "Winter", excluded={"a1"}, feedback=["a1 ersetzen"])
    assert "a1" not in [s["recipe"]["id"] for s in sel["selection"]]


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
