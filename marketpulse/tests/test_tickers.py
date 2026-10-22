from __future__ import annotations

from app.tickers import detect_ticker, label_for_ticker


def test_detects_a_named_company_in_the_title():
    assert detect_ticker("Nvidia shares surge after earnings beat", "", "^IXIC") == "NVDA"


def test_detects_the_longest_matching_alias_first():
    # "meta platforms" and a bare "facebook" could both appear; longest-
    # alias-first ordering means the more specific phrase wins when both
    # happen to be present.
    assert detect_ticker("Meta Platforms reports strong ad revenue", "", "^IXIC") == "META"
    assert detect_ticker("Facebook parent reports strong ad revenue", "", "^IXIC") == "META"


def test_falls_back_to_the_index_symbol_when_no_company_is_named():
    assert detect_ticker("Federal Reserve signals a possible rate cut", "", "^IXIC") == "^IXIC"


def test_word_boundary_prevents_false_positive_substring_matches():
    # "target" the common word must not match Target Corp's "target corp"
    # alias, and must not match on a bare substring overlap either.
    assert detect_ticker("Investors target growth stocks this quarter", "", "^IXIC") == "^IXIC"


def test_is_case_insensitive():
    assert detect_ticker("TESLA UNVEILS NEW MODEL", "", "^IXIC") == "TSLA"


def test_title_company_wins_over_an_incidentally_mentioned_company_in_the_summary():
    """Real production case: "Why Western Digital (WDC) Stock Is Up Today"
    had a summary mentioning "an analyst upgrade for Intel" as passing
    context, and a title-blind search picked Intel over the article's
    actual subject. The title must win when it names a company."""
    title = "Why Western Digital (WDC) Stock Is Up Today"
    summary = (
        "Shares of leading data storage manufacturer Western Digital (NASDAQ: WDC) jumped 4.8% "
        "in the morning session... helped by an analyst upgrade for Intel."
    )
    assert detect_ticker(title, summary, "^IXIC") == "WDC"


def test_falls_back_to_summary_only_when_the_title_names_no_company():
    title = "Stock rallies after strong quarter"
    summary = "Shares of Apple rose on the news."
    assert detect_ticker(title, summary, "^IXIC") == "AAPL"


def test_label_for_ticker_returns_a_readable_company_name():
    assert label_for_ticker("TSLA") == "Tesla"
    assert label_for_ticker("NVDA") == "Nvidia"


def test_label_for_ticker_falls_back_to_the_bare_symbol_when_uncurated():
    assert label_for_ticker("^IXIC") == "^IXIC"
