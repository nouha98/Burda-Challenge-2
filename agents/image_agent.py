"""Image agent: writes a visual brief from the final recipe and generates the card image with FLUX.

Run standalone:  python -m agents.image_agent <run_id> <slot>
"""
import datetime as dt
import json
import sys
from pathlib import Path

from services import flux
from services.gateway import chat_json
from storage import runs

SYSTEM = """You are a food stylist and photographer briefing an image model for the German food magazine "das schmeckt!".
You know exactly how German and regional ingredients look in real life, raw and after cooking.
The image model does NOT reliably know German or regional food names, so you describe appearance instead of naming.
The magazine's best-selling covers define the photo style – follow this style guide:

""" + (Path(__file__).resolve().parents[1] / "config" / "image_style.md").read_text(encoding="utf-8") + """

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
- Start with the camera view and the vessel (e.g. "High-angle view of … in a white gratin dish"), then each visible
  component using your appearance descriptions – no German food names, no brand names.
- Where texture identifies a food, show it (e.g. one sausage cut open to reveal its interior).
- Style = the top covers in the style guide: hearty and generous, golden-brown roasted/seared/crisp surfaces where the
  steps produce them, visible sauce, every component recognisable, warm palette (golden, brown, cream, red) with green
  only as an accent where the recipe allows. Achieve appeal through styling, not adjectives: freshly served and hot
  (a little steam where it is hot), natural sheen from fat or sauce, the most attractive components on top facing the
  camera, a generous but realistic amount for {servings}. Sauce as thick or thin as the steps make it; no garnish and
  nothing that is not in the recipe.
- Vessel: show the food in the vessel it is cooked or served in, as on the top covers – roasting dish, gratin or baking
  dish, frying pan, enamel or cast-iron pot, or a large white serving bowl/platter – with a serving spoon, fork or cake
  server resting in the food. Everyday German home tableware, ingredients as in German supermarkets. Viewers are
  German home cooks (mostly women around 56, two-person households).
- Framing: high camera angle about 60–75° (or top-down if the dish is flat), the food fills most of the square frame
  and the vessel's edges may be cut off by the frame. Background calm, light or warm neutral (light wood, white, pale
  grey or soft grey-blue); at most a linen napkin edge or a small side bowl partly in frame. Bright soft natural
  daylight, crisp detail, true-to-life colours, professional magazine cover food photo.
- Avoid what the low covers show: large green areas, strongly coloured backgrounds (purple, turquoise, pink, red),
  dark moody scenes, pale unbrowned food, busy props.
- Avoid words that make images look artificial: perfect, flawless, plastic, 8k, hyperrealistic, CGI, render.
- No text, no logos, no hands, no people.

Format:
{{"visible_ingredients": [{{"name_de": "...", "real_life_appearance": "..."}}],
  "prompt": "English prompt, max. 140 words"}}"""


def image_path(run_id: str, recipe: dict):
    return runs.run_dir(run_id) / f"image_{recipe['slot']}_v{recipe['version']}.jpg"


def view_from_generated(recipe: dict) -> dict:
    """Common text view of a generated recipe for the image brief."""
    return {
        "title": recipe.get("title"), "servings": recipe.get("servings"),
        "ingredients": ", ".join(
            f"{i.get('quantity') if i.get('quantity') is not None else ''} {i.get('unit') or ''} {i.get('name')}".strip()
            for i in recipe.get("ingredients") or []),
        "steps": " ".join(f"{s.get('number')}. {s.get('text', '')}" for s in recipe.get("steps") or []),
        "tip": recipe.get("serving_tip"),
    }


def view_from_archive(r: dict) -> dict:
    """Common text view of an archive XML recipe (values as stored)."""
    items = []
    for g in r.get("ingredient_groups") or []:
        for i in g["items"]:
            items.append(" ".join(str(x) for x in [i.get("amount") if i.get("amount") is not None else "", i.get("unit") or "",
                                                   i.get("prefix") or "", i.get("name") or ""] if x != ""))
    return {"title": r.get("title"), "servings": (r.get("servings") or {}).get("amount") or 4,
            "ingredients": ", ".join(items),
            "steps": " ".join(f"{n}. {s['text']}" for n, s in enumerate(r.get("steps") or [], start=1)),
            "tip": " ".join(r.get("tips") or []) or "–"}


def generate_image(view: dict, path, agent: str = "image_brief") -> dict:
    """Brief (recipe model) -> FLUX -> image at `path` plus a .json with prompt and provenance."""
    brief, meta = chat_json("recipe_author", SYSTEM, USER_TEMPLATE.format(
        title=view["title"], servings=view["servings"], ingredients=view["ingredients"], steps=view["steps"],
        tip=view["tip"]), max_tokens=8000, agent=agent)
    job = flux.submit(brief["prompt"])
    # Save the job before polling so an interrupted generation can be resumed instead of paid for twice
    runs.write_json(path.with_suffix(".pending.json"), {"job": job, "prompt": brief["prompt"], "model": flux.MODEL})
    result = flux.wait(job)
    path.write_bytes(result["bytes"])
    path.with_suffix(".pending.json").unlink(missing_ok=True)
    info = {"file": path.name, "image_model": result["model"], "job_id": result["job_id"], "seed": result.get("seed"),
            "cost_credits": result.get("cost_credits"), "seconds": result["seconds"], "prompt": brief["prompt"],
            "visible_ingredients": brief.get("visible_ingredients"), "prompt_model": meta["model"],
            "created_at": dt.datetime.now().isoformat(timespec="seconds")}
    runs.write_json(path.with_suffix(".json"), info)
    return info


def create_image(run_id: str, slot: str) -> dict:
    recipe = runs.latest_recipes(run_id)[slot]
    path = image_path(run_id, recipe)
    info = generate_image(view_from_generated(recipe), path)
    info = {"slot": slot, "recipe_version": recipe["version"], **info}
    runs.write_json(path.with_suffix(".json"), info)
    runs.log_event(run_id, "image_ready", f"{slot}: {info['image_model']} image for v{recipe['version']} ({info['seconds']} s)")
    return info


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(create_image(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
