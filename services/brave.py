"""Brave Web Search: recent German context for a trend topic. Results are context, not demand measurements."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
CACHE_DIR = ROOT / "runs" / "cache" / "brave"
URL = "https://api.search.brave.com/res/v1/web/search"


def search(query: str, count: int = 5, freshness: str = "pm") -> dict:
    key = hashlib.sha1(f"{query}|{count}|{freshness}".encode()).hexdigest()[:16]
    cache = CACHE_DIR / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return {"query": query, "results": [], "error": "no BRAVE_SEARCH_API_KEY"}
    try:
        resp = requests.get(URL, params={"q": query, "country": "DE", "search_lang": "de", "count": count,
                                         "freshness": freshness},
                            headers={"Accept": "application/json", "X-Subscription-Token": api_key}, timeout=20)
        resp.raise_for_status()
        results = [{"title": r.get("title"), "url": r.get("url"), "description": r.get("description"),
                    "age": r.get("age") or r.get("page_age")}
                   for r in resp.json().get("web", {}).get("results", [])]
        out = {"query": query, "freshness": freshness, "retrieved_at": dt.datetime.now().isoformat(timespec="seconds"),
               "results": results}
    except requests.RequestException as exc:
        return {"query": query, "results": [], "error": str(exc)[:200]}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
