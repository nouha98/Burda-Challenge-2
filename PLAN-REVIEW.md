# Plan Review – Challenge 2 "das schmeckt!"

Review of [Das-schmeckt-workflow-and-implementation-plan.md](Das-schmeckt-workflow-and-implementation-plan.md) against the challenge materials in `challenge-2/`.
The build plan we actually follow is **[TASKS.md](TASKS.md)**. This file explains why it differs from the original plan.

## Constraints

- **5 hours** to a working prototype, **3 people, 1 laptop**
- Goal: **functional and clearly related to the challenge**. Judging criteria are not a focus for now.
- **FLUX images are left out for now.** The cards keep an image slot with a placeholder; add FLUX only if time is left after the freeze.

## Verdict

The design is sound. It covers all 9 workflow steps in the brief, keeps the editor's choice with a person, and does arithmetic, scoring and checks in code rather than with the LLM.
Its data claims check out against the files (Google CSV format, `1.450 %` = 1450 %, 1,216 nutrition foods, topic-map structure).
**But it is a 6-hour plan for a polished product.** About 40 % is cut or simplified below.

## What still applies from the original plan

- Agent sequence: trend → brand → archive → 5 proposals → human selection → 2 recipes → review loop (max. 2 revisions) → nutrition → HTML
- Model assignment: GLM-5.3-Flash (research, brand, proposals, nutrition matching), Kimi-K3.1-Pro (recipe writing), DeepSeek-V4.1-Flash (review)
- Structured JSON between steps; recipe JSON schema from §7
- Code checks before the LLM review: unused ingredients, ingredients missing from the list, split quantities, EL vs TL, every ingredient has a quantity (except salt/pepper)
- Nutrition calculated in code from the Swiss database, every match and assumption labelled, missing values never treated as zero
- Parsing details in §2 (German number formats, deduplication, don't execute the SQL dump)
- Honest limitations shown in the app and demo

## What changed since the plan was written

| Plan assumption | Now | Effect |
|---|---|---|
| Full recipe archive missing; topic map only | **5,000 recipe XMLs uploaded** (`challenge-2/data/recipe-archive/rezepte_export/`). Ingredient IDs resolve 100 % via the topic map, unit IDs 93 %. Dates 2019–2026, 71 % have nutrition values | Real archive check: similar recipes, how often a topic appeared, most recent similar recipe. No PDF extraction from sample issues needed |
| Archive = complete | The 5,000 are a **category-stratified sample of 81,798** recipes (see `auswahl_manifest.json`) | Claims must say "in this 5,000-recipe sample" |
| XML file for the template missing | The archive XMLs are that format (field guide: `challenge-2/data/recipe-archive/README.txt`) | The card renderer can be tested on archive recipes too |
| FLUX integrated in step 9 | Left out for now | Placeholder image; brief asks for images → listed as a limitation |
| 6-hour build, 3 parallel tracks | 5 hours, 1 laptop, sequential blocks | See TASKS.md |
| Model selection procedure (5 tasks × 3 models) | Smoke test done: all 3 models return valid JSON in about 2 s | Skip the comparison; use the proposed assignment |

## Fixes to the original plan

1. **Subheadings in the recipe format.** Review criterion 2 checks subheadings ("Für den Teig"). The plan's JSON has flat lists. Add `group` to ingredients and steps. The archive XML has the same concept (`CustomRecipeIngredientsHeader`).
2. **Live Wikimedia API.** The brief prescribes the live API (`all-agents`, descriptive User-Agent). Use it, with the fallback spreadsheet only if the call fails. Don't mix the two series.
3. **HTML template approach.** The salmon example positions every text line absolutely. Build a flowing A4 page reusing its CSS, logo, colours and section headings. Aim for 1 page, use simple CSS page breaks for overflow.
4. **Show kJ.** The template displays kJ and the database has it; the plan only lists kcal/F/KH/E.
5. **Use the database's `Dichte` (density) column** for ml → g instead of a hand-made density list.
6. **Filter generic queries** (`rezept`, `rezepte`, `chefkoch`…) before scoring. Many rising queries have search interest `0`, so that score component means little for them.
7. **Set `max_tokens` ≥ 2000** (config uses 4000). All three models are reasoning models and spend tokens before answering.
8. **Follow the archive README's parsing rules** (`challenge-2/data/recipe-archive/README.txt`): keep group order; sort ingredients by `position` only when all positions are numeric; missing values are not zero; don't add different time types into one total; keep `amount_error`-type attributes as quality flags. Keep step order as in the source, even where it looks odd (e.g. `doc7868bmaxa2gmhkh0avd` reads in reverse cooking order). The template requirements forbid changing archive content.

## Cut or simplified

| Original plan | Decision | Why |
|---|---|---|
| Model comparison with rubric | Cut | Smoke test is enough for a prototype |
| SQLite + 9-state state machine | JSON files in `runs/<id>/` | Same result, much less code |
| Score coverage masks ("62/80 observed points") | Show components, "unknown" where missing | Simpler, still honest |
| Calibrated similarity formula and thresholds | Title/keyword + ingredient overlap, top 3 matches | No time to calibrate |
| OCR, embeddings, vision image check | Cut | Not needed with the XML archive and no FLUX |
| Multi-page renderer with repeated headers | One flowing page + CSS page breaks | Biggest time sink in the original plan |
| Brave search | Kept, but first to cut if late | Optional context, not required by the brief |
| Detailed conversion rules | Small unit table (EL/TL/Stück) + density column | Covers typical recipes |

## Risks

| Risk | Mitigation |
|---|---|
| Gateway slow or rate-limited during the demo | Pre-generate and save the 5 proposals; live demo starts at the editor's choice. Save a full backup run at the freeze (block 7) |
| One laptop = single point of failure | Commit after every block; repo can be cloned on another laptop (`.env` must be shared privately) |
| LLM returns invalid JSON | One automatic repair attempt, then fall back to `GLM-5.3` |
| Recipe drafts fail review twice | Stop after 2 revisions and mark "needs editor review", as the brief allows |
| Ingredients that don't match the nutrition database | Show the closest match with a confidence label; block the nutrition label only for major unmatched ingredients |

## Known limitations (state in the demo)

- Archive comparison covers a **5,000-recipe sample** of 81,798; "most recent similar recipe" uses `DateImported` (CMS import date, not necessarily print date)
- Trend data is a fixed snapshot (18 Oct–18 Nov 2026); the November rise is partly seasonal
- No AI-generated images yet (FLUX left out for now)
- Nutrition values are database estimates, not lab measurements; the AI review doesn't replace a test kitchen
