"""Export an Archiv-Revival result to results/<name>/ for sharing: RESULTS.md summary + images, cards, revival.json.

  python -m storage.results_export [revival_id]     (default: newest revival result)
"""
import shutil
import sys
from pathlib import Path

from storage import runs

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MATCH = {"title": "Titel", "ingredient": "Zutaten", "semantic": "inhaltlich ähnlich (Embedding)"}
STATUS = {"approved": "✅ vom Review bestätigt", "needs_editor_review": "⚠️ Redaktion prüfen"}


def _summary(data: dict, revival_id: str) -> str:
    ctx = data["season_context"]
    lines = [f"# Archiv-Revival – Ergebnis `{revival_id}`", "",
             f"- **Erzeugt:** {data['generated_at']}",
             f"- **Seed:** `{data.get('seed')}` (gleicher Lauf: `python -m agents.revival_agent --seed {data.get('seed')}`)",
             f"- **Trenddaten:** {ctx.get('trends_generated_at')} · **Saison:** {ctx['reason']}",
             f"- **Suche:** {data['method'].get('retrieval')}",
             f"- **Ablauf:** {data['method'].get('pipeline')}",
             "- **Trendkarte (A4, ohne Bild):** [TREND-KARTE.html](TREND-KARTE.html) – Top-3-Trends mit Trend-Score, "
             "Google-Anstieg, Suchinteresse, Wikipedia-Aufrufen und den gezogenen Rezepten", ""]
    rounds = data.get("rounds", [])
    replaced = [r for rnd in rounds for r in (rnd.get("action") or {}).get("replaced", [])]
    lines.append(f"**Review:** {len(rounds)} Runde(n)" + (f"; ersetzt: {'; '.join(replaced)}" if replaced else "; nichts ersetzt") + "\n")
    for tid, pool in data["candidate_pool"].items():
        items = [i for i in data["items"] if i.get("trend_id") == tid]
        lines += [f"## {pool['trend']}", "", f"*{pool.get('description') or ''}*", "",
                  "| # | Rezept | Kategorie | Platz im Pool | Treffer | Saison | Review | Bild |",
                  "|---|---|---|---|---|---|---|---|"]
        for i in items:
            rv = i.get("review") or {}
            chk = (i.get("image_check") or {})
            img = (f"[{i['image']}]({i['image']}) – Prüfung: {chk.get('status', '–')}" if i.get("image")
                   else (i.get("image_error") or "–"))
            lines.append(f"| {i['rank']} | [{i['title']}]({i['card']}) | {i['category']} | {i.get('pool_rank', '–')} von "
                         f"{len(pool['candidates'])} | {MATCH.get(i['match'], i['match'])} | "
                         f"{', '.join(i['season_labels']) or '–'} | {STATUS.get(i.get('status'), i.get('status'))}: "
                         f"{rv.get('trend_match', '?')} – {rv.get('reason_de') or ''} | {img} |")
        lines.append("")
        lines.append("<details><summary>Relevanz-Pool (daraus wurde gezogen)</summary>\n")
        drawn = {i["recipe_id"] for i in items}
        for k, c in enumerate(pool["candidates"], 1):
            lines.append(f"{k}. {'🎲 **' if c['recipe_id'] in drawn else ''}{c['title']}{'**' if c['recipe_id'] in drawn else ''}"
                         f" · {c['category']} · Score {c['score']:.0f}")
        lines.append("\n</details>\n")
    checked = [i for i in data["items"] if i.get("image_check")]
    if checked:
        lines += ["## Bildprüfung", ""]
        for i in checked:
            for a in i["image_check"]["attempts"]:
                lines.append(f"- **{i['title']}**, Versuch {a['attempt']}: {a['verdict']} – {a.get('summary_de') or ''}")
        lines.append("")
    lines += ["## Hinweise", ""] + [f"- {l}" for l in data.get("limitations", [])]
    return "\n".join(lines) + "\n"


def export(revival_id: str | None = None) -> Path:
    revival_id = revival_id or sorted(p.name for p in runs.RUNS.glob("revival_*") if p.is_dir())[-1]
    src = runs.RUNS / revival_id
    data = runs.read_json(src / "revival.json")
    out = RESULTS / revival_id
    # Overwrite files in place; never delete the folder (OneDrive/Explorer can lock folders on Windows)
    out.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.suffix in (".jpg", ".html") or f.name == "revival.json":
            shutil.copy2(f, out / f.name)
    from rendering.trend_card import build as build_trend_card
    (out / "TREND-KARTE.html").write_text(build_trend_card(revival_id), encoding="utf-8")
    (out / "RESULTS.md").write_text(_summary(data, revival_id), encoding="utf-8")
    index = sorted(p.name for p in RESULTS.iterdir() if p.is_dir())
    (RESULTS / "README.md").write_text(
        "# Results\n\nArchiv-Revival runs for the current top trends (newest last). Each folder: `RESULTS.md` "
        "(summary), `TREND-KARTE.html` (A4 trend overview without image), images, A4 recipe cards (`.html`) and "
        "`revival.json` (full trace incl. seed, pools and review rounds).\n\n"
        + "\n".join(f"- [{n}]({n}/RESULTS.md)" for n in index) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(export(sys.argv[1] if len(sys.argv) > 1 else None))
