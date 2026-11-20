"""Review agent (DeepSeek-V4.1-Flash) + correction loop.

Per recipe: code checks -> LLM review -> if material issues remain, the recipe agent revises
(max. 2 revisions) -> review again. Final status: "approved" or "needs_editor_review".

Run standalone:  python -m agents.review_agent <run_id>
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.recipe_agent import revise_recipe
from ingest.archive import build_index
from scoring.recipe_checks import check_archive_duplicate, check_pair, check_recipe
from services.gateway import chat_json
from storage import runs

ROOT = Path(__file__).resolve().parents[1]
BRAND_RULES = (ROOT / "config" / "brand_rules.md").read_text(encoding="utf-8")
MAX_REVISIONS = 2
PASS_SCORE = 85
SCORE_MAX = {"culinary_plausibility": 30, "consistency": 25, "brand_fit": 20, "clarity": 15, "differentiation": 10}

CRITERIA = [
    (1, "Haupttitel", "Ist der Titel passend und beschreibt er das Rezept korrekt?"),
    (2, "Zwischenüberschriften", "Sind Zwischenüberschriften sinnvoll und strukturieren sie das Rezept logisch? (Fehlen ist ok, wenn das Rezept keine braucht.)"),
    (3, "Plausible Mengen", "Sind die Mengen für Gericht und Portionenzahl plausibel?"),
    (4, "Vollständige Mengenangaben", "Hat jede Zutat eine Menge? Ausnahme: Salz und Pfeffer."),
    (5, "Alle Zutaten verwendet", "Werden alle Zutaten der Liste in den Schritten verwendet?"),
    (6, "Konsistente Mengen und Einheiten", "Stimmen Mengen und Einheiten zwischen Liste und Schritten überein, auch bei aufgeteilten Mengen?"),
    (7, "EL und TL korrekt", "Werden Esslöffel und Teelöffel korrekt unterschieden und verrechnet?"),
    (8, "Logische Reihenfolge", "Sind die Zubereitungsschritte logisch angeordnet (z. B. Vorheizen rechtzeitig)?"),
]

SYSTEM = f"""Du bist der Review-Agent der Zeitschrift "das schmeckt!" (Burda) – eine erfahrene Testküchen-Redakteurin.
Du prüfst KI-generierte Rezeptentwürfe streng, konkret und fair. Du schreibst nicht selbst um, sondern benennst
Probleme mit konkreten Korrekturvorschlägen.
{BRAND_RULES}
Antworte ausschließlich mit einem JSON-Objekt."""

USER_TEMPLATE = """Prüfe dieses Rezept (Rezept {slot}, Version {version}).

Rezept (JSON):
{recipe}

Das andere Rezept dieses Laufs heißt „{other_title}“ – beide müssen sich klar unterscheiden.
Ähnliche Archivrezepte (nicht wiederholen): {archive}
Vorgaben der Redaktion: {spec}

Ergebnisse der automatischen Code-Prüfung (bereits sicher festgestellt, bitte übernehmen):
{code_findings}

Prüfkriterien (Checkliste der Redaktion):
{criteria}

Prüfe zusätzlich kulinarische Plausibilität: Garzeiten, Temperaturen, Texturen, Mengenverhältnisse, Ergebnis für die Portionenzahl.

Format:
{{"criteria": [{{"no": 1, "pass": true, "comment_de": "kurz"}}],
  "issues": [{{"severity": "critical|major|minor", "field": "z. B. steps.3 oder ingredients.i2",
               "problem_de": "konkret", "fix_de": "konkreter Korrekturvorschlag", "criterion": 3}}],
  "scores": {{"culinary_plausibility": 0, "consistency": 0, "brand_fit": 0, "clarity": 0, "differentiation": 0}},
  "summary_de": "1–2 Sätze Gesamturteil"}}
Punkte-Maxima: culinary_plausibility 30, consistency 25, brand_fit 20, clarity 15, differentiation 10.
"major" = muss vor Veröffentlichung korrigiert werden; "minor" = sollte verbessert werden. Keine erfundenen Probleme."""


def _body(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("status", "model", "origin", "recipe_id", "proposal_id", "language", "slot")}


def review(run_id: str, recipe: dict, other: dict, sel: dict, archive_titles: set[str]) -> dict:
    code = check_recipe(recipe, sel["spec"]) + check_pair(recipe, other) + check_archive_duplicate(recipe, archive_titles)
    arch = sel["proposal"]["evidence"]["archive"]["closest_recipes"]
    user = USER_TEMPLATE.format(
        slot=recipe["slot"], version=recipe["version"], recipe=json.dumps(_body(recipe), ensure_ascii=False, indent=1),
        other_title=other.get("title"), archive="; ".join(f'„{r["title"]}“' for r in arch) or "keine",
        spec=json.dumps(sel["spec"], ensure_ascii=False),
        code_findings="\n".join(f'- [{i["severity"]}] {i["message_de"]}' for i in code) or "- keine Befunde",
        criteria="\n".join(f"{n}. {name}: {desc}" for n, name, desc in CRITERIA))
    data, meta = chat_json("reviewer", SYSTEM, user, max_tokens=12000, timeout=400, agent=f"review_{recipe['slot']}")
    scores = {k: max(0, min(SCORE_MAX[k], float((data.get("scores") or {}).get(k, 0) or 0))) for k in SCORE_MAX}
    total = round(sum(scores.values()), 1)
    llm_issues = [dict(i, source="review_agent") for i in data.get("issues") or []
                  if i.get("severity") in ("critical", "major", "minor")]
    material = [i for i in code + llm_issues if i["severity"] in ("critical", "major")]
    minor = [i for i in code + llm_issues if i["severity"] == "minor"]
    # Minor findings get one polishing revision on the first draft; after that only material issues block.
    verdict = "pass" if not material and total >= PASS_SCORE and not (minor and recipe["version"] == 1) else "revise"
    result = {
        "slot": recipe["slot"], "version": recipe["version"], "verdict": verdict, "score_total": total,
        "scores": scores, "pass_rule": f"no critical/major issues and score ≥ {PASS_SCORE}/100; "
                                       "minor findings on the first draft trigger one polishing revision",
        "code_findings": code, "llm_issues": llm_issues, "criteria": data.get("criteria") or [],
        "summary_de": data.get("summary_de"), "model": meta["model"],
    }
    runs.write_json(runs.run_dir(run_id) / f"review_{recipe['slot']}_v{recipe['version']}.json", result)
    return result


def revision_report(rv: dict) -> str:
    lines = []
    for i in rv["code_findings"]:
        lines.append(f'- [{i["severity"]}, Code-Prüfung] {i["message_de"]}')
    for i in rv["llm_issues"]:
        lines.append(f'- [{i["severity"]}, {i.get("field", "")}] {i.get("problem_de")} → Korrektur: {i.get("fix_de")}')
    return f'Gesamturteil: {rv.get("summary_de")}\nPunkte: {rv["score_total"]}/100\nBefunde:\n' + "\n".join(lines)


def review_loop(run_id: str, progress=print) -> dict:
    sel = runs.selection(run_id)
    recipes = runs.latest_recipes(run_id)
    archive_titles = {(r["title"] or "").strip().lower() for r in build_index()}
    runs.log_event(run_id, "under_review", "Code checks + review agent")

    def loop(slot):
        recipe = recipes[slot]
        other = recipes["B" if slot == "A" else "A"]
        revisions = 0
        while True:
            progress(f"Rezept {slot} v{recipe['version']}: Review …")
            rv = review(run_id, recipe, other, sel, archive_titles)
            if rv["verdict"] == "pass":
                recipe["status"] = "approved"
                runs.save_recipe(run_id, recipe)
                return slot, recipe, rv, "approved"
            if revisions >= MAX_REVISIONS:
                recipe["status"] = "needs_editor_review"
                runs.save_recipe(run_id, recipe)
                return slot, recipe, rv, "needs_editor_review"
            progress(f"Rezept {slot} v{recipe['version']}: {rv['score_total']} Punkte, Korrektur …")
            recipe = revise_recipe(run_id, recipe, revision_report(rv))
            revisions += 1

    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(loop, ["A", "B"]))
    summary = {slot: {"final_version": r["version"], "status": status, "score": rv["score_total"]}
               for slot, r, rv, status in results}
    overall = "reviewed" if all(s["status"] == "approved" for s in summary.values()) else "needs_editor_review"
    runs.log_event(run_id, overall, "; ".join(f"{k}: v{v['final_version']} {v['status']} ({v['score']} P.)"
                                               for k, v in summary.items()))
    return summary


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(review_loop(sys.argv[1]), ensure_ascii=False, indent=1))
