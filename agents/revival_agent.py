"""Archiv-Revival: the 10 existing archive recipes that best match the rising trends and the current
season/holiday mood, each with a new FLUX image and an A4 card (archive content unchanged).

Run:  python -m agents.revival_agent           -> runs/revival_<time>/
      python -m agents.revival_agent --no-images   (ranking + cards only)
Images are generated for the top `revival_max_images` recipes (config/models.json; currently 2 for testing).
"""
import base64
import datetime as dt
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.image_agent import generate_image, view_from_archive
from ingest.archive import build_index
from rendering.card import card_from_archive, render
from scoring import revival
from scoring.season import season_context
from storage import runs

ROOT = Path(__file__).resolve().parents[1]
IMAGE_WORKERS = 2
MAX_IMAGES = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8")).get("revival_max_images", 10)


def list_revivals() -> list[str]:
    return sorted((p.name for p in runs.RUNS.glob("revival_*") if p.is_dir()), reverse=True)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:30]


def rank_now(day: dt.date | None = None) -> tuple[dict, list[dict]]:
    trends = runs.read_json(runs.TRENDS)
    if not trends:
        raise RuntimeError("runs/trends.json missing – run the trend agent first")
    rising = [c for c in trends["candidates"] if c["scores"]["is_rising"]]
    ctx = season_context(day or dt.date.today(), rising)
    ctx["trends_generated_at"] = trends["generated_at"]
    ctx["rising_trends"] = len(rising)
    return ctx, revival.rank(rising, build_index(), ctx)


def run(images: bool = True, max_images: int | None = None, progress=print) -> str:
    ctx, top = rank_now()
    out = runs.RUNS / f"revival_{dt.datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True)
    items = []
    for n, t in enumerate(top, start=1):
        r = t["recipe"]
        items.append({"rank": n, "recipe_id": r["id"], "title": r["title"], "category": r["category"],
                      "date_imported": r["date_imported"], "labels": r["labels"], "trend": t["trend"],
                      "trend_T": t["trend_T"], "match": t["match"], "trend_relevance": round(t["trend_relevance"], 3),
                      "season_fit": t["season_fit"], "season_labels": t["season_labels"],
                      "completeness": t["completeness"], "score": t["score"],
                      "file_stem": f"{n:02d}_{_slug(r['title'])}"})
    runs.write_json(out / "revival.json", {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "season_context": ctx,
        "method": {"score": "100 × (0.55 × trend relevance + 0.35 × season fit + 0.10 × completeness)",
                   "trend_relevance": "trend score T/100 × match strength (title 1.0, ingredient 0.4)",
                   "season_fit": "best matching current label weight; 0.4 without season label; 0 if only off-season labels",
                   "diversity": f"max. {revival.MAX_PER_TREND} recipes per trend; publication date ignored"},
        "limitations": ["Archive = 5,000-recipe sample of 81,798; category labels exist for 3,354 recipes.",
                        "Matching is lexical (title/ingredient names), not semantic.",
                        "Images are AI illustrations of archive recipes; the export contains no original photos."],
        "items": items})
    progress(f"Top {len(items)} ermittelt – {ctx['reason']}")

    index = {r["id"]: r for r in build_index()}

    def image_for(item):
        path = out / f"{item['file_stem']}.jpg"
        try:
            info = generate_image(view_from_archive(index[item["recipe_id"]]), path, agent="revival_image")
            progress(f"Bild für Platz {item['rank']}: {item['title']}")
            return item["rank"], info, None
        except Exception as exc:  # one failed image must not stop the others
            return item["rank"], None, str(exc)[:300]

    limit = MAX_IMAGES if max_images is None else max_images
    with_image = items[:limit] if images else []
    for item in items[len(with_image):]:
        item["image"], item["image_error"] = None, f"kein Bild (Testlimit: {limit} Bilder)" if images else "Bilder deaktiviert"
    if with_image:
        with ThreadPoolExecutor(max_workers=IMAGE_WORKERS) as ex:
            for rank_no, info, err in ex.map(image_for, with_image):
                item = items[rank_no - 1]
                item["image"] = info["file"] if info else None
                item["image_error"] = err

    for item in items:
        img = out / item["image"] if item.get("image") else None
        src = "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode() if img and img.exists() else None
        (out / f"{item['file_stem']}.html").write_text(render(card_from_archive(index[item["recipe_id"]], src)),
                                                       encoding="utf-8")
        item["card"] = f"{item['file_stem']}.html"
    data = runs.read_json(out / "revival.json")
    data["items"] = items
    runs.write_json(out / "revival.json", data)
    return out.name


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    name = run(images="--no-images" not in sys.argv)
    data = runs.read_json(runs.RUNS / name / "revival.json")
    print(f"\n-> runs/{name}\n{data['season_context']['reason']}\n")
    for i in data["items"]:
        print(f"{i['rank']:2} {i['score']:5} | {i['title'][:46]:46} | {i['trend']} ({i['match']}) | "
              f"{', '.join(i['season_labels'])} | image: {i.get('image') or i.get('image_error') or '-'}")
