# Burda Challenge 2 – From Food Trends to New "das schmeckt!" Recipes

Multi-agent workflow: food trends → 5 qualified proposals → editor selects 1 → 2 recipes → review loop (max. 2 revisions) → nutrition calculation → HTML recipe cards.

- **Presentation overview (features, workflow, scoring, costs): [PRESENTATION.md](PRESENTATION.md)**
- Build plan and roles: [TASKS.md](TASKS.md)
- Archiv-Revival mode: [REVIVAL-PLAN.md](REVIVAL-PLAN.md)
- Review of the original plan (what changed, what was cut, risks): [PLAN-REVIEW.md](PLAN-REVIEW.md)
- Full design: [Das-schmeckt-workflow-and-implementation-plan.md](Das-schmeckt-workflow-and-implementation-plan.md)
- Challenge materials: [challenge-2/](challenge-2/) (copied from the organisers' repo; folder renamed because `:` is invalid on Windows)

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in the keys (never commit .env)
```

## Run

```
streamlit run app.py
```
Workflow in the app: Trends → Vorschläge & Auswahl → Rezepte → Review → Nährwerte → Rezeptkarten; second mode: Archiv-Revival.
Command-line equivalents: `python -m agents.trend_agent`, `python -m agents.proposal_agent`,
`python -m agents.recipe_agent <run_id>`, `python -m agents.review_agent <run_id>`, `python -m agents.nutrition_agent <run_id>`,
`python -m agents.image_agent <run_id> <A|B>`, `python -m agents.revival_agent [--seed N] [--no-images]`,
`python -m ingest.archive_vectors` (one-off vector index, ~17 min).

## Demo backup (no live APIs needed)

`snapshots/` holds frozen trends, proposals and complete runs. Load one in the app sidebar
("Demo-Backup") or with `python -m storage.snapshot restore demo_2026-11-20_latest` (latest: Grünkohl run with all
image versions + 7 Archiv-Revival results; older: `demo_backup_2026-11-20`).
Current files are backed up to `runs/_backup_<time>/` first. Save a new one with
`python -m storage.snapshot save <name> [run_id]`.

## Layout

```
config/      model IDs and settings, brand rules, image style, unit weights
ingest/      Google Trends, archive XML + topic map, archive vectors, nutrition DB
agents/      trend, brand, proposal, recipe, review, nutrition, image, revival (+ review), trend queries
services/    gateway (LLM), embeddings, vision, FLUX, Brave, Wikimedia
scoring/     trend score, archive match, hybrid search, season, revival, recipe checks, nutrition
rendering/   A4 recipe cards (template, logo, export)
storage/     run folders, snapshots
snapshots/   frozen demo data
tests/       pytest (38 tests)
runs/        generated outputs (git-ignored)
```
