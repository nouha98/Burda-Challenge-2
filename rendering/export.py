"""Write the HTML recipe cards for a run (only for the current recipe versions)."""
import base64

from agents.image_agent import image_path
from agents.nutrition_agent import latest_nutrition
from rendering.card import card_from_generated, paginate, render
from storage import runs


def card_path(run_id: str, recipe: dict):
    return runs.run_dir(run_id) / f"card_{recipe['slot']}_v{recipe['version']}.html"


def blockers(run_id: str) -> dict:
    """slot -> list of reasons why a card for the current version should not be exported yet."""
    out = {}
    for slot, r in runs.latest_recipes(run_id).items():
        reasons = []
        if r.get("status") not in ("approved", "needs_editor_review"):
            reasons.append("Review noch nicht durchgeführt")
        n = latest_nutrition(run_id, r)
        if not n:
            reasons.append(f"Nährwerte für Version {r['version']} noch nicht berechnet")
        out[slot] = reasons
    return out


def export_cards(run_id: str) -> dict:
    result = {}
    for slot, r in runs.latest_recipes(run_id).items():
        img = image_path(run_id, r)  # only an image made for this exact recipe version
        src = "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode() if img.exists() else None
        card = card_from_generated(r, latest_nutrition(run_id, r), image_src=src)
        path = card_path(run_id, r)
        path.write_text(render(card), encoding="utf-8")
        result[slot] = {"path": str(path), "pages": len(paginate(card)), "version": r["version"]}
    runs.log_event(run_id, "rendered", "; ".join(f"{s}: v{v['version']}, {v['pages']} Seite(n)" for s, v in result.items()))
    return result
