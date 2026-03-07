"""Tests for RSS feed ingestion adapter."""

import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from news.rss_adapter import fetch_rss_articles, RSS_SOURCES


def _make_entry(title, link, summary="", content=None, published="2026-03-06"):
    """Create a mock feedparser entry."""
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.get.side_effect = lambda k, d=None: {
        "author": "Test Author",
        "published": published,
    }.get(k, d)
    entry.summary = summary
    if content:
        entry.content = [MagicMock(value=content)]
    else:
        entry.content = []
    return entry


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


def test_rss_sources_defined():
    """RSS_SOURCES should have entries for all 8 direct RSS sources."""
    assert len(RSS_SOURCES) == 8
    assert "denver_post" in RSS_SOURCES
    assert "durango_herald" in RSS_SOURCES
    assert "colorado_sun" in RSS_SOURCES
    assert "co_springs_gazette" in RSS_SOURCES
    assert "steamboat_pilot" in RSS_SOURCES
    assert "summit_daily" in RSS_SOURCES
    assert "vail_daily" in RSS_SOURCES
    assert "post_independent" in RSS_SOURCES


@patch("news.rss_adapter.feedparser.parse")
def test_fetch_stores_articles(mock_parse, conn):
    """Articles from RSS should be stored in the articles table."""
    mock_feed = MagicMock()
    mock_feed.entries = [
        _make_entry(
            "Water crisis in Denver",
            "https://denverpost.com/article-1",
            content="<p>Full article about water crisis.</p>",
        ),
    ]
    mock_parse.return_value = mock_feed

    count = fetch_rss_articles(conn, "denver_post")
    assert count == 1

    row = conn.execute("SELECT title, url, source FROM articles").fetchone()
    assert row[0] == "Water crisis in Denver"
    assert row[1] == "https://denverpost.com/article-1"
    assert row[2] == "denver_post"


@patch("news.rss_adapter.feedparser.parse")
def test_deduplication(mock_parse, conn):
    """Same URL should not be inserted twice."""
    entry = _make_entry(
        "Same article",
        "https://denverpost.com/dup",
        content="<p>Content</p>",
    )
    mock_feed = MagicMock()
    mock_feed.entries = [entry]
    mock_parse.return_value = mock_feed

    fetch_rss_articles(conn, "denver_post")
    fetch_rss_articles(conn, "denver_post")

    count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert count == 1
