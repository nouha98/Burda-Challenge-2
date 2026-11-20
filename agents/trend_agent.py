"""Trend agent: Google Trends + Wikimedia pageviews -> scored food-trend candidates.

Run:  python -m agents.trend_agent        -> runs/trends.json

Steps
1. Read the 4 Google exports and group records by their mapped German Wikipedia article.
2. Fetch live pageviews for each article (fallback spreadsheet per article if the live call fails).
3. LLM (GLM-5.3-Flash) classifies each topic and explains its recipe relevance in German.
4. Score eligible topics in code (scoring/trend_score.py).
"""
import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from ingest.google_trends import PERIOD, load_records, normalize
from scoring.trend_score import score_candidates
from services import wikimedia
from services.gateway import GatewayError, chat_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "trends.json"

ELIGIBLE_KINDS = {"dish", "baked_good", "ingredient", "drink"}

SYSTEM = """Du bist der Trend-Agent der Food-Zeitschrift "das schmeckt!" (Burda).
Du klassifizierst Suchtrend-Themen aus Google Trends Deutschland (18.10.–18.11.2026).
Antworte ausschließlich mit einem JSON-Objekt."""

USER_TEMPLATE = """Klassifiziere jedes Thema. Jedes Thema ist ein deutscher Wikipedia-Artikel mit den Google-Suchbegriffen, die darauf abgebildet wurden.

kind – genau einer von:
- "dish": konkretes Gericht (z. B. Linsensuppe, Rinderrouladen)
- "baked_good": konkretes Gebäck / Kuchen / Plätzchen
- "ingredient": konkrete Zutat, aus der Rezepte entstehen (z. B. Grünkohl, Spinat)
- "drink": konkretes Getränk
- "broad_category": zu allgemein für eine Rezeptidee (z. B. Kuchen, Suppe, Fleisch, Dessert, Rezept)
- "method_or_appliance": Zubereitungsart oder Gerät (z. B. Backen, Heißluftfritteuse, Backofen, Thermomix)
- "diet_or_lifestyle": Ernährungsform (z. B. Veganismus)
- "brand_or_media": Marke, Website, Sender, Sendung
- "non_food": kein Essen (z. B. Salzteig zum Basteln)

Außerdem:
- name_de: kurzer deutscher Themenname, wie ihn eine Redaktion schreiben würde
- timing: "current" (passt jetzt: Spätherbst/Advent), "past_event" (Anlass vorbei, z. B. Halloween), "evergreen"
- relevance_de: 1 Satz (max. 25 Wörter), warum das Thema für eine Rezeptentwicklung relevant sein könnte – oder warum nicht. Keine Zahlen erfinden.

Themen:
{topics}

Antwortformat:
{{"topics": [{{"id": "t1", "name_de": "...", "kind": "...", "timing": "...", "relevance_de": "..."}}]}}
Gib für jede id genau einen Eintrag zurück."""


def group_by_article(records: list[dict], mapping: dict) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in records:
        m = mapping.get((normalize(r["term"]), r["source_kind"]))
        if m is None:
            article, m = f"UNMAPPED:{r['term']}", {"article": None, "mapping_method": "unmapped",
                                                    "review_required": True, "wikipedia_url": None}
        else:
            article = m["article"]
        g = groups.setdefault(article, {"wikipedia_article": m["article"], "wikipedia_url": m["wikipedia_url"],
                                        "mapping_methods": set(), "review_required": False, "records": []})
        g["mapping_methods"].add(m["mapping_method"])
        g["review_required"] |= m["review_required"]
        g["records"].append(r)
    out = []
    for n, g in enumerate(groups.values(), start=1):
        g["id"] = f"t{n}"
        g["mapping_methods"] = sorted(g["mapping_methods"])
        out.append(g)
    return out


def attach_pageviews(topics: list[dict], fallback: dict) -> dict:
    window = wikimedia.live_window()
    session = requests.Session()

    def one(t):
        art = t["wikipedia_article"]
        if not art:
            return None
        try:
            return wikimedia.fetch_live(art, window, session)
        except Exception as exc:  # network/API problem -> fallback for this article only
            fb = fallback.get(art)
            return dict(fb, live_error=str(exc)[:200]) if fb else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for t, pv in zip(topics, pool.map(one, topics)):
            t["wikimedia"] = pv
    return {"previous": [str(d) for d in window["previous"]], "latest": [str(d) for d in window["latest"]]}


def classify(topics: list[dict], batch_size: int = 30) -> dict:
    """Return id -> classification. Falls back to 'unclassified' if the gateway fails."""
    def payload(batch):
        lines = []
        for t in batch:
            terms = sorted({r["term"] for r in t["records"]})
            lines.append(f'- {t["id"]}: Artikel "{t["wikipedia_article"]}"; Suchbegriffe: {", ".join(terms)}')
        return USER_TEMPLATE.format(topics="\n".join(lines))

    batches = [topics[i:i + batch_size] for i in range(0, len(topics), batch_size)]

    def run(batch):
        try:
            data, meta = chat_json("research", SYSTEM, payload(batch), max_tokens=12000, agent="trend")
            return {x["id"]: dict(x, model=meta["model"]) for x in data.get("topics", []) if "id" in x}
        except (GatewayError, KeyError, TypeError) as exc:
            print(f"  classification batch failed: {exc}", file=sys.stderr)
            return {}

    result = {}
    with ThreadPoolExecutor(max_workers=2) as pool:  # plan: max 2 concurrent gateway calls
        for part in pool.map(run, batches):
            result.update(part)
    return result


def main() -> None:
    print("Reading Google Trends exports ...")
    records = load_records()
    mapping, fallback = wikimedia.load_fallback()
    topics = group_by_article(records, mapping)
    print(f"  {len(records)} records -> {len(topics)} topics (grouped by Wikipedia article)")

    print("Fetching live Wikimedia pageviews ...")
    window = attach_pageviews(topics, fallback)
    live = sum(1 for t in topics if t["wikimedia"] and t["wikimedia"]["source"] == "live_api")
    print(f"  live: {live}, fallback: {sum(1 for t in topics if t['wikimedia'] and t['wikimedia']['source'] != 'live_api')}")

    print("Classifying topics with the trend agent (LLM) ...")
    labels = classify(topics)
    print(f"  classified {len(labels)}/{len(topics)}")

    eligible, excluded = [], []
    for t in topics:
        lab = labels.get(t["id"])
        t["classification"] = lab or {"kind": "unclassified", "name_de": t["wikipedia_article"],
                                      "timing": "unknown", "relevance_de": "Klassifikation nicht verfügbar."}
        reasons = []
        if t["review_required"]:
            reasons.append("mapping flagged for review in source data")
        if lab and lab.get("kind") not in ELIGIBLE_KINDS:
            reasons.append(f"kind: {lab.get('kind')}")
        if lab and lab.get("timing") == "past_event":
            reasons.append("occasion already over")
        (excluded if reasons else eligible).append(t)
        if reasons:
            t["excluded_because"] = reasons

    score_candidates(eligible)
    eligible.sort(key=lambda t: t["scores"]["T"], reverse=True)

    out = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "google_trends": {"country": "DE", "period": PERIOD, "files": sorted({r["source_file"] for r in records})},
            "wikimedia": {"live_window": window, "project": "de.wikipedia.org",
                          "fallback": wikimedia.FALLBACK_XLSX.name},
        },
        "method": {
            "grouping": "Google records grouped by the mapped German Wikipedia article (fallback spreadsheet mapping)",
            "score": "T = 100*(0.65*G + 0.35*W); G = 0.6*p(growth)+0.4*p(interest) within Google cohort, "
                     "best record per topic; W = 0.6*p(latest 7d views)+0.4*p(clipped log growth, +20 smoothing). "
                     "Relative ranking within this dataset, not absolute demand.",
            "classification_model": next((l["model"] for l in labels.values()), None),
        },
        "limitations": [
            "Google values are normalised (0-100), not search counts; a rising '0' is a rounded small value.",
            "Google period (18 Oct-18 Nov) and Wikipedia window differ.",
            "The November rise is partly seasonal (Advent/Christmas baking), not necessarily a lasting trend.",
            "Several search terms can share one broad Wikipedia article.",
        ],
        "candidates": eligible,
        "excluded": [{k: t[k] for k in ("id", "wikipedia_article", "classification", "excluded_because")}
                     | {"terms": sorted({r["term"] for r in t["records"]})} for t in excluded],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{len(eligible)} eligible candidates, {len(excluded)} excluded -> {OUT.relative_to(ROOT)}\n")
    print(f"{'#':>2}  {'T':>5}  {'Google':>7}  {'Wiki 7d':>8}  {'Wiki Δ':>7}  {'src':4}  Topic")
    for n, t in enumerate(eligible[:20], start=1):
        s, w = t["scores"], t["wikimedia"] or {}
        delta = f"{s['wikipedia_change']:+.0%}" if s["wikipedia_change"] is not None else "n/a"
        src = "live" if w.get("source") == "live_api" else "fb"
        print(f"{n:>2}  {s['T']:>5}  {s['best_google_growth_percent'] or 0:>6.0f}%  {w.get('latest_7d_views', 'n/a'):>8}  "
              f"{delta:>7}  {src:4}  {t['classification']['name_de']}  [{t['classification']['kind']}]"
              + (f"  flags={s['flags']}" if s["flags"] else ""))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
