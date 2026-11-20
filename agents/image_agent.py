"""Image agent: writes a visual brief from the final recipe and generates the card image with FLUX.

Run standalone:  python -m agents.image_agent <run_id> <slot>
"""
import datetime as dt
import json
import sys
from pathlib import Path

from services import flux, vision
from services.gateway import chat_json
from storage import runs

MAX_REGENERATIONS = 1

SYSTEM = """You are a food stylist and photographer briefing an image model for the German food magazine "das schmeckt!".
You know exactly how German and regional ingredients look in real life, raw and after cooking.
The image model does NOT reliably know German or regional food names, so you describe appearance instead of naming.
The magazine's best-selling covers define the photo style – follow this style guide without changing the recipe:

""" + (Path(__file__).resolve().parents[1] / "config" / "image_style.md").read_text(encoding="utf-8") + """

Respond only with a JSON object."""

USER_TEMPLATE = """Brief a photo of this finished recipe as it really looks when cooked at home following these exact steps.

Recipe (German): {title}
Servings: {servings}
Ingredients with recipe quantities and deterministic per-serving amounts where known: {ingredients}
All preparation steps: {steps}
Serving tip: {tip}

Work in this order so photography never changes the meaning of the recipe.

Step 1 – define the finished recipe result.
Read the title, cooking steps and final serving step first. State in one English sentence what complete food the viewer
must see at the end: its main components, their cooked states and whether the image shows one plated serving or a whole
family-style dish. Do not begin with camera settings, table decorations or an attractive generic dish name.

Step 2 – describe the visible ingredients and their proportions.
For every visually distinct ingredient, give its real-life appearance after following the steps: exact colour, surface,
texture, shape and cut size in cm when explicitly stated. Distinguish skin-on wedges from cubes, lengthwise carrot pieces
from slices, and braised leafy greens from roasted crisp leaves. Do not invent piece counts, cut sizes or preparation details.
Use the supplied total and per-serving quantities as authoritative anchors for visual proportions; all division is already
done in code where source quantities and servings are numeric. Give larger recipe quantities more visual presence and keep
accompaniments at their actual portion size. Translate quantities through the method: leafy greens reduce when roasted or
braised, while legumes and grains may swell. Recipe quantities are starting amounts, not cooked weights, and must never appear
as text in the image. Never invent cooked weights or make all components equal merely for symmetry. Ingredients dissolved in
a sauce are texture within that sauce, not extra components. Favour vibrant, appetizing but true-to-life ingredient colours:
rich cooked greens, golden starches and rosy or browned meat where the method creates them. Do not mute or replace a recipe's
colours merely to fit a generic warm palette.

Step 3 – establish the recipe's final plating.
Extract the base, toppings and any separately served accompaniment from the last steps, including vessel and layer order.
For {servings} total servings, show one plated serving only when the recipe plates individual portions. Preserve every
food's cut and cooked state from step 2 while describing exactly where it sits. Styling may create natural asymmetry,
visible browned surfaces and a modest clean plate rim, but may not reverse layers, move sauce onto the food or add garnish.
Every sauce has the consistency and service format produced by the recipe.

Step 4 – write the prompt in this exact information order: finished recipe result → ingredients with proportions and
cooked appearance → final plating → photographic light, composition and setting. The first three parts carry the content;
the photographic part only records them clearly. Start with "Close-up of". Use the branch's cover style only after recipe
fidelity is established: hearty generous food, a suitable cooking or serving vessel from the recipe, clear components, a high
camera angle around 60–75 degrees or top-down when appropriate, bright soft natural daylight, crisp detail and true-to-life
colours. Let the food fill most of the square frame against a calm light or warm-neutral background. Use realistic steam,
sheen, roasted or seared surfaces only where the recipe supports them. Everyday German tableware and restrained props are
secondary to the food. Avoid artificial quality tags such as perfect, hyperrealistic, 8k, CGI or render. Keep unsupported
food and props out by describing only the recipe components and a clean unmarked setting. Returned image text, logos, hands
and people are unwanted.

The returned prompt is a positive full-scene caption for FLUX 3 Klein, which performs its own prompt upsampling. Use a
caption rather than a negative-exclusion list; describe exactly what occupies the finished photograph.

Format:
{{"recipe_result": "one sentence describing the finished dish and servings shown",
  "visible_ingredients": [{{"name_de": "...", "recipe_quantity_and_visual_proportion": "supplied quantity plus cooked-volume explanation", "real_life_appearance": "..."}}],
  "final_plating_from_recipe": "base, toppings and separately served accompaniments with reference to the relevant step",
  "prompt": "English positive full-scene caption ordered as recipe result, ingredients, final plating, then photography; max. 220 words"}}"""


def image_path(run_id: str, recipe: dict):
    return runs.run_dir(run_id) / f"image_{recipe['slot']}_v{recipe['version']}.jpg"


def _format_quantity(value) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _can_divide(servings, quantity) -> bool:
    return (isinstance(servings, (int, float)) and not isinstance(servings, bool) and servings > 0
            and isinstance(quantity, (int, float)) and not isinstance(quantity, bool))


def ingredient_context(recipe: dict) -> str:
    """Preserve display quantities and calculate one-serving anchors in code for visual proportions."""
    servings = recipe.get("servings")
    lines = []
    for ingredient in recipe.get("ingredients") or []:
        name = ingredient.get("name") or "Unbenannte Zutat"
        note = f' ({ingredient["note"]})' if ingredient.get("note") else ""
        quantity = ingredient.get("quantity")
        unit = ingredient.get("unit") or ""
        if quantity is None:
            lines.append(f"{name}{note}: quantity not specified")
            continue
        total = f"{_format_quantity(quantity)} {unit}".strip()
        if _can_divide(servings, quantity):
            portion = f"{_format_quantity(quantity / servings)} {unit}".strip()
            lines.append(f"{name}{note}: {total} total; {portion} per serving")
        else:
            lines.append(f"{name}{note}: {total} total; per-serving quantity unavailable")
    return "; ".join(lines)


def archive_ingredient_context(recipe: dict) -> str:
    """Use the same deterministic scaling for archive XML amounts; ranges and unknown servings stay explicit."""
    servings = (recipe.get("servings") or {}).get("amount")
    lines = []
    for group in recipe.get("ingredient_groups") or []:
        for item in group.get("items") or []:
            label = " ".join(str(value).strip() for value in
                             (item.get("prefix"), item.get("name"), item.get("suffix"))
                             if value is not None and str(value).strip()) or "Unbenannte Zutat"
            amount, maximum, unit = item.get("amount"), item.get("amount_max"), item.get("unit") or ""
            if amount is None:
                lines.append(f"{label}: quantity not specified")
                continue
            amount_text = _format_quantity(amount)
            if maximum is not None:
                amount_text += f"–{_format_quantity(maximum)}"
            total = f"{amount_text} {unit}".strip()
            if maximum is None and _can_divide(servings, amount):
                portion = f"{_format_quantity(amount / servings)} {unit}".strip()
                lines.append(f"{label}: {total} total; {portion} per serving")
            else:
                lines.append(f"{label}: {total} total; per-serving quantity unavailable")
    return "; ".join(lines)


def recipe_instruction_evidence(recipe: dict) -> list[dict]:
    return [{"number": step.get("number"), "instruction": step.get("text") or "",
             "duration_minutes": step.get("duration_minutes"), "temperature": step.get("temperature")}
            for step in recipe.get("steps") or []]


def _step_texts(recipe: dict) -> list[str]:
    return [step.get("text") or "" for step in recipe.get("steps") or []]


def view_from_generated(recipe: dict) -> dict:
    """Common text view of a generated recipe for the image brief."""
    instructions = recipe_instruction_evidence(recipe)
    return {
        "title": recipe.get("title"), "servings": recipe.get("servings"),
        "ingredients": ingredient_context(recipe),
        "steps": " ".join(f"{s.get('number')}. {s.get('text', '')}" for s in recipe.get("steps") or []),
        "tip": recipe.get("serving_tip"),
        "recipe_instructions": instructions,
        "final_plating_instruction": instructions[-1]["instruction"] if instructions else None,
    }


def view_from_archive(recipe: dict) -> dict:
    """Common text view of an archive XML recipe, retaining quantities and complete instructions."""
    steps = _step_texts(recipe)
    instructions = [{"number": number, "instruction": text, "duration_minutes": None, "temperature": None}
                    for number, text in enumerate(steps, start=1)]
    return {
        "title": recipe.get("title"),
        "servings": (recipe.get("servings") or {}).get("amount") or 4,
        "ingredients": archive_ingredient_context(recipe),
        "steps": " ".join(f"{number}. {text}" for number, text in enumerate(steps, start=1)),
        "tip": " ".join(recipe.get("tips") or []) or "–",
        "recipe_instructions": instructions,
        "final_plating_instruction": steps[-1] if steps else None,
    }


CHECK_SYSTEM = """Du bist Bildredakteurin bei "das schmeckt!". Du prüfst, ob ein KI-Rezeptbild zum Rezept passt.
Grundlage ist eine neutrale Bildbeschreibung (die Bildbeschreibung kennt das Rezept nicht). Antworte nur mit JSON."""

CHECK_USER = """Rezept: {title}
Zutaten: {ingredients}
Zubereitung: {steps}

Bildbeschreibung (aus dem Bild erzeugt):
{description}

Prüfe streng, ob das Bild das fertige Gericht so zeigt, wie es nach diesem Rezept aussieht:
- fehlen wichtige sichtbare Komponenten?
- sind Komponenten falsch (andere Zutat, falscher Garzustand, falsche Schnittform, falsche Schichtung/Anordnung)?
- sind Zutaten zu sehen, die nicht im Rezept stehen?
- Bildfehler, Text, Personen?
Kleinigkeiten (Geschirr, Hintergrund) sind kein Grund für "mismatch".

Format: {{"verdict": "match|mismatch", "missing": ["..."], "wrong": ["..."], "extra": ["..."],
          "summary_de": "1 Satz", "fix_instructions_en": "concrete instructions for the next image prompt, or empty"}}"""

CORRECTION = """

The previous image for this recipe was rejected by the photo editor. Fix these points in the new prompt without changing
recipe quantities, cooked states, cuts or final plating:
{fix}"""


def generate_image(view: dict, path, agent: str = "image_brief", corrections: str | None = None) -> dict:
    """Brief (recipe model) -> configured FLUX model -> image plus prompt and recipe provenance."""
    user = USER_TEMPLATE.format(title=view["title"], servings=view["servings"], ingredients=view["ingredients"],
                                steps=view["steps"], tip=view["tip"])
    if corrections:
        user += CORRECTION.format(fix=corrections)
    brief, meta = chat_json("recipe_author", SYSTEM, user, max_tokens=16000, agent=agent)  # 8000 ran out (finish=length)
    if not isinstance(brief.get("prompt"), str) or not brief["prompt"].strip():
        # Valid JSON but without the prompt field: ask once more instead of failing
        brief, meta = chat_json("recipe_author", SYSTEM, user + "\n\nIMPORTANT: the JSON object must contain the field "
                                "\"prompt\" with the complete English image caption.", max_tokens=16000, agent=agent)
        if not isinstance(brief.get("prompt"), str) or not brief["prompt"].strip():
            raise ValueError("image brief without 'prompt' after retry")
    job = flux.submit(brief["prompt"])
    # Save the job before polling so an interrupted generation can be resumed instead of paid for twice.
    runs.write_json(path.with_suffix(".pending.json"), {"job": job, "prompt": brief["prompt"], "model": flux.MODEL})
    result = flux.wait(job)
    path.write_bytes(result["bytes"])
    path.with_suffix(".pending.json").unlink(missing_ok=True)
    info = {"file": path.name, "image_model": result["model"], "job_id": result["job_id"], "seed": result.get("seed"),
            "cost_credits": result.get("cost_credits"), "seconds": result["seconds"], "prompt": brief["prompt"],
            "visible_ingredients": brief.get("visible_ingredients"), "recipe_result": brief.get("recipe_result"),
            "ingredient_context": view["ingredients"], "final_plating_from_recipe": brief.get("final_plating_from_recipe"),
            "recipe_instructions": view.get("recipe_instructions") or [],
            "final_plating_instruction": view.get("final_plating_instruction"), "prompt_model": meta["model"],
            "created_at": dt.datetime.now().isoformat(timespec="seconds")}
    runs.write_json(path.with_suffix(".json"), info)
    return info


def validate_image(path, view: dict) -> dict:
    """Image -> text (vision model, recipe-blind) -> comparison with the recipe (review model)."""
    desc = vision.describe_image(path)
    data, meta = chat_json("reviewer", CHECK_SYSTEM, CHECK_USER.format(
        title=view["title"], ingredients=view["ingredients"], steps=view["steps"][:1500],
        description=desc["description"]), max_tokens=6000, agent="image_check")
    return {"verdict": data.get("verdict", "mismatch"), "missing": data.get("missing", []),
            "wrong": data.get("wrong", []), "extra": data.get("extra", []), "summary_de": data.get("summary_de"),
            "fix_instructions_en": data.get("fix_instructions_en") or "",
            "image_description": desc["description"], "vision_model": desc["model"], "check_model": meta["model"]}


def generate_validated(view: dict, path, max_regenerations: int = MAX_REGENERATIONS, agent: str = "image_brief",
                       progress=print) -> dict:
    """Generate, check against the recipe, regenerate with concrete fixes if it does not match (bounded)."""
    attempts, corrections = [], None
    for attempt in range(max_regenerations + 1):
        info = generate_image(view, path, agent=agent, corrections=corrections)
        try:
            check = validate_image(path, view)
        except Exception as exc:  # validation unavailable: keep the image, say so
            check = {"verdict": "unchecked", "summary_de": f"Bildprüfung nicht verfügbar: {str(exc)[:150]}"}
        attempts.append({"attempt": attempt + 1, "prompt": info["prompt"], "seed": info.get("seed"),
                         "cost_credits": info.get("cost_credits"), "check": check})
        progress(f"Bildprüfung {view['title'][:40]} – Versuch {attempt + 1}: {check['verdict']}")
        if check["verdict"] != "mismatch" or attempt == max_regenerations:
            break
        rejected = path.with_name(f"{path.stem}_rejected{attempt + 1}{path.suffix}")
        path.replace(rejected)
        attempts[-1]["rejected_file"] = rejected.name
        corrections = "; ".join(x for x in [check.get("fix_instructions_en"),
                                            "Missing: " + ", ".join(check.get("missing") or []) if check.get("missing") else "",
                                            "Wrong: " + ", ".join(check.get("wrong") or []) if check.get("wrong") else "",
                                            "Remove: " + ", ".join(check.get("extra") or []) if check.get("extra") else ""] if x)
    final = attempts[-1]["check"]["verdict"]
    info.update({"validation": final, "attempts": attempts,
                 "status": {"match": "ok", "unchecked": "unchecked"}.get(final, "needs_editor_review")})
    runs.write_json(path.with_suffix(".json"), info)
    return info


def create_image(run_id: str, slot: str) -> dict:
    recipe = runs.latest_recipes(run_id)[slot]
    path = image_path(run_id, recipe)
    # Same check as Archiv-Revival: image -> text -> comparison with the recipe, max. one regeneration
    info = generate_validated(view_from_generated(recipe), path, progress=lambda m: None)
    info = {"slot": slot, "recipe_version": recipe["version"], **info}
    runs.write_json(path.with_suffix(".json"), info)
    runs.log_event(run_id, "image_ready", f"{slot}: {info['image_model']} image for v{recipe['version']}, "
                                          f"check {info['validation']} after {len(info['attempts'])} attempt(s)")
    return info


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(create_image(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
