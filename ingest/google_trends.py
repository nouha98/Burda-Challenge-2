"""Read the four Google Trends exports (Germany, 18 Oct - 18 Nov 2026)."""
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRENDS_DIR = ROOT / "challenge-2" / "data" / "trends" / "google-trends"
PERIOD = {"start": "2026-10-18", "end": "2026-11-18"}


def parse_percent(text: str) -> float | None:
    """German format: '1.450 %' -> 1450.0, '-7 %' -> -7.0. Thousands dot, decimal comma."""
    if text is None:
        return None
    t = str(text).replace(" ", " ").replace("%", "").strip()
    if not t:
        return None
    if t.lower() in ("breakout", "sprunghaft"):
        return None
    t = t.replace(".", "").replace(",", ".").replace(" ", "")
    return float(t)


def _cohort(path: Path) -> tuple[str, str]:
    name = path.name
    signal = "rising" if "rising" in name else "top"
    kind = "topic" if "_topics_" in name else "query"
    return signal, kind


def load_records() -> list[dict]:
    records = []
    for path in sorted(TRENDS_DIR.glob("*.csv")):
        signal, kind = _cohort(path)
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            next(reader)  # header
            for row_no, row in enumerate(reader, start=2):
                if not row:
                    continue
                records.append({
                    "term": row[0].strip(),
                    "signal_type": signal,
                    "source_kind": kind,
                    "search_interest": int(row[1]),
                    "increase_percent": parse_percent(row[2]),
                    "increase_raw": row[2],
                    "source_file": path.name,
                    "source_row": row_no,
                })
    return records


def normalize(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().lower())
