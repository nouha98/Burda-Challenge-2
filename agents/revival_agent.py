"""Archiv-Revival: 5 existing archive recipes for the current trends and season, chosen by a multi-agent loop.

  1. Retrieval   – per rising trend the best archive recipes (hybrid search: embeddings + title/ingredient,
                   scored with season fit); top 12 trends × 3 candidates
  2. Selector    – editor agent picks 5: different trends, max. 2 per category, a varied mix (agents/revival_editors)
  3. Review      – review agent checks trend match, season and variety; rejected picks are replaced by the
                   selector (with the reasons), "retrieve_again" widens the search for a trend; max. 2 rounds
  4. Images      – FLUX image → vision model turns it into text → review model compares it with the recipe →
                   one regeneration with concrete fixes if it does not match (agents/image_agent.generate_validated)
  5. Cards       – archive card with image (content unchanged)

Run:  python -m agents.revival_agent           -> runs/revival_<time>/
      python -m agents.revival_agent --no-images
Images only for the first `revival_max_images` picks (config/models.json; currently 2 for testing).
"""
import base64
import datetime as dt
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents import revival_editors
from agents.image_agent import generate_validated, view_from_archive
from agents.trend_queries import describe
from ingest import archive_vectors
from ingest.archive import build_index
from rendering.card import card_from_archive, render
from scoring import revival
from scoring.season import season_context
from services import embeddings
from storage import runs

ROOT = Path(__file__).resolve().parents[1]
IMAGE_WORKERS = 2
MAX_IMAGES = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8")).get("revival_max_images", 10)
MAX_REVIEW_ROUNDS = 2      # correction rounds after the first review
WIDER_PER_TREND = 8        # candidates per trend when the reviewer asks to search again


def list_revivals() -> list[str]:
    return sorted((p.name for p in runs.RUNS.glob("revival_*") if p.is_dir()), reverse=True)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:30]


def prepare(day: dt.date | None = None, semantic: bool = True, build_vectors: bool = True, progress=print) -> dict:
    """Season context, aligned recipes/vectors and per-trend query vectors."""
    trends = runs.read_json(runs.TRENDS)
    if not trends:
        raise RuntimeError("runs/trends.json missing – run the trend agent first")
    rising = [c for c in trends["candidates"] if c["scores"]["is_rising"]]
    ctx = season_context(day or dt.date.today(), rising)
    ctx["trends_generated_at"] = trends["generated_at"]
    ctx["rising_trends"] = len(rising)
    recipes, vectors, query_vecs, descriptions = build_index(), None, None, {}
    if semantic:
        ids, vectors = archive_vectors.load(build=build_vectors, progress=progress)
        if vectors is not None:
            by_id = {r["id"]: r for r in recipes}
            recipes = [by_id[i] for i in ids]  # align recipe order with vector rows
            descriptions = describe(rising, trends["generated_at"])
            qv = embeddings.embed([descriptions[c["id"]] for c in rising], query=True)
            query_vecs = {c["id"]: qv[k] for k, c in enumerate(rising)}
    ctx["retrieval"] = "hybrid (embeddings + title/ingredient)" if query_vecs else "lexical only (title/ingredient)"
    return {"ctx": ctx, "rising": rising, "recipes": recipes, "vectors": vectors, "query_vecs": query_vecs,
            "descriptions": descriptions}


def rank_now(day: dt.date | None = None, semantic: bool = True, progress=print) -> tuple[dict, list[dict]]:
    """Deterministic top 5 (no agents) – used for the quick preview in the app."""
    p = prepare(day, semantic=semantic, build_vectors=False, progress=progress)
    return p["ctx"], revival.rank(p["rising"], p["recipes"], p["ctx"], vectors=p["vectors"], query_vecs=p["query_vecs"])


def select_and_review(p: dict, progress=print) -> tuple[list[dict], list[dict], dict]:
    """Selector ↔ review loop. Returns (final selection, round log, candidate pool)."""
    ctx = p["ctx"]
    pool = revival.candidates_per_trend(p["rising"], p["recipes"], ctx, p["vectors"], p["query_vecs"])
    for tid, entry in pool.items():
        entry["description"] = p["descriptions"].get(tid)
    season = ctx["reason"]
    excluded, feedback, rounds = set(), [], []
    for rnd in range(MAX_REVIEW_ROUNDS + 1):
        progress(f"Runde {rnd + 1}: Auswahl-Agent wählt 5 aus {sum(len(e['candidates']) for e in pool.values())} Kandidaten …")
        sel = revival_editors.select(pool, season, excluded, feedback)
        progress(f"Runde {rnd + 1}: Review-Agent prüft die Auswahl …")
        rev = revival_editors.review(sel["selection"], pool, season)
        rounds.append({"round": rnd + 1, "selection": [{"recipe_id": s["recipe"]["id"], "title": s["recipe"]["title"],
                                                        "trend": s["trend"], "category": s["recipe"]["category"],
                                                        "why_de": s.get("why_de"), "picked_by": s.get("picked_by")}
                                                       for s in sel["selection"]],
                       "variety_de": sel.get("variety_de"), "validation_notes": sel["validation_notes"],
                       "review": rev, "excluded_before": sorted(excluded)})
        if rev["all_ok"] or rnd == MAX_REVIEW_ROUNDS:
            break
        rejected = [v for v in rev["items"] if v.get("verdict") == "replace"]
        for v in rejected:
            excluded.add(v["recipe_id"])
            feedback.append(f'„{v["title"]}" ersetzen: {v.get("reason_de")}')
        if not rev.get("variety_ok", True):
            feedback.append(f'Mischung verbessern: {rev.get("variety_reason_de")}')
        for tid in rev.get("retrieve_again", []):
            wider = revival.candidates_for_trend(pool[tid]["trend"], p["recipes"], ctx, p["vectors"],
                                                 (p["query_vecs"] or {}).get(tid), WIDER_PER_TREND, exclude=excluded)
            pool[tid]["candidates"] = wider
            pool[tid]["widened"] = True
            progress(f"Retrieval: Trend {pool[tid]['trend']['classification']['name_de']} breiter gesucht ({len(wider)} Kandidaten)")
        rounds[-1]["action"] = {"replaced": [v["title"] for v in rejected], "retrieve_again": rev.get("retrieve_again", [])}
    final = sel["selection"]
    verdicts = {v["recipe_id"]: v for v in rev["items"]}
    for s in final:
        v = verdicts.get(s["recipe"]["id"], {})
        s["review"] = v
        s["status"] = "approved" if v.get("verdict", "keep") == "keep" else "needs_editor_review"
    return final, rounds, pool


def run(images: bool = True, max_images: int | None = None, progress=print) -> str:
    p = prepare(progress=progress)
    ctx = p["ctx"]
    final, rounds, pool = select_and_review(p, progress)
    out = runs.RUNS / f"revival_{dt.datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True)
    items = []
    for n, t in enumerate(final, start=1):
        r = t["recipe"]
        items.append({"rank": n, "recipe_id": r["id"], "title": r["title"], "category": r["category"],
                      "date_imported": r["date_imported"], "labels": r["labels"], "trend": t["trend"],
                      "trend_T": t["trend_T"], "match": t["match"], "semantic": t["semantic"],
                      "hybrid_relevance": t["hybrid_relevance"], "trend_relevance": round(t["trend_relevance"], 3),
                      "season_fit": t["season_fit"], "season_labels": t["season_labels"],
                      "completeness": t["completeness"], "score": t["score"], "why_de": t.get("why_de"),
                      "picked_by": t.get("picked_by"), "review": t.get("review"), "status": t.get("status"),
                      "file_stem": f"{n:02d}_{_slug(r['title'])}"})

    def save(extra=None):
        runs.write_json(out / "revival.json", {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "season_context": ctx,
            "method": {"pipeline": "retrieval per trend → selector agent → review agent (max. "
                                   f"{MAX_REVIEW_ROUNDS} correction rounds) → FLUX image → vision check → cards",
                       "retrieval": ctx["retrieval"],
                       "score": "100 × (0.55 × trend relevance + 0.35 × season fit + 0.10 × completeness)",
                       "trend_relevance": "trend score T/100 × hybrid relevance (0.6 × semantic + 0.4 × lexical)",
                       "diversity": f"5 different trends, max. {revival_editors.MAX_PER_CATEGORY} per archive category; "
                                    "publication date ignored"},
            "candidate_pool": {tid: {"trend": e["trend"]["classification"]["name_de"], "description": e.get("description"),
                                     "widened": e.get("widened", False),
                                     "candidates": [{"recipe_id": s["recipe"]["id"], "title": s["recipe"]["title"],
                                                     "category": s["recipe"]["category"], "score": s["score"],
                                                     "match": s["match"], "season_labels": s["season_labels"]}
                                                    for s in e["candidates"]]} for tid, e in pool.items()},
            "rounds": rounds,
            "limitations": ["Archive = 5,000-recipe sample of 81,798; category labels exist for 3,354 recipes.",
                            "Semantic similarity ranks candidates; trend fit is judged by the review agent, not proven.",
                            "Images are AI illustrations of archive recipes; the export contains no original photos.",
                            "The image check compares a text description of the image with the recipe; it can miss details."],
            "items": items, **(extra or {})})
    save()
    progress(f"Auswahl fertig nach {len(rounds)} Runde(n): " + ", ".join(i["title"] for i in items))

    index = {r["id"]: r for r in p["recipes"]}

    def image_for(item):
        path = out / f"{item['file_stem']}.jpg"
        try:
            info = generate_validated(view_from_archive(index[item["recipe_id"]]), path, agent="revival_image",
                                      progress=progress)
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
                if info:
                    item["image_check"] = {"status": info["status"], "attempts": [
                        {"attempt": a["attempt"], "verdict": a["check"]["verdict"], "summary_de": a["check"].get("summary_de"),
                         "missing": a["check"].get("missing"), "wrong": a["check"].get("wrong"),
                         "extra": a["check"].get("extra"), "rejected_file": a.get("rejected_file"),
                         "image_description": a["check"].get("image_description")} for a in info["attempts"]]}

    for item in items:
        img = out / item["image"] if item.get("image") else None
        src = "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode() if img and img.exists() else None
        (out / f"{item['file_stem']}.html").write_text(render(card_from_archive(index[item["recipe_id"]], src)),
                                                       encoding="utf-8")
        item["card"] = f"{item['file_stem']}.html"
    save()
    return out.name


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    name = run(images="--no-images" not in sys.argv)
    data = runs.read_json(runs.RUNS / name / "revival.json")
    print(f"\n-> runs/{name}\n{data['season_context']['reason']}\n")
    for rnd in data["rounds"]:
        print(f"Runde {rnd['round']}: " + " | ".join(s["title"][:30] for s in rnd["selection"]))
        for v in rnd["review"]["items"]:
            print(f"   {v.get('verdict', '?'):7} {v.get('trend_match', '?'):6} {v['title'][:40]} – {v.get('reason_de')}")
        print(f"   Vielfalt ok: {rnd['review'].get('variety_ok')} – {rnd['review'].get('variety_reason_de')}")
    print()
    for i in data["items"]:
        chk = (i.get("image_check") or {}).get("status")
        print(f"{i['rank']} {i['title'][:44]:44} | {i['trend']} | {i['category']} | {i['status']} | "
              f"image: {i.get('image') or i.get('image_error')} ({chk})")
