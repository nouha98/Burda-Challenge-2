# Archiv-Revival – Plan and current state (branch `feature/archive-trend-revival`)

**Goal:** see what is trending now and bring back existing *das schmeckt!* archive recipes that fit those trends and the
current season/holiday mood – with variety on every run, a new FLUX image and an A4 card each.
This is a **second mode** next to the brief's workflow (trends → 5 proposals → 2 new recipes), which stays unchanged.
Presentation-ready overview of the whole project: [PRESENTATION.md](PRESENTATION.md).

## Current flow

```
Top 3 rising trends (by trend score T)
  → per trend: the 10 most relevant archive recipes (hybrid search + season score) = relevant pool
  → random draw of 3 recipes per trend (uniform, without replacement, recorded seed)
  → review agent: trend match + season per recipe; "replace" → new random draw from the same pool;
    "retrieve_again" → pool widened to 20; max. 2 correction rounds, then open points = "Redaktion prüfen"
  → FLUX image → image check (vision model describes the image without the recipe, review model compares
    with ingredients/steps) → on mismatch 1 regeneration with fix instructions
  → A4 card (archive content unchanged)
```

## Decisions (2026-11-20)

| Topic | Decision |
|---|---|
| Relation to workflow | Second mode (tab „Archiv-Revival“ + CLI); new-recipe workflow unchanged |
| Trends | Top 3 rising trends (`revival_trends`) |
| Recipes | Pool of 10 most relevant per trend (`revival_pool_size`), **random draw of 3** (`revival_per_trend`) |
| Randomness | New seed per run → different recipes for the same trend; `--seed N` / seed field reproduces a run |
| Season/holiday mood | From today's date + season signals in the trends; bonus in the pool score, not a filter |
| Publication date | Ignored |
| Review | Review agent per recipe; a failed review = "unreviewed", never "approved" |
| Images | FLUX 3 Image Klein, **limited to 2 for testing** (`revival_max_images`); image check + max. 1 regeneration |
| Image style | `config/image_style.md` from the brand guide's top vs. low covers |
| Output | Image + A4 card per recipe |

All settings are in `config/models.json`.

## Data basis

- **Season/holiday/mood labels:** archive field `CustomRecipeThesaurs` (12,004 refs, all resolve via the topic map;
  3,354 of 5,000 recipes have labels), e.g. Winter 231, Weihnachten 194, Herbst 151, Advent 35, Silvester/Neujahr 23.
- **Christmas flag:** `auswahl_manifest.json` (`weihnachtsrezept`, 500 recipes). `Keywords` refs do not resolve and are not used.

## Hybrid search

- **Embeddings:** `Qwen3-Embedding-8B` via the gateway (4,096 dims); each recipe embedded once from title, category,
  labels, main ingredients and the start of the method (`ingest/archive_vectors.py`, cached in `runs/cache/`,
  checkpointed every 320 recipes; the build took ~17 min).
- **Queries:** one-sentence trend description written by the LLM (`agents/trend_queries.py`), embedded with Qwen3's
  query instruction (a bare word like "Spitzbuben" ranked a beef roast above Linzer cookies).
- **Relevance** (`scoring/hybrid.py`): 0.6 × semantic + 0.4 × lexical (title 1.0, ingredient 0.4). Semantic score
  calibrated per trend: 99th percentile → 0, best recipe → 1. Keyword hits are always kept; embedding-only hits need
  calibrated ≥ 0.5 and raw similarity ≥ 0.5, max. 10 per trend.
- **Pool score** (`scoring/revival.py`): 100 × (0.55 × T/100 × relevance + 0.35 × season fit + 0.10 × completeness).
- **Also used in** the proposals' archive check (closest recipes, most recent comparable recipe); keyword counts stay lexical.

## FLUX 3 Image Klein – prompt upsampler

The BFL API runs the prompt upsampler automatically; it cannot be switched off via the API (`prompt_upsampling`,
`upsampling`, `pup` are rejected, HTTP 422). An on/off comparison is only possible with the open weights (`--no-pup`),
which needs a GPU.

## Status

- 31 tests pass; app tab and CLI work.
- Live runs: two draws on the same trends gave different recipes; the review loop replaced off-trend picks
  (e.g. "Rosenkohl-Eintopf" drawn for Grünkohl) and marked one remaining recipe „Redaktion prüfen“ after the round limit.
- Image check verified on a known faulty image (Tiramisu with ladyfingers on top → "mismatch" with fix instructions).
- Images for new recipes (`agents/image_agent.create_image`, CLI) do not yet run the image check; only the revival does.

## Limitations

- Archive = 5,000-recipe sample of 81,798; labels exist for 3,354 recipes.
- Relevance ranks the pool; trend fit is judged by the review agent, not proven.
- Images are AI illustrations; the export contains no original photos. The image check works on a text description
  and can miss details.
