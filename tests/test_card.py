from rendering.card import AI_LABEL, card_from_archive, card_from_generated, paginate, render


def recipe(n_steps=4, step_len=200, n_ing=8, title="Grünkohl-Eintopf"):
    return {
        "title": title, "introduction": "Intro", "servings": 2, "servings_unit": "Portionen", "version": 2,
        "times": {"prep_minutes": 20, "cook_minutes": 30, "total_minutes": 50},
        "ingredients": [{"id": f"i{k}", "name": f"Zutat {k}", "quantity": 1.5, "unit": "EL",
                         "group": "Für die Soße" if k > 4 else None} for k in range(n_ing)],
        "steps": [{"number": k + 1, "text": "Wort " * (step_len // 5), "temperature": None} for k in range(n_steps)],
        "serving_tip": "Tipp",
    }


NUT = {"per_serving": {"kcal": 500, "kj": 2092, "fat_g": 20.4, "carbs_g": 50, "protein_g": 30}, "complete": True}


def test_generated_card_has_required_parts():
    html = render(card_from_generated(recipe(), NUT))
    for part in (AI_LABEL, "Zutaten", "Für 2 Portionen", "Zubereitung", "Unser Tipp", "Nährwerte",
                 "500 kcal / 2092 kJ", "1,5 EL Zutat 0", "Für die Soße", "Seite 1 von 1"):
        assert part in html, part


def test_long_recipe_paginates_without_losing_steps():
    card = card_from_generated(recipe(n_steps=14, step_len=500, n_ing=24), NUT)
    pages = paginate(card)
    assert len(pages) >= 2
    steps = [b for p in pages for b in p["main"] if b["kind"] == "step" and isinstance(b["number"], int)]
    ings = [b for p in pages for b in p["side"] if b["kind"] == "ing"]
    assert len(steps) == 14 and len(ings) == 24
    html = render(card)
    assert f"Seite {len(pages)} von {len(pages)}" in html and "Fortsetzung" in html


def test_llm_text_is_escaped():
    html = render(card_from_generated(recipe(title='<script>alert(1)</script>'), NUT))
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_archive_card_keeps_values_and_states_missing_reference():
    r = {"id": "doc1", "title": "Rosenkohl-Suppe", "subtitle": None, "servings": {"amount": 4.0, "unit": "Personen"},
         "times": [{"type": "Zubereitung", "minutes": 55.0}],
         "ingredient_groups": [{"header": None, "items": [
             {"amount": 500.0, "amount_max": None, "unit": "g", "prefix": None, "name": "Rosenkohl", "suffix": None},
             {"amount": None, "amount_max": None, "unit": None, "prefix": None, "name": "Salz", "suffix": None}]}],
         "steps": [{"header": None, "text": "Rosenkohl putzen."}], "tips": [],
         "nutrition_raw": {"kcal": 300.0, "fat_g": 23.0}}
    html = render(card_from_archive(r))
    for part in ("500 g Rosenkohl", "Salz", "Für 4 Personen", "Zubereitung: 55 Min.", "300 kcal",
                 "Bezugsmenge nicht angegeben", "XML-Archivexport"):
        assert part in html, part
    assert AI_LABEL not in html
