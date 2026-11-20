"""Search descriptions for trends: a bare word ("Spitzbuben") is too thin for semantic search, so the LLM writes
one sentence per trend describing what it is and its typical dish forms. Cached per trends.json version.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.gateway import GatewayError, chat_json

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "runs" / "cache"

SYSTEM = """Du beschreibst Food-Trends für eine semantische Rezeptsuche im Archiv der Zeitschrift "das schmeckt!".
Antworte ausschließlich mit einem JSON-Objekt."""

USER = """Beschreibe jedes Thema in genau einem deutschen Satz (max. 30 Wörter): was es ist (Gericht, Gebäck oder Zutat),
die wichtigsten Zutaten bzw. Merkmale, gängige andere Bezeichnungen und typische Rezeptformen.
Beispiel: "Spitzbuben – Weihnachtsplätzchen aus Mürbeteig, mit roter Marmelade zusammengesetzt und mit Puderzucker
bestäubt, auch Linzer Augen genannt."

Themen:
{topics}

Format: {{"descriptions": {{"t1": "...", "t2": "..."}}}}"""


def describe(candidates: list[dict], trends_generated_at: str) -> dict:
    cache = CACHE_DIR / f"trend_queries_{trends_generated_at.replace(':', '')}.json"
    known = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    todo = [c for c in candidates if c["id"] not in known]
    batches = [todo[i:i + 25] for i in range(0, len(todo), 25)]

    def run(batch):
        topics = "\n".join(f'- {c["id"]}: {c["classification"]["name_de"]} (Suchbegriffe: '
                           + ", ".join(sorted({r["term"] for r in c["records"]})) + ")" for c in batch)
        try:
            data, _ = chat_json("research", SYSTEM, USER.format(topics=topics), max_tokens=8000, agent="trend_queries")
            return data.get("descriptions", {})
        except GatewayError:
            return {}

    with ThreadPoolExecutor(max_workers=2) as ex:
        for part in ex.map(run, batches):
            known.update({k: v for k, v in part.items() if isinstance(v, str)})
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(known, ensure_ascii=False, indent=1), encoding="utf-8")
    # Fallback: name + relevance note when the LLM gave no description
    return {c["id"]: known.get(c["id"]) or f'{c["classification"]["name_de"]}. {c["classification"].get("relevance_de", "")}'
            for c in candidates}
