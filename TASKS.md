# Challenge 2 – Single-Laptop Build Plan (5 hours, 3 people)

One laptop does all the building, with Claude Code writing the code. The other two people
work on things that don't need the keyboard: checking outputs, editorial decisions and the demo.
Tasks run **one after another**. Each block ends with something that works and is committed to GitHub.

## Roles

| Role | Who | Job |
|---|---|---|
| **Driver** | _name_ | Runs the laptop: gives Claude Code its instructions, runs the app, commits. |
| **Editor / Reviewer** | _name_ | Plays the das schmeckt! editor. Checks proposals, recipes and nutrition against the brief and the 8 review criteria. Makes the selection in the demo. |
| **Presenter** | _name_ | Owns the demo story and slides. Collects screenshots and limitations. Keeps time and calls the feature freeze. |

## Already done

- [x] Challenge files copied to `challenge-2/` (repo folder names contain `:`, which Windows doesn't allow)
- [x] `.env` with `BFL_API_KEY`, `BRAVE_SEARCH_API_KEY`, `TESSERACT_BASE_URL`, `TESSERACT_API_KEY` (git-ignored)
- [x] BFL key works (credits endpoint returned HTTP 200). **FLUX is out of scope for now (team decision); cards keep an image slot with a placeholder.**
- [x] Brave key works (DE search returned HTTP 200)
- [x] Full recipe archive uploaded: 5,000 XML files, all ingredient IDs resolve via `rezepte_export_topicmap.sql`, 71% have nutrition values, dates 2019–2026
- [x] Gateway: GLM-5.3-Flash, Kimi-K3.1-Pro and DeepSeek-V4.1-Flash all return valid JSON in about 2 s
      → they're reasoning models: set `max_tokens` to at least 2000, otherwise the reasoning uses up the budget

- [x] **Block 1 done:** `python -m agents.trend_agent` → `runs/trends.json` (150 Google records → 94 topics, live Wikimedia for all 94, LLM classification, 70 eligible / 24 excluded, ~80 s)
- [x] **Block 2 done:** `python -m agents.proposal_agent` → `runs/proposals.json` (archive index of 5,000 recipes, Brave context, brand agent, 5 proposals with 2 recipe directions each, ~2 min 15 s)
- [x] **Block 3 done:** `streamlit run app.py` → tabs Trends / Vorschläge & Auswahl / Rezepte; editor selection saved in `runs/<run_id>/`; recipe agent (Kimi, 2 parallel streamed calls, ~100 s) writes recipes A and B
- [x] **Block 4 done:** Review tab → code checks + DeepSeek review (8 criteria + culinary plausibility, 100-point score) → recipe agent revises, max. 2 revisions; minor findings get one polishing revision; changes v1 → v2 shown in the app (~1–3 min)
- [x] **Block 5 done:** Nährwerte tab → ingredients matched to real Swiss database IDs (exact / Swiss name / closest substitute, with confidence), grams via `config/unit_weights.json` rules, per-serving kcal/kJ/fat/carbs/protein computed in code, unresolved items listed (~15–20 s)
- [x] **Block 6 done:** Rezeptkarten tab → A4 cards in the das schmeckt! design (logo, colours, layout from the salmon example), „KI-generierter Rezeptentwurf“, nutrition per serving, image placeholder, multi-page with header/footer/„Seite x von y“; same renderer shows archive XML recipes; print-to-PDF page count verified
- [x] **Backup snapshot:** `snapshots/demo_backup_2026-11-20` (trends, 5 proposals, complete Grünkohl run: v1→v2 corrections, nutrition, 2 cards); load in the sidebar or `python -m storage.snapshot restore demo_backup_2026-11-20`. Note: this run was a test run (editor `cli-test`) – replace it with the editor's real run via `python -m storage.snapshot save <name> <run_id>`

## Timeline

| # | Time | Build step (laptop) | Done when | Editor / Presenter meanwhile |
|---|---|---|---|---|
| 0 | 0:00–0:15 | Install Python, create venv, install `requests pandas openpyxl jinja2 python-dotenv streamlit`; set up the repo skeleton and push | `streamlit hello` runs; skeleton on GitHub | Editor: read brand guide + review criteria. Presenter: demo outline |
| 1 | 0:15–0:55 | **Trends:** parse 4 Google CSVs (`1.450 %` = 1450), drop generic/brand queries (`rezept`, `chefkoch`…), merge top/rising, call **live Wikimedia API** (`all-agents`, User-Agent) with fallback to the spreadsheet, score | `runs/trends.json` with about 15 food candidates, scores and raw numbers | Editor: mark candidates that don't fit the brand |
| 2 | 0:55–1:50 | **Archive index + brand + 5 proposals:** parse the 5,000 archive XMLs into one index (title, ingredients resolved via topic map, units, servings, steps, `DateImported`); for each candidate find similar recipes (title/keyword + ingredient overlap), how often it appeared, and the **most recent comparable recipe**; Brave context for the top 8; GLM scores brand fit (5 dimensions, 0–5 with reasons); GLM writes 5 proposals | `runs/proposals.json` with 5 varied proposals, each with evidence and limitations | Editor: check the 5 proposals are really different (not 5 cookie variants) |
| 3 | 1:50–2:25 | **Streamlit UI + recipe agent:** proposal cards → editor selects 1 → Kimi writes 2 recipes in the agreed JSON (with **subheadings/groups**) | Selection saved; 2 recipe JSONs in `runs/<id>/` | Editor: make the selection; read the drafts |
| 4 | 2:25–2:55 | **Review loop:** code checks (unused ingredients, ingredients missing from the list, split quantities, EL vs TL, quantity present) + DeepSeek review against the 8 criteria → at most 2 revisions | Review history shows at least 1 real correction | Editor: compare the review results with their own reading |
| 5 | 2:55–3:35 | **Nutrition:** match to the Swiss database (exact → alias → candidate list → GLM picks an actual database ID), convert units (density column for ml; table for EL/TL/Stück), calculate per serving incl. kJ, label every assumption | Nutrition table plus assumption list for both recipes | Editor: spot-check 2 ingredients by hand |
| 6 | 3:35–4:15 | **HTML cards:** flowing A4 template using the salmon example's CSS/logo, label „KI-generierter Rezeptentwurf"; image slot shows a placeholder (FLUX left out for now) | 2 HTML cards that open and print | Presenter: screenshots for slides |
| 7 | 4:15–4:30 | **FEATURE FREEZE.** 2 full end-to-end runs; save the best run as a backup demo | Backup run committed | Everyone: dry-run the demo |
| 8 | 4:30–5:00 | Demo prep, README, final push | Repo complete | Presenter leads the rehearsal |

**If running late, cut in this order:** Brave context → archive ingredient overlap (keep title/keyword matching) → UI polish.
Never cut: 5 proposals, human selection, 2 recipes, review loop, nutrition with assumptions, 2 HTML cards.
**If time is left after the freeze:** add FLUX images (key in `.env`, ~30 min: submit → poll → save locally → put in the image slot).

## Shared formats (agree in block 0, then don't change)

- **Proposal:** `id, title_de, trend {google, wikimedia, brave_context}, brand_fit {scores, reasons}, archive {matches, coverage_note}, repetition_risk, content_gap, recipe_directions[2], score_components, limitations`
- **Recipe:** as in the plan §7, plus `group` on ingredients and steps (e.g. „Für den Teig") for review criterion 2
- **Nutrition:** per ingredient `display, grams, db_id, db_name, match_type, conversion, confidence, assumption`; totals and per serving `kcal, kJ, fat, carbs, protein`

## Known limitations to state in the demo

- Archive = 5,000 recipe XMLs (`challenge-2/data/recipe-archive/rezepte_export/`), a **category-stratified sample of 81,798** recipes, so archive claims hold "in this sample" only; ingredient IDs resolve 100% via the topic map, unit IDs 93%. "Most recent comparable recipe" uses `DateImported`, which is the import date into the CMS, not necessarily the print publication date
- Trend data is a fixed snapshot from 18 Oct–18 Nov 2026; the November rise is partly seasonal (Christmas baking)
- No AI-generated images yet (FLUX left out for now) – the brief asks for them on the final cards
- Nutrition values are estimates from the database, not lab measurements; the AI review doesn't replace a test kitchen
