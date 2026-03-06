"""Tests for Google News ingestion adapter."""

import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from news.google_news_adapter import fetch_google_news_articles, GOOGLE_NEWS_SOURCES


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
    assert "pueblo_chieftain" in GOOGLE_NEWS_SOURCES
    assert "gj_sentinel" in GOOGLE_NEWS_SOURCES
    assert "co_springs_gazette" in GOOGLE_NEWS_SOURCES
    assert "fort_collins_coloradoan" in GOOGLE_NEWS_SOURCES
    assert "steamboat_pilot" in GOOGLE_NEWS_SOURCES
    assert "summit_daily" in GOOGLE_NEWS_SOURCES


def _make_rss_entry(title, link, snippet, published="2026-03-06"):
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = snippet
    entry.get.side_effect = lambda k, d=None: {"published": published}.get(k, d)
    entry.content = []
    return entry


@patch("news.google_news_adapter.feedparser.parse")
def test_fetch_stores_articles(mock_parse, conn):
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


@patch("news.google_news_adapter.feedparser.parse")
def test_deduplication(mock_parse, conn):
    entry = _make_rss_entry("Same", "https://news.google.com/rss/articles/dup", "Snippet")
    mock_feed = MagicMock()
    mock_feed.entries = [entry]
    mock_parse.return_value = mock_feed

    fetch_google_news_articles(conn, "pueblo_chieftain")
    fetch_google_news_articles(conn, "pueblo_chieftain")

    count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert count == 1
