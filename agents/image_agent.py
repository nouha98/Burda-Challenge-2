"""Image agent: writes a visual brief from the final recipe and generates the card image with FLUX.

Run standalone:  python -m agents.image_agent <run_id> <slot>
"""
import datetime as dt
import json
import sys

from services import flux
from services.gateway import chat_json
from storage import runs

SYSTEM = """You write prompts for realistic food photography for the German food magazine "das schmeckt!".
Respond only with a JSON object."""

USER_TEMPLATE = """Write an image prompt for this finished recipe. The image must show exactly this dish.

Recipe (German): {title}
Servings: {servings}
Ingredients: {ingredients}
Final preparation and serving: {final_steps}
Serving tip: {tip}

Rules:
- Show only ingredients that are actually in the recipe and visible in the finished dish; nothing else as garnish.
- Cut sizes, cooking method and texture must match the steps.
- Realistic, appetizing home-cooking food photography, served for {servings}, natural daylight, calm and tidy but warm,
  seasonal background, main dish clearly in focus; square format, dish centred with some space around it.
- No text, no logos, no hands, no people.

Format: {{"visible_ingredients": ["..."], "prompt": "English prompt, max. 90 words"}}"""


def image_path(run_id: str, recipe: dict):
    return runs.run_dir(run_id) / f"image_{recipe['slot']}_v{recipe['version']}.jpg"


def create_image(run_id: str, slot: str) -> dict:
    recipe = runs.latest_recipes(run_id)[slot]
    ingredients = ", ".join(
        f"{i.get('quantity') if i.get('quantity') is not None else ''} {i.get('unit') or ''} {i.get('name')}".strip()
        for i in recipe.get("ingredients") or [])
    steps = recipe.get("steps") or []
    brief, meta = chat_json("recipe_author", SYSTEM, USER_TEMPLATE.format(
        title=recipe.get("title"), servings=recipe.get("servings"), ingredients=ingredients,
        final_steps=" ".join(s.get("text", "") for s in steps[-2:]), tip=recipe.get("serving_tip")),
        max_tokens=4000, agent="image_brief")
    result = flux.generate(brief["prompt"])
    path = image_path(run_id, recipe)
    path.write_bytes(result["bytes"])
    info = {"slot": slot, "recipe_version": recipe["version"], "file": path.name, "image_model": result["model"],
            "job_id": result["job_id"], "seed": result.get("seed"), "seconds": result["seconds"],
            "prompt": brief["prompt"], "visible_ingredients": brief.get("visible_ingredients"),
            "prompt_model": meta["model"], "created_at": dt.datetime.now().isoformat(timespec="seconds")}
    runs.write_json(path.with_suffix(".json"), info)
    runs.log_event(run_id, "image_ready", f"{slot}: FLUX image for v{recipe['version']} ({result['seconds']} s)")
    return info


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(create_image(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
