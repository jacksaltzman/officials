"""Tests for the news pipeline orchestrator."""

import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from news.pipeline import run_news_pipeline


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


@patch("news.pipeline.extract_issues_for_article")
@patch("news.pipeline.fetch_google_news_articles")
@patch("news.pipeline.fetch_rss_articles")
def test_pipeline_calls_all_sources(mock_rss, mock_gnews, mock_extract, conn):
    """Pipeline should call both adapters for all four sources."""
    mock_rss.return_value = 2
    mock_gnews.return_value = 1

    # Insert fake articles so extraction has something to process
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://example.com/1", "Test", "denver_post"),
    )
    conn.commit()

    run_news_pipeline(conn)

    # RSS called for denver_post and durango_herald
    rss_calls = [c[0][1] for c in mock_rss.call_args_list]
    assert "denver_post" in rss_calls
    assert "durango_herald" in rss_calls

    # Google News called for pueblo_chieftain and gj_sentinel
    gnews_calls = [c[0][1] for c in mock_gnews.call_args_list]
    assert "pueblo_chieftain" in gnews_calls
    assert "gj_sentinel" in gnews_calls
