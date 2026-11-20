"""Link a results folder: trend card ↔ recipe cards.

TREND-KARTE.html gets clickable recipe titles; every recipe card gets a screen-only navigation bar
(← Trendkarte, ‹ previous, next ›, "Rezept n von N · Trend"). Existing images in the folder are reused –
no new FLUX calls.

  python -m rendering.linked_results <revival_id> <folder>
"""
import base64
import sys
from pathlib import Path

from ingest.archive import build_index
from rendering.card import card_from_archive, render
from rendering.trend_card import build as build_trend_card
from storage import runs

ROOT = Path(__file__).resolve().parents[1]
TREND_CARD = "TREND-KARTE.html"


def link_folder(revival_id: str, folder: Path) -> dict:
    data = runs.read_json(runs.RUNS / revival_id / "revival.json")
    index = {r["id"]: r for r in build_index()}
    trend_no = {tid: k for k, tid in enumerate(data["candidate_pool"], start=1)}
    items = sorted(data["items"], key=lambda i: i["rank"])
    links = {}
    for k, item in enumerate(items):
        card_file = f"{item['file_stem']}.html"
        img = folder / f"{item['file_stem']}.jpg"
        src = "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode() if img.exists() else None
        prev_item = items[k - 1] if k > 0 else None
        next_item = items[k + 1] if k + 1 < len(items) else None
        nav = {"back": f"{TREND_CARD}#trend-{trend_no.get(item['trend_id'], 1)}", "index": k + 1, "total": len(items),
               "trend": item["trend"],
               "prev": f"{prev_item['file_stem']}.html" if prev_item else None,
               "prev_title": prev_item["title"] if prev_item else None,
               "next": f"{next_item['file_stem']}.html" if next_item else None,
               "next_title": next_item["title"] if next_item else None}
        (folder / card_file).write_text(render(card_from_archive(index[item["recipe_id"]], src), nav=nav), encoding="utf-8")
        links[item["recipe_id"]] = card_file
    (folder / TREND_CARD).write_text(build_trend_card(revival_id, links=links), encoding="utf-8")
    return links


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    folder = ROOT / sys.argv[2]
    print(f"{len(link_folder(sys.argv[1], folder))} Rezeptkarten verlinkt in {folder}")
