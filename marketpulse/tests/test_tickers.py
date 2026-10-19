from __future__ import annotations

from app.tickers import detect_ticker


def test_detects_a_named_company_in_a_headline():
    assert detect_ticker("Nvidia shares surge after earnings beat", "^IXIC") == "NVDA"


def test_detects_the_longest_matching_alias_first():
    # "meta platforms" and a bare "facebook" could both appear; longest-
    # alias-first ordering means the more specific phrase wins when both
    # happen to be present.
    assert detect_ticker("Meta Platforms reports strong ad revenue", "^IXIC") == "META"
    assert detect_ticker("Facebook parent reports strong ad revenue", "^IXIC") == "META"


def test_falls_back_to_the_index_symbol_when_no_company_is_named():
    assert detect_ticker("Federal Reserve signals a possible rate cut", "^IXIC") == "^IXIC"


def test_word_boundary_prevents_false_positive_substring_matches():
    # "target" the common word must not match Target Corp's "target corp"
    # alias, and must not match on a bare substring overlap either.
    assert detect_ticker("Investors target growth stocks this quarter", "^IXIC") == "^IXIC"


def test_is_case_insensitive():
    assert detect_ticker("TESLA UNVEILS NEW MODEL", "^IXIC") == "TSLA"
