# Burda Challenge 2 – From Food Trends to New "das schmeckt!" Recipes

Multi-agent workflow: food trends → 5 qualified proposals → editor selects 1 → 2 recipes → review loop (max. 2 revisions) → nutrition calculation → HTML recipe cards.

- Build plan and roles: [TASKS.md](TASKS.md)
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

## Layout

```
config/      model IDs
schemas/     shared JSON formats (proposal, recipe, nutrition)
ingest/      Google Trends, Wikimedia, nutrition CSV, topic map
agents/      trend, brand, proposal, recipe, review, nutrition
services/    gateway, Brave, Wikimedia clients
scoring/     deterministic scores and checks
rendering/   HTML recipe cards
storage/     run files
tests/
runs/        generated outputs (git-ignored)
```
