"""Image agent: writes a visual brief from the final recipe and generates the card image with FLUX.

Run standalone:  python -m agents.image_agent <run_id> <slot>
"""
import datetime as dt
import json
import sys

from services import flux
from services.gateway import chat_json
from storage import runs

SYSTEM = """You are a food stylist and photographer briefing an image model for the German food magazine "das schmeckt!".
You know exactly how German and regional ingredients look in real life, raw and after cooking.
The image model does NOT reliably know German or regional food names, so you describe appearance instead of naming.
Respond only with a JSON object."""

USER_TEMPLATE = """Brief a photo of this finished recipe as it really looks when cooked at home following these exact steps.

Recipe (German): {title}
Servings: {servings}
Ingredients: {ingredients}
All preparation steps: {steps}
Serving tip: {tip}

Step 1 – for every ingredient that is VISIBLE in the finished dish, describe its real-life appearance in the state the
steps leave it in (raw, braised, roasted, mashed, melted …): colour (precise, e.g. "dark olive green", "greyish brown"),
surface and texture, shape, cut size in cm, how many pieces per portion, and what typically distinguishes it from
similar-looking foods (e.g. a coarse grain sausage is NOT a smooth frankfurter; smoked cured pork loin is NOT boiled ham).
Ingredients dissolved in the sauce or used only for seasoning are not visible – leave them out.

Step 2 – write the image prompt.
PRIORITY: realism comes before appeal. Appeal must never change how an ingredient really looks. For every component,
reuse the colour, texture and shape from your step-1 description word for word (e.g. braised kale stays very dark,
almost black-green and soft – never light green; a sausage keeps its real casing colour). Use the most specific
English food term or a plain description; never substitute a different vegetable or meat (kale is not "cabbage").
Consistency must match the steps (a stew thickened with crushed potatoes is thick and spoonable, not a soup).
- Start with "Close-up of", the dish and vessel, then each visible component using your appearance descriptions – no German food names,
  no brand names.
- Where texture identifies a food, show it (e.g. one sausage cut open to reveal its interior).
- Make it as appealing as possible while staying true to real food – the brand's photo rule is "yummy, focus on the main
  motif, ingredients clearly recognisable, makes you full and happy". Achieve appeal through styling, not adjectives:
  freshly served and hot (a little steam where the dish is hot), natural sheen from fat, butter or sauce, the most
  attractive components placed on top and facing the camera (e.g. sliced meat, a cut-open sausage, browned edges),
  clear colour contrast between components, golden or browned surfaces where the steps brown them, a clean plate rim,
  a generous but realistic portion for {servings}. Sauce or broth as thick or thin as the steps make it; no garnish
  and nothing that is not in the recipe.
- The viewers are German home cooks (mostly women around 56, two-person households). Serve the dish the way it is
  typically served at a German home table today – e.g. a stew in a deep plate, a tray bake on a plate, a cake slice on
  a cake plate – in everyday German tableware: a plain white or simple stoneware deep plate, a simple enamel or
  stainless pot. Ingredients look as they do in German supermarkets. No American or Instagram clichés (no cast-iron
  skillets, slate boards, rustic props, scattered herbs or spices, dark moody styling).
- Framing – the food is the subject: close-up, the dish fills about 80 % of the square frame, camera about 45° above
  and close to the plate or pot, the food surface and textures sharp and clearly readable. Only the vessel's rim and a
  narrow strip of table may show, calm and softly blurred; no window, no room, no extra props, no side dishes. Warm, soft
  natural side light that brings out texture, 85 mm lens, f/5.6, true-to-life colours, professional magazine food photo.
- Avoid words that make images look artificial: perfect, flawless, plastic, 8k, hyperrealistic, CGI, render.
- No text, no logos, no hands, no people.

Format:
{{"visible_ingredients": [{{"name_de": "...", "real_life_appearance": "..."}}],
  "prompt": "English prompt, max. 140 words"}}"""


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
        steps=" ".join(f"{s.get('number')}. {s.get('text', '')}" for s in steps), tip=recipe.get("serving_tip")),
        max_tokens=8000, agent="image_brief")
    path = image_path(run_id, recipe)
    job = flux.submit(brief["prompt"])
    # Save the job before polling so an interrupted generation can be resumed instead of paid for twice
    runs.write_json(path.with_suffix(".pending.json"), {"job": job, "prompt": brief["prompt"], "model": flux.MODEL})
    result = flux.wait(job)
    path.write_bytes(result["bytes"])
    path.with_suffix(".pending.json").unlink(missing_ok=True)
    info = {"slot": slot, "recipe_version": recipe["version"], "file": path.name, "image_model": result["model"],
            "job_id": result["job_id"], "seed": result.get("seed"), "cost_credits": result.get("cost_credits"), "seconds": result["seconds"],
            "prompt": brief["prompt"], "visible_ingredients": brief.get("visible_ingredients"),
            "prompt_model": meta["model"], "created_at": dt.datetime.now().isoformat(timespec="seconds")}
    runs.write_json(path.with_suffix(".json"), info)
    runs.log_event(run_id, "image_ready", f"{slot}: {result['model']} image for v{recipe['version']} ({result['seconds']} s)")
    return info


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(create_image(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
