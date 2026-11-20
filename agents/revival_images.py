"""Generate FLUX 3 Image Klein images + A4 cards for every recipe of an existing Archiv-Revival result.

  python -m agents.revival_images <revival_id> <out_dir> [--no-check] [--only <file_stem or title>,...]

--no-check skips the image check (vision description + comparison + regeneration): one image per recipe, labelled
"ungeprüft" in the summary. Without the flag every image goes through generate_validated as usual.
"""
import base64
import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.image_agent import generate_image, generate_validated, view_from_archive
from ingest.archive import build_index
from rendering.card import card_from_archive, render
from storage import runs

ROOT = Path(__file__).resolve().parents[1]
WORKERS = 3


def run(revival_id: str, out_dir: Path, check: bool = True, only: set | None = None, progress=print) -> dict:
    data = runs.read_json(runs.RUNS / revival_id / "revival.json")
    index = {r["id"]: r for r in build_index()}
    out_dir.mkdir(parents=True, exist_ok=True)

    def one(item):
        recipe = index[item["recipe_id"]]
        path = out_dir / f"{item['file_stem']}.jpg"
        try:
            if check:
                info = generate_validated(view_from_archive(recipe), path, agent="revival_image", progress=progress)
            else:
                info = generate_image(view_from_archive(recipe), path, agent="revival_image")
                info["status"] = "unchecked"
            src = "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()
            (out_dir / f"{item['file_stem']}.html").write_text(render(card_from_archive(recipe, src)), encoding="utf-8")
            progress(f"fertig: {item['title']}")
            return item, info, None
        except Exception as exc:  # one failed image must not stop the others
            return item, None, str(exc)[:300]

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        todo = [i for i in data["items"] if not only or i["file_stem"] in only or i["title"] in only]
        results = list(ex.map(one, todo))

    previous = {}
    if only and (out_dir / "images.json").exists():  # keep the other recipes' earlier results
        previous = {r["recipe_id"]: r for r in json.loads((out_dir / "images.json").read_text(encoding="utf-8"))["items"]}
    rows, credits = [], 0.0
    done = {item["recipe_id"] for item, _, _ in results}
    for item in data["items"]:
        if item["recipe_id"] not in done and item["recipe_id"] in previous:
            rows.append(previous[item["recipe_id"]])
            credits += previous[item["recipe_id"]].get("cost_credits") or 0
    for item, info, err in results:
        cost = sum(a.get("cost_credits") or 0 for a in info.get("attempts", [])) if info and info.get("attempts") \
            else (info or {}).get("cost_credits") or 0
        credits += cost
        rows.append({"rank": item["rank"], "trend": item["trend"], "title": item["title"], "recipe_id": item["recipe_id"],
                     "image": f"{item['file_stem']}.jpg" if info else None, "card": f"{item['file_stem']}.html" if info else None,
                     "status": info["status"] if info else "failed", "error": err, "cost_credits": cost,
                     "prompt": (info or {}).get("prompt"), "seed": (info or {}).get("seed")})
    summary = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "source_revival": revival_id,
               "source_seed": data.get("seed"), "image_model": "flux-3-image-klein", "image_check": check,
               "total_credits": round(credits, 1), "items": rows}
    (out_dir / "images.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    from rendering.linked_results import link_folder
    link_folder(revival_id, out_dir)  # trend card ↔ recipe cards (reuses the images, no new FLUX calls)
    lines = [f"# Bilder + Karten – Top-3-Trends ({revival_id})", "",
             f"- **Rezepte:** aus `results/{revival_id}` (Seed `{data.get('seed')}`), je Trend 3 zufällig gezogene Archivrezepte",
             f"- **Bildmodell:** FLUX 3 Image Klein (`flux-3-image-klein`), 1 Bild je Rezept",
             f"- **Bildprüfung:** {'an' if check else '**aus** – Bilder sind ungeprüft (auf Wunsch übersprungen)'}",
             f"- **Credits:** {summary['total_credits']}", ""]
    rows.sort(key=lambda r: r["rank"])
    for trend in dict.fromkeys(r["trend"] for r in rows):
        lines += [f"## {trend}", "", "| Rezept | Bild | Karte | Status |", "|---|---|---|---|"]
        for r in [x for x in rows if x["trend"] == trend]:
            lines.append(f"| {r['title']} | " + (f"![{r['title']}]({r['image']})" if r["image"] else "–")
                         + f" | " + (f"[Karte]({r['card']})" if r["card"] else "–")
                         + f" | {r['status']}{(' – ' + r['error']) if r['error'] else ''} |")
        lines.append("")
    lines.insert(5, "- **Trendkarte:** [TREND-KARTE.html](TREND-KARTE.html) – von dort zu jeder Rezeptkarte und zurück")
    lines += ["Die Bilder sind KI-Illustrationen (keine Originalfotos); Rezeptinhalte auf den Karten sind unverändert aus dem Archiv."]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    s = run(args[0], ROOT / args[1], check="--no-check" not in args, only=only)
    print(f"\n{len([i for i in s['items'] if i['image']])}/{len(s['items'])} Bilder, {s['total_credits']} Credits")
    for i in s["items"]:
        print(f"  {i['trend']:9} {i['title'][:44]:44} {i['status']}{' ' + i['error'] if i['error'] else ''}")
