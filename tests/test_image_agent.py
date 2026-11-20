from agents.image_agent import USER_TEMPLATE, ingredient_context, recipe_instruction_evidence


def test_ingredient_context_scales_quantities_in_code():
    recipe = {"servings": 2, "ingredients": [
        {"name": "Kartoffeln", "quantity": 500, "unit": "g"},
        {"name": "Möhren", "quantity": 350, "unit": "g"},
        {"name": "Grünkohl", "quantity": 300, "unit": "g"},
        {"name": "Schmand", "quantity": 100, "unit": "g"},
    ]}
    context = ingredient_context(recipe)
    assert "Kartoffeln: 500 g total; 250 g per serving" in context
    assert "Möhren: 350 g total; 175 g per serving" in context
    assert "Grünkohl: 300 g total; 150 g per serving" in context
    assert "Schmand: 100 g total; 50 g per serving" in context
    assert recipe["ingredients"][0]["quantity"] == 500


def test_ingredient_context_retains_notes_and_unknown_quantities():
    context = ingredient_context({"servings": 2, "ingredients": [
        {"name": "Kassler", "quantity": 250, "unit": "g", "note": "am Stück"},
        {"name": "Salz", "quantity": None, "unit": None},
    ]})
    assert "Kassler (am Stück): 250 g total; 125 g per serving" in context
    assert "Salz: quantity not specified" in context


def test_ingredient_context_fails_safe_without_valid_servings():
    context = ingredient_context({"servings": 0, "ingredients": [
        {"name": "Butter", "quantity": 1.25, "unit": "EL"},
    ]})
    assert context == "Butter: 1.25 EL total; per-serving quantity unavailable"


def test_recipe_instruction_evidence_preserves_full_step_text():
    steps = [{"number": 1, "text": "Kartoffeln waschen und in 1 cm dicke Spalten schneiden.",
              "duration_minutes": 20, "temperature": None, "uses": []}]
    evidence = recipe_instruction_evidence({"steps": steps})
    assert evidence == [{"number": 1, "instruction": steps[0]["text"], "duration_minutes": 20, "temperature": None}]
    assert recipe_instruction_evidence({}) == []


def test_prompt_orders_recipe_then_ingredients_then_plating_then_photography():
    stages = [USER_TEMPLATE.index("Step 1 – define the finished recipe result"),
              USER_TEMPLATE.index("Step 2 – describe the visible ingredients"),
              USER_TEMPLATE.index("Step 3 – establish the recipe's final plating"),
              USER_TEMPLATE.index("Step 4 – write the prompt")]
    assert stages == sorted(stages)
    assert "finished recipe result → ingredients with proportions and" in USER_TEMPLATE
    assert '"recipe_result"' in USER_TEMPLATE
