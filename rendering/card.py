"""Reusable A4 recipe card renderer in the das schmeckt! design (based on the supplied salmon example).

Accepts two inputs:
  card_from_generated(recipe, nutrition)  – our AI recipe drafts
  card_from_archive(archive_recipe)       – recipes from the archive XML export
Content is taken over completely (no shortening, no unit conversion). Pages are split in Python with
conservative text-height estimates, so the output needs no JavaScript; every page has header, recipe
name, footer and "Seite x von y".
"""
import base64
import math
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
ENV = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html", "j2"]))
LOGO = "data:image/png;base64," + base64.b64encode((HERE / "assets" / "logo.png").read_bytes()).decode()
AI_LABEL = "KI-generierter Rezeptentwurf"

# Page geometry in pt (A4 = 595 x 842). Body runs from 86 pt to the footer at 801 pt (minus a safety reserve).
BODY_BOTTOM = 790
CONT_COLUMNS_TOP = 86 + 20 + 19.6          # continuation title + divider
CHARS = {"step": 60, "ing": 23, "intro": 66, "title": 19, "tip": 64, "ghead": 24}  # conservative chars per line


def de_num(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return f"{v:g}".replace(".", ",")


def _lines(text: str, per_line: int) -> int:
    return max(1, math.ceil(len(text or "") / per_line))


# ---------- Adapters ----------

def card_from_generated(recipe: dict, nutrition: dict | None, image_src: str | None = None) -> dict:
    t = recipe.get("times") or {}
    meta = " · ".join(x for x in [
        f"Zubereitung: {t['prep_minutes']} Min." if t.get("prep_minutes") else "",
        f"Garzeit: {t['cook_minutes']} Min." if t.get("cook_minutes") else "",
        f"Gesamt: {t['total_minutes']} Min." if t.get("total_minutes") else "",
        f"{de_num(recipe.get('servings'))} {recipe.get('servings_unit') or 'Portionen'}" if recipe.get("servings") else ""] if x)
    groups, current = [], object()
    for i in recipe.get("ingredients") or []:
        if i.get("group") != current:
            current = i.get("group")
            groups.append({"header": current, "items": []})
        qty = de_num(i.get("quantity")) if isinstance(i.get("quantity"), (int, float)) else ""
        text = " ".join(x for x in [qty, i.get("unit") or "", i.get("name") or ""] if x)
        if i.get("note"):
            text += f" ({i['note']})"
        if i.get("optional"):
            text += " (nach Belieben)"
        groups[-1]["items"].append(text)
    steps = [{"group": s.get("group"), "text": s.get("text") or "", "temp": s.get("temperature")}
             for s in recipe.get("steps") or []]
    if nutrition:
        ps = nutrition["per_serving"]
        rows = [("Energie", f"{ps['kcal']} kcal / {ps['kj']} kJ"), ("Fett", f"{de_num(round(ps['fat_g']))} g"),
                ("Kohlenhydrate", f"{de_num(round(ps['carbs_g']))} g"), ("Eiweiß", f"{de_num(round(ps['protein_g']))} g")]
        note = "Pro Portion, berechnet aus der Schweizer Nährwertdatenbank."
        if not nutrition.get("complete"):
            note += " Unvollständig: nicht alle Zutaten zugeordnet."
        source = "Schätzwerte, keine Labormessung."
    else:
        rows, note, source = [], "Nährwerte noch nicht berechnet.", None
    return {
        "title": recipe.get("title"), "subtitle": recipe.get("subtitle"), "meta": meta,
        "introduction": recipe.get("introduction"), "ai_label": AI_LABEL,
        "servings_label": f"Für {de_num(recipe.get('servings'))} {recipe.get('servings_unit') or 'Portionen'}" if recipe.get("servings") else None,
        "ingredient_groups": groups, "steps": steps, "tip": recipe.get("serving_tip"),
        "nutrition": {"rows": rows, "note": note, "source": source},
        "image_src": image_src, "image_alt": recipe.get("title"),
        "image_placeholder": "Bild folgt – KI-generiertes Rezeptbild noch nicht erstellt",
        "image_caption": "KI-generierte Illustration · kein Originalfoto" if image_src else None,
        "source_label": f"KI-Entwurf · Version {recipe.get('version')}",
    }


def card_from_archive(r: dict, image_src: str | None = None) -> dict:
    """Archive XML record (ingest/archive.py). Values are shown as stored; missing optional fields are omitted."""
    groups = []
    for g in r.get("ingredient_groups") or []:
        items = []
        for i in g["items"]:
            amount = de_num(i["amount"]) if i.get("amount") is not None else ""
            if i.get("amount_max") is not None:
                amount = f"{amount}–{de_num(i['amount_max'])}"
            text = " ".join(x for x in [amount, i.get("unit") or "", i.get("prefix") or "", i.get("name") or "", i.get("suffix") or ""] if x)
            items.append(text)
        groups.append({"header": g.get("header") if g.get("header") not in (None, "Zutaten") else None, "items": items})
    times = " · ".join(f"{t['type']}: {de_num(t['minutes'])} Min." for t in r.get("times") or [] if t.get("minutes"))
    serv = r.get("servings") or {}
    serv_text = f"{de_num(serv.get('amount'))} {serv.get('unit') or ''}".strip() if serv.get("amount") else None
    nut = r.get("nutrition_raw") or {}
    rows = []
    if "kcal" in nut or "kj" in nut:
        rows.append(("Energie", " / ".join(x for x in [f"{de_num(nut['kcal'])} kcal" if "kcal" in nut else "",
                                                        f"{de_num(nut['kj'])} kJ" if "kj" in nut else ""] if x)))
    for key, label in (("fat_g", "Fett"), ("carbs_g", "Kohlenhydrate"), ("protein_g", "Eiweiß")):
        if key in nut:
            rows.append((label, f"{de_num(nut[key])} g"))
    return {
        "title": r.get("title"), "subtitle": r.get("subtitle"),
        "meta": " · ".join(x for x in [times, serv_text] if x), "introduction": None, "ai_label": None,
        "servings_label": f"Für {serv_text}" if serv_text else None,
        "ingredient_groups": groups,
        "steps": [{"group": s.get("header"), "text": s["text"], "temp": None} for s in r.get("steps") or []],
        "tip": " ".join(r.get("tips") or []) or None,
        "nutrition": {"rows": rows, "note": "Angaben aus dem Archiv; Bezugsmenge nicht angegeben." if rows
                      else "Keine Nährwertangaben im Archivdatensatz.", "source": f"Rezeptquelle: XML-Archivexport ({r['id']})."},
        "image_src": image_src, "image_alt": r.get("title"),
        "image_placeholder": "Kein Bild im Archivexport enthalten",
        "image_caption": "KI-generierte Illustration · kein Originalfoto" if image_src else None,
        "source_label": "aus dem Archiv",
    }


# ---------- Pagination ----------

def _split_long(text: str, max_lines: int) -> list[str]:
    """Split an overlong step at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts, cur = [], ""
    for s in sentences:
        if cur and _lines(cur + " " + s, CHARS["step"]) > max_lines:
            parts.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        parts.append(cur)
    return parts


def _hero_height(card: dict) -> float:
    h = _lines(card["title"], CHARS["title"]) * 31
    if card.get("subtitle"):
        h += 4 + _lines(card["subtitle"], CHARS["intro"]) * 14
    if card.get("meta"):
        h += 10 + _lines(card["meta"], 62) * 13
    if card.get("introduction"):
        h += 8 + _lines(card["introduction"], CHARS["intro"]) * 13
    if card.get("ai_label"):
        h += 9 + 16
    figure = 174 + (14 if card.get("image_caption") else 0)
    return max(h, figure) + 19.6  # + divider


def paginate(card: dict) -> list[dict]:
    side_blocks = [{"kind": "ing_title", "h": 29 + (20 if card.get("servings_label") else 0)}]
    for g in card["ingredient_groups"]:
        if g.get("header"):
            side_blocks.append({"kind": "ing_group", "text": g["header"], "h": 16 + _lines(g["header"], CHARS["ghead"]) * 12})
        for item in g["items"]:
            side_blocks.append({"kind": "ing", "text": item, "h": _lines(item, CHARS["ing"]) * 13.5 + 6})
    nrows = len(card["nutrition"]["rows"])
    side_blocks.append({"kind": "nutrition", "h": 20 + 3 * 10.3 + nrows * 12 + (2 * 10 + 6 if card["nutrition"].get("source") else 0) + 8})

    step_cap = BODY_BOTTOM - CONT_COLUMNS_TOP - 29
    main_blocks = [{"kind": "steps_title", "h": 29}]
    current_group, number = object(), 0
    for s in card["steps"]:
        if s.get("group") != current_group:
            current_group = s.get("group")
            if current_group:
                main_blocks.append({"kind": "step_group", "text": current_group, "h": 24})
        text = s["text"]
        max_lines = int(step_cap // 14.2) - 1
        parts = _split_long(text, max_lines) if _lines(text, CHARS["step"]) > max_lines else [text]
        number += 1
        for k, part in enumerate(parts):
            main_blocks.append({"kind": "step", "number": number if k == 0 else f"{number}…", "text": part,
                                "temp": s.get("temp") if k == len(parts) - 1 else None,
                                "h": max(22, _lines(part + (s.get("temp") or ""), CHARS["step"]) * 14.2) + 9})
    if card.get("tip"):
        main_blocks.append({"kind": "tip", "text": card["tip"], "h": 20 + 16 + _lines(card["tip"], CHARS["tip"]) * 13.3 + 4})

    first_top = 86 + _hero_height(card)

    def fill(blocks, title_kind):
        pages, i, page_no = [], 0, 0
        while i < len(blocks):
            top = first_top if page_no == 0 else CONT_COLUMNS_TOP
            pad = 23 if title_kind == "ing_title" else 0  # sidebar padding
            used, page = top + pad, []
            if page_no > 0 and blocks[i]["kind"] != title_kind:
                page.append({"kind": title_kind, "cont": True, "h": 29})
                used += 29
            def fits(k):
                need = blocks[k]["h"]
                if blocks[k]["kind"] in ("ing_group", "step_group") and k + 1 < len(blocks):
                    need += blocks[k + 1]["h"]  # keep a group heading together with its first item
                return used + need <= BODY_BOTTOM

            while i < len(blocks) and (fits(i) or not page or (len(page) == 1 and page[0].get("cont"))):
                page.append(blocks[i])
                used += blocks[i]["h"]
                i += 1
            pages.append(page)
            page_no += 1
        return pages

    side_pages = fill(side_blocks, "ing_title")
    main_pages = fill(main_blocks, "steps_title")
    n = max(len(side_pages), len(main_pages))
    return [{"side": side_pages[k] if k < len(side_pages) else [], "main": main_pages[k] if k < len(main_pages) else []}
            for k in range(n)]


def render(card: dict) -> str:
    return ENV.get_template("card.html.j2").render(card=card, pages=paginate(card), logo=LOGO)
