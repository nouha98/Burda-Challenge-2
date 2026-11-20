from scoring.recipe_checks import check_pair, check_recipe


def base_recipe(**over):
    r = {
        "title": "Test", "introduction": "Intro", "servings": 2, "serving_tip": "Tipp",
        "times": {"prep_minutes": 10, "cook_minutes": 20, "total_minutes": 30},
        "ingredients": [
            {"id": "i1", "name": "Butter", "quantity": 40, "unit": "g"},
            {"id": "i2", "name": "Salz", "quantity": None, "unit": None},
            {"id": "i3", "name": "Senf", "quantity": 1, "unit": "EL"},
        ],
        "steps": [
            {"number": 1, "text": "…", "uses": [{"ingredient_id": "i1", "quantity": 20, "unit": "g"},
                                              {"ingredient_id": "i2"}]},
            {"number": 2, "text": "…", "uses": [{"ingredient_id": "i1", "quantity": 20, "unit": "g"},
                                              {"ingredient_id": "i3", "quantity": 1, "unit": "EL"}]},
        ],
    }
    r.update(over)
    return r


def codes(issues):
    return {i["code"] for i in issues}


def test_clean_recipe_has_no_issues():
    assert check_recipe(base_recipe(), {"servings": 2}) == []


def test_unused_and_unknown_ingredient():
    r = base_recipe()
    r["ingredients"].append({"id": "i4", "name": "Petersilie", "quantity": 1, "unit": "Bund"})
    r["steps"][0]["uses"].append({"ingredient_id": "i9", "quantity": 1, "unit": "g"})
    assert {"unused_ingredient", "unknown_ingredient"} <= codes(check_recipe(r))


def test_split_quantity_mismatch():
    r = base_recipe()
    r["steps"][1]["uses"][0]["quantity"] = 30  # 20 + 30 != 40
    assert "split_mismatch" in codes(check_recipe(r))


def test_el_tl_confusion_is_major():
    r = base_recipe()
    r["steps"][1]["uses"][1]["unit"] = "TL"
    issues = [i for i in check_recipe(r) if i["code"] == "unit_mismatch"]
    assert issues and issues[0]["severity"] == "major" and issues[0]["criterion"] == 7


def test_missing_quantity_except_salt():
    r = base_recipe()
    r["ingredients"][2]["quantity"] = None
    found = [i for i in check_recipe(r) if i["code"] == "missing_quantity"]
    assert len(found) == 1 and "Senf" in found[0]["message_de"]


def test_servings_spec_and_pair_similarity():
    assert "servings" in codes(check_recipe(base_recipe(servings=4), {"servings": 2}))
    assert "too_similar" in codes(check_pair(base_recipe(), base_recipe()))
