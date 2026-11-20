from ingest.nutrition_db import foods, parse_value
from scoring.nutrition import calculate, to_grams


def test_parse_value_traces_and_decimals():
    assert parse_value("12,5") == (12.5, None)
    assert parse_value("Sp.")[0] == 0.0
    assert parse_value("k.A.")[0] is None


def test_unit_conversions_are_documented():
    assert to_grams({"name": "Mehl", "quantity": 200, "unit": "g"}, None)["grams"] == 200
    assert to_grams({"name": "Mehl", "quantity": 0.5, "unit": "kg"}, None)["grams"] == 500
    oil = to_grams({"name": "Rapsöl", "quantity": 2, "unit": "EL"}, None)
    assert abs(oil["grams"] - 27.6) < 1e-9 and "0,92" in oil["rule"]
    assert to_grams({"name": "Senf", "quantity": 1, "unit": "TL"}, None)["grams"] == 5
    milk = foods()["1194"]  # Milch (Durchschnitt), density 1,03
    assert abs(to_grams({"name": "Milch", "quantity": 200, "unit": "ml"}, milk)["grams"] - 206) < 1e-9
    assert to_grams({"name": "Zwiebel", "quantity": 2, "unit": "Stück"}, None)["grams"] == 160
    assert to_grams({"name": "Pinkel", "quantity": 2, "unit": "Stück", "note": "ca. 250 g"}, None)["grams"] == 250
    assert to_grams({"name": "Salz", "quantity": None, "unit": None}, None)["grams"] is None


def test_hand_checked_two_ingredient_calculation():
    fake = lambda kcal, fat: {"name": "x", "per_100g": {"kcal": kcal, "kj": kcal * 4.184, "fat_g": fat,
                                                         "carbs_g": 0, "protein_g": 0}}
    lines = [{"grams": 200, "food": fake(100, 10)}, {"grams": 50, "food": fake(800, 90)}]
    res = calculate(lines, servings=2)
    # (200*100 + 50*800)/100 = 600 kcal total -> 300 per serving; fat (20 + 45) / 2 = 32.5
    assert res["total"]["kcal"] == 600 and res["per_serving"]["kcal"] == 300
    assert res["per_serving"]["fat_g"] == 32.5
    assert calculate(lines, servings=4)["per_serving"]["kcal"] == 150


def test_unmatched_weight_lowers_coverage_not_zero_values():
    lines = [{"grams": 100, "food": {"name": "x", "per_100g": {"kcal": 50, "kj": 209, "fat_g": 1, "carbs_g": 1, "protein_g": 1}}},
             {"grams": 100, "food": None}]
    res = calculate(lines, servings=1)
    assert res["weight_coverage"] == 0.5 and res["per_serving"]["kcal"] == 50
