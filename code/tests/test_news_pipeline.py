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


@patch("news.pipeline.find_duplicates")
@patch("news.pipeline.scrape_missing_bodies")
@patch("news.pipeline.extract_issues_for_article")
@patch("news.pipeline.fetch_google_news_articles")
@patch("news.pipeline.fetch_rss_articles")
def test_pipeline_calls_all_sources(mock_rss, mock_gnews, mock_extract, mock_scrape, mock_dedup, conn):
    """Pipeline should call both adapters, scraper, and extractor."""
    mock_rss.return_value = 2
    mock_gnews.return_value = 1
    mock_scrape.return_value = 0
    mock_dedup.return_value = 0

    # Insert fake articles so extraction has something to process
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://example.com/1", "Test", "denver_post"),
    )
    conn.commit()

    run_news_pipeline(conn)

    # RSS called for all 8 direct RSS sources
    rss_calls = [c[0][1] for c in mock_rss.call_args_list]
    assert len(rss_calls) == 8
    assert "denver_post" in rss_calls
    assert "durango_herald" in rss_calls
    assert "colorado_sun" in rss_calls
    assert "co_springs_gazette" in rss_calls
    assert "steamboat_pilot" in rss_calls
    assert "summit_daily" in rss_calls
    assert "vail_daily" in rss_calls
    assert "post_independent" in rss_calls

    # Google News called for only 3 sources (no native RSS)
    gnews_calls = [c[0][1] for c in mock_gnews.call_args_list]
    assert len(gnews_calls) == 3
    assert "pueblo_chieftain" in gnews_calls
    assert "gj_sentinel" in gnews_calls
    assert "fort_collins_coloradoan" in gnews_calls
    # These moved to direct RSS
    assert "co_springs_gazette" not in gnews_calls
    assert "steamboat_pilot" not in gnews_calls
    assert "summit_daily" not in gnews_calls

    # Scraper called once with connection
    mock_scrape.assert_called_once_with(conn)

    # Dedup called once with connection
    mock_dedup.assert_called_once_with(conn)
