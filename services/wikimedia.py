"""German Wikipedia pageviews: live API (as the brief prescribes) with the supplied spreadsheet as fallback.

Live and fallback series are never mixed within one article: each result says which source it came from.
"""
import datetime as dt
import json
import urllib.parse
from pathlib import Path

import openpyxl
import requests

from ingest.google_trends import normalize

ROOT = Path(__file__).resolve().parents[1]
FALLBACK_XLSX = ROOT / "challenge-2" / "data" / "trends" / "wikimedia" / "Wikimedia_Pageviews_Fallback_2026-11-18.xlsx"
CACHE_DIR = ROOT / "runs" / "cache" / "wikimedia"
USER_AGENT = "BurdaChallenge2-Hackathon/0.1 (ab@fiveseasons.com) python-requests"
API = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/de.wikipedia.org/"
       "all-access/all-agents/{article}/daily/{start}/{end}")


def live_window(today: dt.date | None = None) -> dict:
    """Two 7-day periods ending yesterday (the latest complete day)."""
    today = today or dt.date.today()
    latest_end = today - dt.timedelta(days=1)
    latest_start = latest_end - dt.timedelta(days=6)
    prev_end = latest_start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=6)
    return {"previous": (prev_start, prev_end), "latest": (latest_start, latest_end)}


def load_fallback() -> tuple[dict, dict]:
    """Return (term -> mapping row, article -> fallback summary)."""
    wb = openpyxl.load_workbook(FALLBACK_XLSX, read_only=True, data_only=True)
    rows = list(wb["Topic summary"].iter_rows(values_only=True))
    header, rows = rows[0], rows[1:]
    idx = {h: i for i, h in enumerate(header)}
    mapping, summary = {}, {}
    for r in rows:
        term = normalize(r[idx["Google term"]])
        article = r[idx["Wikipedia article"]]
        mapping[(term, r[idx["Source kind"]])] = {
            "article": article,
            "mapping_method": r[idx["Mapping method"]],
            "review_required": bool(r[idx["Review required"]]),
            "wikipedia_url": r[idx["Wikipedia URL"]],
        }
        summary[article] = {
            "source": "fallback_spreadsheet",
            "traffic_filter": "all-access; user",
            "previous_period": [str(r[idx["Previous period start"]])[:10], str(r[idx["Previous period end"]])[:10]],
            "latest_period": [str(r[idx["Latest period start"]])[:10], str(r[idx["Latest period end"]])[:10]],
            "previous_7d_views": r[idx["Previous 7d views"]],
            "latest_7d_views": r[idx["Latest 7d views"]],
        }
    return mapping, summary


def fetch_live(article: str, window: dict, session: requests.Session | None = None) -> dict:
    (ps, pe), (ls, le) = window["previous"], window["latest"]
    cache = CACHE_DIR / f"{article.replace('/', '_')}_{ps:%Y%m%d}_{le:%Y%m%d}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    url = API.format(article=urllib.parse.quote(article.replace(" ", "_"), safe=""),
                     start=f"{ps:%Y%m%d}", end=f"{le:%Y%m%d}")
    http = session or requests
    resp = http.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    if resp.status_code == 404:
        items = []  # Wikimedia omits days with zero views; a 404 means no views in the window
    else:
        resp.raise_for_status()
        items = resp.json().get("items", [])
    daily = {i["timestamp"][:8]: i["views"] for i in items}

    def total(start, end):
        days = [(start + dt.timedelta(days=n)).strftime("%Y%m%d") for n in range((end - start).days + 1)]
        return sum(daily.get(d, 0) for d in days)  # omitted days = 0 views (documented API behaviour)

    result = {
        "source": "live_api",
        "traffic_filter": "all-access; all-agents",
        "previous_period": [str(ps), str(pe)],
        "latest_period": [str(ls), str(le)],
        "previous_7d_views": total(ps, pe),
        "latest_7d_views": total(ls, le),
        "api_url": url,
        "retrieved_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
