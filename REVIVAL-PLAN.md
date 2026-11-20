# Archiv-Revival – Plan (branch `feature/archive-trend-revival`)

**Goal:** see what is trending now and bring back the 10 best-fitting existing *das schmeckt!* recipes from the archive
that match those trends and the current season/holiday mood – each with a new FLUX image and an A4 card.
This is a **second mode** next to the brief's workflow (trends → 5 proposals → 2 new recipes), which stays unchanged.

## Decisions (agreed 2026-11-20)

| Topic | Decision |
|---|---|
| Relation to workflow | Second mode (new tab + CLI); new-recipe workflow unchanged |
| Top N | **Top 5** (changed from 10), one list across all trends, **max. 1 recipe per trend** |
| Trends used | Rising food trends (eligible topics with positive Google growth) |
| Season/holiday mood | From today's date + season signals in the trends |
| Season match | Bonus, not a filter (off-season recipes penalised, not excluded) |
| Publication date | Ignored |
| Images | FLUX for the top 5 – **currently limited to 2 for testing** (`config/models.json` → `revival_max_images`, adjustable in the app) |
| Output | Image + A4 card per recipe; archive content shown unchanged |

## Data basis

- **Season/holiday/mood labels:** archive field `CustomRecipeThesaurs` (12,004 refs, all resolve via the topic map),
  e.g. Winter 231, Weihnachten 194, Herbst 151, Advent 35, Silvester/Neujahr 23, Sommer 323, Grillen 57.
- **Christmas flag:** `auswahl_manifest.json` (`weihnachtsrezept`, 500 recipes).
- `Keywords` references do not resolve (0 of 12,508) and are not used.

## Steps

1. **Archive index:** add category labels (`labels`) from `CustomRecipeThesaurs`; drop unresolved keywords.
2. **Season context** (`scoring/season.py`): calendar weights for the date (Nov: Herbst, Winter, Advent, Weihnachten,
   a little Silvester; Dec: Winter, Advent, Weihnachten, Silvester …) plus a boost for Advent/Weihnachten when
   rising trends are Christmas specialities. Off-season labels: Sommer, Sommerparty, Grillen, Grillparty/BBQ, Frühling, Ostern, Eis.
3. **Matching** (`scoring/revival.py`): per rising trend, archive recipes with the trend in the title (strength 1.0)
   or as an ingredient (0.4); relevance = trend score T/100 × strength; a recipe keeps its best trend.
4. **Score** per recipe (0–100): 55 % trend relevance + 35 % season fit + 10 % completeness
   (steps, servings, times, named ingredients). Season fit: best matching seasonal label weight; 0.4 if no season
   label; 0 if only off-season labels.
5. **Top 10** with max. 2 per trend; each with reasons (trend, match type, labels, score breakdown).
6. **Images:** image agent generalised to any recipe (generated or archive), same realism/German/close-up/appeal prompt.
7. **Cards:** archive card renderer accepts an image ("KI-generierte Illustration · kein Originalfoto").
8. **App + CLI:** tab „Archiv-Revival“; `python -m agents.revival_agent`; output in `runs/revival_<time>/`.
9. **Tests:** season context, label parsing, scoring and diversity rule.

## Limitations to state

- Archive = 5,000-recipe sample of 81,798; labels exist only for part of the recipes.
- Matching is lexical (title/ingredient), not semantic.
- Images are AI illustrations of archive recipes, not the original photos (none are in the export).

## Image style (added 2026-11-20)

Images follow `config/image_style.md`, derived from the brand guide's **Top 10 covers** (template) vs. **Low 10 covers**
(avoid): hearty dishes with golden-brown surfaces, shown in the cooking/serving vessel with a serving spoon, high angle
(60–75°) or top-down, food fills the frame, calm light/warm neutral background, warm palette, little green, no strongly
coloured backgrounds. The covers are not passed to the image model (FLUX 3 Image Klein is an editing model; reference
images would be copied incl. logo/headlines) – only the derived rules are used.

## FLUX 3 Image Klein – prompt upsampler

The BFL API runs the prompt upsampler automatically; it cannot be switched off via the API (`prompt_upsampling`,
`upsampling`, `pup` are rejected as extra inputs, HTTP 422). On/off comparison is only possible with the open weights
(`--no-pup` in the reference CLI or Diffusers), which needs a GPU.

## Status

- Ranking, season context, cards, app tab and CLI work; 21 tests pass.
- Test run `runs/revival_20261120_151646`: images for ranks 1–2 (Grünkohl-Gnocchi-Auflauf, Grünkohlsalat), cards for all 10.

## Hybrid search (added 2026-11-20)

- **Embeddings:** `Qwen3-Embedding-8B` via the gateway (4,096 dims). Each archive recipe is embedded once from
  title, category, labels, main ingredients and the start of the method (`ingest/archive_vectors.py`, cached in
  `runs/cache/`, built in checkpoints of 320 recipes so an interrupted build resumes).
- **Queries:** a bare trend word is too thin (test: "Spitzbuben" ranked a beef roast above Linzer cookies), so the
  LLM writes a one-sentence description per trend (`agents/trend_queries.py`, cached), embedded with Qwen3's
  query instruction.
- **Hybrid relevance** (`scoring/hybrid.py`): 0.6 × semantic similarity calibrated per trend
  (median → 0, 99.8th percentile → 1) + 0.4 × lexical (title 1.0, ingredient 0.4); minimum 0.35.
- **Used in:** Archiv-Revival ranking and the proposals' archive check (closest recipes, most recent comparable
  recipe). Keyword match counts stay lexical so repetition statistics remain comparable.
- **Fallback:** without the vector index everything falls back to keyword matching (labelled in the output).
- **Build time:** ~40–50 min once at current gateway speed (slower than the 3 s/32 texts measured in the first test).

## Multi-agent loop (added 2026-11-20)

1. **Retrieval** – per rising trend the best archive recipes (hybrid search + season scoring): top 12 trends × 3 candidates.
2. **Selector agent** (GLM-5.3-Flash, editor role) – picks 5: different trends, max. 2 per archive category, a varied
   mix of dish types. Code validates IDs and rules and fills gaps deterministically.
3. **Review agent** (DeepSeek-V4.1-Flash) – per pick: trend match (strong/weak/none), season ok, keep/replace; set: variety.
   `none` always means replace. Rejected picks are excluded and the selector gets the reasons; `retrieve_again`
   widens the search for a trend (8 candidates). Max. 2 correction rounds, then open points are marked
   „Redaktion prüfen“.
4. **Image check** – FLUX image → vision model (gemma-4-31B-it, ~4 s; Qwen3-VL fallback) describes the image *without*
   seeing the recipe → review model compares the description with ingredients and steps → on mismatch one
   regeneration with concrete fix instructions; rejected images are kept (`*_rejected1.jpg`).
5. Live test (`runs/revival_20261120_162027`): 5 trends / 5 categories, review accepted round 1, both images matched.
   Check against a known faulty Tiramisu image: correctly "mismatch" (ladyfingers on top instead of cocoa-dusted cream).
