"""Tests for Google News ingestion adapter."""

import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from news.google_news_adapter import (
    fetch_google_news_articles,
    decode_existing_google_urls,
    _decode_google_url,
    GOOGLE_NEWS_SOURCES,
)


@pytest.fixture
def conn():
    """In-memory database with full schema."""
    import db as db_module
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON;")
    c.execute(db_module._SCHEMA_OFFICIALS)
    c.execute(db_module._SCHEMA_KEY_STAFF)
    for stmt in db_module._NEWS_SCHEMAS:
        c.execute(stmt)
    c.commit()
    yield c
    c.close()


def test_google_news_sources_defined():
    """GOOGLE_NEWS_SOURCES should have only 3 entries (sources without native RSS)."""
    assert len(GOOGLE_NEWS_SOURCES) == 3
    assert "pueblo_chieftain" in GOOGLE_NEWS_SOURCES
    assert "gj_sentinel" in GOOGLE_NEWS_SOURCES
    assert "fort_collins_coloradoan" in GOOGLE_NEWS_SOURCES
    # These moved to direct RSS
    assert "co_springs_gazette" not in GOOGLE_NEWS_SOURCES
    assert "steamboat_pilot" not in GOOGLE_NEWS_SOURCES
    assert "summit_daily" not in GOOGLE_NEWS_SOURCES


def _make_rss_entry(title, link, snippet, published="2026-03-06"):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = snippet
    entry.get.side_effect = lambda k, d=None: {"published": published}.get(k, d)
    entry.content = []
    return entry


# ---------------------------------------------------------------------------
# _decode_google_url unit tests
# ---------------------------------------------------------------------------


@patch("news.google_news_adapter.gnewsdecoder")
def test_decode_google_url_success(mock_decoder):
    """gnewsdecoder returns decoded URL on success."""
    mock_decoder.return_value = {
        "status": True,
        "decoded_url": "https://chieftain.com/story/real-article",
    }
    result = _decode_google_url("https://news.google.com/rss/articles/CBMiXX")
    assert result == "https://chieftain.com/story/real-article"
    mock_decoder.assert_called_once_with("https://news.google.com/rss/articles/CBMiXX")


@patch("news.google_news_adapter.gnewsdecoder")
def test_decode_google_url_failure_fallback(mock_decoder):
    """On exception, fall back to the original URL."""
    mock_decoder.side_effect = Exception("network error")
    result = _decode_google_url("https://news.google.com/rss/articles/CBMiXX")
    assert result == "https://news.google.com/rss/articles/CBMiXX"


def test_decode_google_url_non_google_passthrough():
    """Non-Google URLs are returned unchanged without calling gnewsdecoder."""
    url = "https://chieftain.com/story/already-decoded"
    result = _decode_google_url(url)
    assert result == url


# ---------------------------------------------------------------------------
# fetch_google_news_articles tests (updated to mock gnewsdecoder)
# ---------------------------------------------------------------------------


@patch("news.google_news_adapter.gnewsdecoder")
@patch("news.google_news_adapter.feedparser.parse")
def test_fetch_stores_decoded_url(mock_parse, mock_decoder, conn):
    """fetch_google_news_articles should decode Google News URLs before storing."""
    mock_decoder.return_value = {
        "status": True,
        "decoded_url": "https://chieftain.com/story/housing",
    }
    mock_feed = MagicMock()
    mock_feed.entries = [
        _make_rss_entry(
            "Pueblo mayor addresses housing shortage",
            "https://news.google.com/rss/articles/xyz",
            "The mayor of Pueblo announced new housing initiatives...",
        ),
    ]
    mock_parse.return_value = mock_feed

    count = fetch_google_news_articles(conn, "pueblo_chieftain")
    assert count == 1

    row = conn.execute("SELECT url, title, source FROM articles").fetchone()
    assert row[0] == "https://chieftain.com/story/housing"
    assert row[1] == "Pueblo mayor addresses housing shortage"
    assert row[2] == "pueblo_chieftain"


@patch("news.google_news_adapter.gnewsdecoder")
@patch("news.google_news_adapter.feedparser.parse")
def test_fetch_stores_articles(mock_parse, mock_decoder, conn):
    """Basic insertion still works (with decoder mocked)."""
    mock_decoder.return_value = {
        "status": True,
        "decoded_url": "https://chieftain.com/story/decoded",
    }
    mock_feed = MagicMock()
    mock_feed.entries = [
        _make_rss_entry(
            "Pueblo mayor addresses housing shortage",
            "https://news.google.com/rss/articles/xyz",
            "The mayor of Pueblo announced new housing initiatives...",
        ),
    ]
    mock_parse.return_value = mock_feed

    count = fetch_google_news_articles(conn, "pueblo_chieftain")
    assert count == 1

    row = conn.execute("SELECT title, source FROM articles").fetchone()
    assert row[0] == "Pueblo mayor addresses housing shortage"
    assert row[1] == "pueblo_chieftain"


@patch("news.google_news_adapter.gnewsdecoder")
@patch("news.google_news_adapter.feedparser.parse")
def test_deduplication(mock_parse, mock_decoder, conn):
    """Duplicate articles (same decoded URL) are not inserted twice."""
    mock_decoder.return_value = {
        "status": True,
        "decoded_url": "https://chieftain.com/story/dup",
    }
    entry = _make_rss_entry("Same", "https://news.google.com/rss/articles/dup", "Snippet")
    mock_feed = MagicMock()
    mock_feed.entries = [entry]
    mock_parse.return_value = mock_feed

    fetch_google_news_articles(conn, "pueblo_chieftain")
    fetch_google_news_articles(conn, "pueblo_chieftain")

    count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# decode_existing_google_urls migration tests
# ---------------------------------------------------------------------------


@patch("news.google_news_adapter.time.sleep")
@patch("news.google_news_adapter.gnewsdecoder")
def test_decode_existing_google_urls(mock_decoder, mock_sleep, conn):
    """Migration function decodes existing Google News URLs in the DB."""
    # Seed two Google News URLs and one already-decoded URL
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://news.google.com/rss/articles/abc", "Article A", "", "pueblo_chieftain"),
    )
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://news.google.com/rss/articles/def", "Article B", "", "gj_sentinel"),
    )
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://chieftain.com/already-good", "Article C", "", "pueblo_chieftain"),
    )
    conn.commit()

    def decoder_side_effect(url):
        mapping = {
            "https://news.google.com/rss/articles/abc": "https://chieftain.com/story/a",
            "https://news.google.com/rss/articles/def": "https://gjsentinel.com/story/b",
        }
        decoded = mapping.get(url)
        if decoded:
            return {"status": True, "decoded_url": decoded}
        return {"status": False, "message": "not found"}

    mock_decoder.side_effect = decoder_side_effect

    updated = decode_existing_google_urls(conn)
    assert updated == 2

    urls = {r[0] for r in conn.execute("SELECT url FROM articles").fetchall()}
    assert "https://chieftain.com/story/a" in urls
    assert "https://gjsentinel.com/story/b" in urls
    assert "https://chieftain.com/already-good" in urls
    # Original Google News URLs should be gone
    assert "https://news.google.com/rss/articles/abc" not in urls
    assert "https://news.google.com/rss/articles/def" not in urls

    # Verify rate-limiting sleep was called between decodes
    assert mock_sleep.call_count == 2
