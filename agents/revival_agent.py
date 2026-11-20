"""Archiv-Revival: existing archive recipes for the current top trends, drawn at random from the most relevant ones.

  1. Trends      – the top 3 rising trends (by trend score T)
  2. Retrieval   – per trend the 10 most relevant archive recipes (hybrid search: embeddings + title/ingredient,
                   scored with season fit) = the relevant pool
  3. Random draw – 3 recipes per trend, uniformly from the pool, with a recorded seed: the same trend gives
                   different recipes on every run; `--seed N` reproduces a run exactly
  4. Review      – review agent checks trend match and season; a rejected recipe is replaced by another random
                   draw from the same trend's pool; "retrieve_again" widens that trend's pool; max. 2 rounds
  5. Images      – FLUX image → vision model turns it into text → review model compares it with the recipe →
                   one regeneration with concrete fixes if it does not match (agents/image_agent.generate_validated)
  6. Cards       – archive card with image (content unchanged)

Run:  python -m agents.revival_agent [--seed N] [--no-images]   -> runs/revival_<time>/
Images only for the first `revival_max_images` recipes (config/models.json; currently 2 for testing).
"""
import base64
import datetime as dt
import json
import random
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
CONFIG = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
IMAGE_WORKERS = 2
MAX_IMAGES = CONFIG.get("revival_max_images", 10)
N_TRENDS = CONFIG.get("revival_trends", 3)
PER_TREND = CONFIG.get("revival_per_trend", 3)
POOL_SIZE = CONFIG.get("revival_pool_size", revival.POOL_SIZE)
MAX_REVIEW_ROUNDS = 2      # correction rounds after the first review
WIDER_POOL = 20            # pool size when the reviewer asks to search a trend again


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


def top_trends(rising: list[dict], n: int = N_TRENDS) -> list[dict]:
    return sorted(rising, key=lambda c: -c["scores"]["T"])[:n]


def rank_now(day: dt.date | None = None, semantic: bool = True, progress=print) -> tuple[dict, list[dict]]:
    """Deterministic list (no agents, no randomness) – used for the quick preview in the app."""
    p = prepare(day, semantic=semantic, build_vectors=False, progress=progress)
    return p["ctx"], revival.rank(p["rising"], p["recipes"], p["ctx"], vectors=p["vectors"], query_vecs=p["query_vecs"])


def sample_and_review(p: dict, seed: int, progress=print) -> tuple[list[dict], list[dict], dict]:
    """Random draw per trend ↔ review loop. Returns (final picks, round log, pools)."""
    ctx, rng = p["ctx"], random.Random(seed)
    pools = {}
    for c in top_trends(p["rising"]):
        qv = (p["query_vecs"] or {}).get(c["id"])
        pools[c["id"]] = {"trend": c, "description": p["descriptions"].get(c["id"]),
                          "candidates": revival.candidates_for_trend(c, p["recipes"], ctx, p["vectors"], qv, POOL_SIZE)}
    picks = {tid: revival.draw(e["candidates"], PER_TREND, rng) for tid, e in pools.items()}
    excluded, rounds = set(), []
    for rnd in range(MAX_REVIEW_ROUNDS + 1):
        selection = [s for tid in pools for s in picks[tid]]
        progress(f"Runde {rnd + 1}: Review-Agent prüft {len(selection)} zufällig gezogene Rezepte …")
        rev = revival_editors.review(selection, pools, ctx["reason"])
        rounds.append({"round": rnd + 1,
                       "selection": [{"recipe_id": s["recipe"]["id"], "title": s["recipe"]["title"], "trend": s["trend"],
                                      "category": s["recipe"]["category"]} for s in selection],
                       "review": rev, "excluded_before": sorted(excluded)})
        if rev["all_ok"] or rnd == MAX_REVIEW_ROUNDS:
            break
        rejected = {v["recipe_id"] for v in rev["items"] if v.get("verdict") == "replace"}
        excluded |= rejected
        for tid in rev.get("retrieve_again", []):
            if tid in pools:
                c = pools[tid]["trend"]
                pools[tid]["candidates"] = revival.candidates_for_trend(
                    c, p["recipes"], ctx, p["vectors"], (p["query_vecs"] or {}).get(c["id"]), WIDER_POOL)
                pools[tid]["widened"] = True
        replaced = []
        for tid in pools:
            keep = [s for s in picks[tid] if s["recipe"]["id"] not in rejected]
            taken = excluded | {s["recipe"]["id"] for s in keep}
            new = revival.draw(pools[tid]["candidates"], PER_TREND - len(keep), rng, exclude=taken)
            replaced += [(old["recipe"]["title"], n["recipe"]["title"])
                         for old, n in zip([s for s in picks[tid] if s["recipe"]["id"] in rejected], new)]
            picks[tid] = keep + new
        rounds[-1]["action"] = {"replaced": [f"{a} → {b}" for a, b in replaced],
                                "retrieve_again": rev.get("retrieve_again", [])}
    verdicts = {v["recipe_id"]: v for v in rev["items"]}
    final = []
    for tid in pools:
        for s in picks[tid]:
            v = verdicts.get(s["recipe"]["id"], {})
            final.append(dict(s, review=v, status="approved" if v.get("verdict", "keep") == "keep" else "needs_editor_review"))
    return final, rounds, pools


def run(images: bool = True, max_images: int | None = None, seed: int | None = None, progress=print) -> str:
    seed = seed if seed is not None else random.SystemRandom().randrange(2 ** 32)
    p = prepare(progress=progress)
    ctx = p["ctx"]
    final, rounds, pools = sample_and_review(p, seed, progress)
    out = runs.RUNS / f"revival_{dt.datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True)
    items = []
    for n, t in enumerate(final, start=1):
        r = t["recipe"]
        items.append({"rank": n, "recipe_id": r["id"], "title": r["title"], "category": r["category"],
                      "date_imported": r["date_imported"], "labels": r["labels"], "trend": t["trend"],
                      "trend_id": t["trend_id"], "trend_T": t["trend_T"], "match": t["match"], "semantic": t["semantic"],
                      "hybrid_relevance": t["hybrid_relevance"], "trend_relevance": round(t["trend_relevance"], 3),
                      "season_fit": t["season_fit"], "season_labels": t["season_labels"],
                      "completeness": t["completeness"], "score": t["score"],
                      "pool_rank": next(k for k, s in enumerate(pools[t["trend_id"]]["candidates"], 1)
                                        if s["recipe"]["id"] == r["id"]),
                      "review": t.get("review"), "status": t.get("status"),
                      "file_stem": f"{n:02d}_{_slug(r['title'])}"})

    def save():
        runs.write_json(out / "revival.json", {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "seed": seed, "season_context": ctx,
            "method": {"pipeline": f"top {N_TRENDS} trends → {POOL_SIZE} most relevant archive recipes per trend → "
                                   f"random draw of {PER_TREND} per trend (seed {seed}) → review agent (max. "
                                   f"{MAX_REVIEW_ROUNDS} correction rounds, replacements drawn from the same pool) → "
                                   "FLUX image → vision check → cards",
                       "retrieval": ctx["retrieval"],
                       "score": "pool ranking: 100 × (0.55 × trend relevance + 0.35 × season fit + 0.10 × completeness)",
                       "trend_relevance": "trend score T/100 × hybrid relevance (0.6 × semantic + 0.4 × lexical)",
                       "randomness": f"uniform draw without replacement from the pool; reproduce with --seed {seed}"},
            "candidate_pool": {tid: {"trend": e["trend"]["classification"]["name_de"], "description": e.get("description"),
                                     "widened": e.get("widened", False),
                                     "candidates": [{"recipe_id": s["recipe"]["id"], "title": s["recipe"]["title"],
                                                     "category": s["recipe"]["category"], "score": s["score"],
                                                     "match": s["match"], "season_labels": s["season_labels"]}
                                                    for s in e["candidates"]]} for tid, e in pools.items()},
            "rounds": rounds,
            "limitations": ["Archive = 5,000-recipe sample of 81,798; category labels exist for 3,354 recipes.",
                            "The pool is ranked by relevance; the draw within it is random by design.",
                            "Images are AI illustrations of archive recipes; the export contains no original photos.",
                            "The image check compares a text description of the image with the recipe; it can miss details."],
            "items": items})
    save()
    progress(f"Gezogen (Seed {seed}) nach {len(rounds)} Runde(n): " + ", ".join(i["title"] for i in items))

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
    args = sys.argv[1:]
    seed_arg = int(args[args.index("--seed") + 1]) if "--seed" in args else None
    name = run(images="--no-images" not in args, seed=seed_arg)
    data = runs.read_json(runs.RUNS / name / "revival.json")
    print(f"\n-> runs/{name}   Seed: {data['seed']}\n{data['season_context']['reason']}\n")
    for rnd in data["rounds"]:
        bad = [v for v in rnd["review"]["items"] if v.get("verdict") != "keep"]
        if rnd.get("action"):
            print(f"Runde {rnd['round']}: {len(rnd['selection'])} geprüft, {len(bad)} ersetzt: "
                  + "; ".join(rnd["action"]["replaced"]))
        else:
            print(f"Runde {rnd['round']}: {len(rnd['selection'])} geprüft, "
                  + (f"{len(bad)} offen (Rundenlimit erreicht → Redaktion prüfen)" if bad else "alle bestätigt"))
    for tid, pool in data["candidate_pool"].items():
        print(f"\n{pool['trend']} – Pool {len(pool['candidates'])}:")
        for i in [x for x in data["items"] if x["trend_id"] == tid]:
            chk = (i.get("image_check") or {}).get("status")
            print(f"   #{i['pool_rank']:2} im Pool | {i['title'][:46]:46} | {i['category']} | {i['status']}"
                  + (f" | Bild: {chk}" if chk else ""))
