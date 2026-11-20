"""Steps 2-4: brand fit, archive check and five qualified recipe proposals.

Run:  python -m agents.proposal_agent      (needs runs/trends.json from the trend agent)
      -> runs/proposals.json

Flow
1. Shortlist: top trend candidates with positive Google growth.
2. Archive check (code) + Brave context for each shortlisted topic.
3. Brand agent rates brand fit B, feasibility F and archive gap (LLM, anchored 0-5).
4. Proposal score P = 0.35*T + 0.30*B + 0.20*N + 0.15*F, computed in code.
5. Pick 5 varied topics (max. 2 baked goods, max. 1 drink); proposal agent writes each proposal.
"""
import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.brand_agent import assess, compute_scores, describe
from ingest.archive import build_index
from scoring.archive_match import check
from scoring.trend_score import percentiles
from services import brave
from services.gateway import GatewayError, chat_json

ROOT = Path(__file__).resolve().parents[1]
TRENDS = ROOT / "runs" / "trends.json"
OUT = ROOT / "runs" / "proposals.json"
SHORTLIST_SIZE = 12
WEIGHTS = {"T": 0.35, "B": 0.30, "N": 0.20, "F": 0.15}
MAX_PER_KIND = {"baked_good": 2, "drink": 1}

SYSTEM = """Du bist der Proposal-Agent der Zeitschrift "das schmeckt!" (Burda). Du schreibst für die Redaktion
einen qualifizierten Rezeptthemen-Vorschlag auf Deutsch – sachlich, knapp, im Ton einer Redaktionskonferenz.
Verwende nur die gelieferten Daten. Erfinde keine Zahlen, Quellen oder Archivrezepte.
Antworte ausschließlich mit einem JSON-Objekt."""

USER_TEMPLATE = """Schreibe einen Vorschlag für dieses Thema.

{evidence}

Bewertung des Brand-Agenten:
- Content-Lücke: {gap}
- Wiederholungsrisiko: {risk} – {risk_reason}

Archivrezepte, auf die du dich beziehen darfst (nur diese IDs verwenden):
{archive_list}

Format:
{{"title_de": "Arbeitstitel des Themas (max. 8 Wörter)",
  "teaser_de": "1–2 Sätze, warum das Thema jetzt passt",
  "trend_signal_de": "1–2 Sätze, nur mit den gelieferten Zahlen",
  "brand_fit_de": "1–2 Sätze",
  "related_recipes": [{{"id": "...", "why_relevant_de": "kurz"}}],
  "repetition_risk_de": "1 Satz",
  "content_gap_de": "1 Satz",
  "recipe_directions": [
    {{"title_de": "Rezeptidee 1", "idea_de": "1–2 Sätze", "format": "z. B. Pfannengericht"}},
    {{"title_de": "Rezeptidee 2", "idea_de": "1–2 Sätze", "format": "deutlich anderes Format/Zubereitung als Idee 1"}}
  ],
  "open_questions_de": ["..."]}}
Die beiden Rezeptideen müssen sich in Format bzw. Zubereitungsart klar unterscheiden und sich von den Archivrezepten abheben.
Alltagstauglich, keine exotischen Zutaten, keine langen Zutatenlisten."""


def select_diverse(ranked: list[dict], n: int = 5) -> list[dict]:
    chosen, per_kind = [], {}
    for c in ranked:
        kind = c["classification"]["kind"]
        if per_kind.get(kind, 0) >= MAX_PER_KIND.get(kind, n):
            continue
        chosen.append(c)
        per_kind[kind] = per_kind.get(kind, 0) + 1
        if len(chosen) == n:
            break
    return chosen


def write_proposal(c: dict) -> dict:
    a = c["assessment"].get("archive", {})
    archive_list = "\n".join(f'- {r["id"]}: „{r["title"]}" ({r["date_imported"]}, {r["category"]})'
                             for r in c["archive"]["closest_recipes"]) or "- keine"
    user = USER_TEMPLATE.format(evidence=describe(c), gap=a.get("content_gap_de", "–"),
                                risk=a.get("repetition_risk", "unbekannt"), risk_reason=a.get("repetition_reason_de", ""),
                                archive_list=archive_list)
    try:
        data, meta = chat_json("proposals", SYSTEM, user, max_tokens=8000, agent="proposal")
    except GatewayError as exc:
        return {"error": str(exc)[:300]}
    valid = {r["id"] for r in c["archive"]["closest_recipes"]}
    data["related_recipes"] = [r for r in data.get("related_recipes", []) if r.get("id") in valid]
    data["model"] = meta["model"]
    return data


def main() -> None:
    trends = json.loads(TRENDS.read_text(encoding="utf-8"))
    pool = [c for c in trends["candidates"] if c["scores"]["is_rising"]][:SHORTLIST_SIZE]
    print(f"Shortlist: {len(pool)} rising candidates")

    print("Archive check (5,000-recipe sample) + Brave context ...")
    recipes = build_index()
    for c in pool:
        c["archive"] = check(c, recipes)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for c, res in zip(pool, ex.map(lambda c: brave.search(f'{c["classification"]["name_de"]} Rezept'), pool)):
            c["brave"] = res

    # Archive coverage relative to the shortlist: fewer (recent) title matches = more room
    coverage = [c["archive"]["title_matches_recent"] * 2 + c["archive"]["title_matches"] for c in pool]
    for c, p in zip(pool, percentiles(coverage)):
        c["archive"]["coverage_room_0_100"] = round(100 * (1 - p), 1)

    print("Brand agent: brand fit, feasibility, archive gap ...")
    assessments = assess(pool)
    print(f"  assessed {len(assessments)}/{len(pool)}")

    ranked = []
    for c in pool:
        c["assessment"] = assessments.get(c["id"], {})
        sc = compute_scores(c["assessment"]) if c["assessment"] else {"B": None, "F": None, "gap_fit_0_100": None}
        gap = sc["gap_fit_0_100"]
        N = round(0.5 * c["archive"]["coverage_room_0_100"] + 0.5 * gap, 1) if gap is not None else None
        parts = {"T": c["scores"]["T"], "B": sc["B"], "N": N, "F": sc["F"]}
        known = {k: v for k, v in parts.items() if v is not None}
        P = sum(WEIGHTS[k] * v for k, v in known.items())
        max_known = 100 * sum(WEIGHTS[k] for k in known)
        c["proposal_score"] = {"P": round(P, 1), "available_maximum": round(max_known, 1), "components": parts,
                               "weights": WEIGHTS, "missing": [k for k in parts if parts[k] is None],
                               "N_detail": {"coverage_room": c["archive"]["coverage_room_0_100"], "gap_fit": gap}}
        if c["assessment"].get("unsuitable"):
            c["proposal_score"]["excluded"] = c["assessment"].get("unsuitable_reason_de") or "unsuitable"
        else:
            ranked.append(c)
    ranked.sort(key=lambda c: c["proposal_score"]["P"] / max(c["proposal_score"]["available_maximum"], 1), reverse=True)
    chosen = select_diverse(ranked)
    print("Selected: " + ", ".join(c["classification"]["name_de"] for c in chosen))

    print("Proposal agent: writing 5 proposals ...")
    with ThreadPoolExecutor(max_workers=2) as ex:
        texts = list(ex.map(write_proposal, chosen))

    proposals = []
    for n, (c, text) in enumerate(zip(chosen, texts), start=1):
        proposals.append({
            "proposal_id": f"P{n}",
            "topic": c["classification"]["name_de"],
            "kind": c["classification"]["kind"],
            **text,
            "scores": c["proposal_score"],
            "evidence": {
                "google_records": c["records"],
                "wikimedia": c["wikimedia"],
                "trend_scores": c["scores"],
                "trend_relevance_de": c["classification"]["relevance_de"],
                "brave": c["brave"],
                "archive": c["archive"],
                "brand_assessment": c["assessment"],
            },
        })

    out = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "trends_generated_at": trends["generated_at"],
        "method": {
            "proposal_score": "P = 0.35*T + 0.30*B + 0.20*N + 0.15*F (0-100 each). B = 20*weighted 5 brand ratings; "
                              "F = 20*mean of 4 feasibility ratings; N = 0.5*archive coverage room (relative to shortlist) "
                              "+ 0.5*gap fit. Ratings by LLM with anchored 0-5 scale; arithmetic in code.",
            "diversity": "max. 2 baked goods and 1 drink among the 5",
        },
        "limitations": trends["limitations"] + [
            "Archive check covers a 5,000-recipe sample of 81,798; date = CMS import date.",
            "Brand, feasibility and gap ratings are LLM judgements against the brand guide, not reader research.",
            "Brave results are context, not demand measurements.",
        ],
        "proposals": proposals,
        "shortlist": [{"topic": c["classification"]["name_de"], "kind": c["classification"]["kind"],
                       "scores": c["proposal_score"], "selected": c in chosen} for c in pool],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n-> {OUT.relative_to(ROOT)}\n")
    print(f"{'':3} {'P':>5} {'T':>5} {'B':>5} {'N':>5} {'F':>5}  Topic")
    for c in sorted(pool, key=lambda c: c["proposal_score"]["P"], reverse=True):
        p = c["proposal_score"]
        comp = p["components"]
        mark = "*" if c in chosen else ("x" if "excluded" in p else " ")
        fmt = lambda v: f"{v:5.1f}" if v is not None else "  n/a"
        print(f" {mark} {p['P']:5.1f} {fmt(comp['T'])} {fmt(comp['B'])} {fmt(comp['N'])} {fmt(comp['F'])}  "
              f"{c['classification']['name_de']} [{c['classification']['kind']}]")
    print("\n* = selected, x = unsuitable")
    for p in proposals:
        print(f"\n{p['proposal_id']} {p.get('title_de', p.get('error'))}")
        for d in p.get("recipe_directions", []):
            print(f"   - {d.get('title_de')} ({d.get('format')})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
