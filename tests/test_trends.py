from ingest.google_trends import load_records, parse_percent
from scoring.trend_score import percentiles, wiki_label


def test_parse_percent_german_format():
    assert parse_percent("1.450 %") == 1450
    assert parse_percent("-7 %") == -7
    assert parse_percent("0 %") == 0
    assert parse_percent("12,5 %") == 12.5


def test_percentiles_ties_and_single():
    assert percentiles([5]) == [0.5]
    assert percentiles([1, 2, 2, 3]) == [0.0, 0.5, 0.5, 1.0]


def test_wiki_label_band():
    assert wiki_label(100, 104) == "stable"
    assert wiki_label(100, 110) == "growing"
    assert wiki_label(100, 90) == "declining"


def test_all_google_records_loaded():
    records = load_records()
    assert len(records) == 150
    top = next(r for r in records if r["term"] == "engelsaugen rezept")
    assert top["increase_percent"] == 1450 and top["signal_type"] == "rising"
