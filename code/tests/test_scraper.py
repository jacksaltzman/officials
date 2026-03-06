"""Tests for the article body scraper."""

import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from news.scraper import BODY_MIN_LENGTH, scrape_article_body, scrape_missing_bodies


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


# -- BODY_MIN_LENGTH constant --------------------------------------------------

def test_body_min_length_equals_200():
    """BODY_MIN_LENGTH should be 200."""
    assert BODY_MIN_LENGTH == 200


# -- scrape_article_body -------------------------------------------------------

@patch("news.scraper.httpx.get")
def test_scrape_article_body_returns_text_on_success(mock_get):
    """scrape_article_body should return extracted text when HTTP succeeds."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = """
    <html>
    <head><title>Test Article</title></head>
    <body>
        <div id="nav">Navigation links</div>
        <article>
            <h1>Water Crisis in Colorado</h1>
            <p>The ongoing water crisis in Colorado has reached a critical point.
            Residents across the state are being asked to conserve water as
            reservoir levels continue to drop to historically low levels.
            Officials say the situation requires immediate action from all
            stakeholders involved in water management.</p>
        </article>
    </body>
    </html>
    """
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    result = scrape_article_body("https://example.com/article")

    assert result is not None
    assert len(result) > 0
    assert "water" in result.lower() or "crisis" in result.lower()
    mock_get.assert_called_once()
    # Verify correct kwargs
    call_kwargs = mock_get.call_args
    assert call_kwargs.kwargs.get("follow_redirects") is True
    assert call_kwargs.kwargs.get("timeout") == 15


@patch("news.scraper.httpx.get")
def test_scrape_article_body_returns_none_on_http_failure(mock_get):
    """scrape_article_body should return None when HTTP request fails."""
    mock_get.side_effect = Exception("Connection refused")

    result = scrape_article_body("https://example.com/broken-link")

    assert result is None


@patch("news.scraper.httpx.get")
def test_scrape_article_body_returns_none_on_bad_status(mock_get):
    """scrape_article_body should return None when raise_for_status raises."""
    import httpx
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found", request=MagicMock(), response=mock_response
    )
    mock_get.return_value = mock_response

    result = scrape_article_body("https://example.com/missing")

    assert result is None


# -- scrape_missing_bodies -----------------------------------------------------

@patch("news.scraper.time.sleep")
@patch("news.scraper.httpx.get")
def test_scrape_missing_bodies_updates_short_articles(mock_get, mock_sleep, conn):
    """scrape_missing_bodies should update articles with body shorter than BODY_MIN_LENGTH."""
    # Insert an article with a short body (title-only from Google News)
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://example.com/short", "Short Article", "Brief summary", "gj_sentinel"),
    )
    conn.commit()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = """
    <html><body>
        <article><p>This is the full article body text that is long enough
        to exceed the minimum length threshold. It contains detailed
        information about the topic at hand and provides substantial
        content that readers would find informative and useful for
        understanding the issue being discussed in this news article.</p></article>
    </body></html>
    """
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    count = scrape_missing_bodies(conn)

    assert count == 1
    row = conn.execute("SELECT body FROM articles WHERE url = ?", ("https://example.com/short",)).fetchone()
    assert row[0] is not None
    assert len(row[0]) > len("Brief summary")


@patch("news.scraper.time.sleep")
@patch("news.scraper.httpx.get")
def test_scrape_missing_bodies_updates_null_body(mock_get, mock_sleep, conn):
    """scrape_missing_bodies should update articles with NULL body."""
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://example.com/null-body", "Null Body Article", None, "pueblo_chieftain"),
    )
    conn.commit()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = """
    <html><body>
        <article><p>Full article content here with enough text.</p></article>
    </body></html>
    """
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    count = scrape_missing_bodies(conn)

    assert count == 1
    row = conn.execute("SELECT body FROM articles WHERE url = ?", ("https://example.com/null-body",)).fetchone()
    assert row[0] is not None


@patch("news.scraper.httpx.get")
def test_scrape_missing_bodies_skips_long_articles(mock_get, conn):
    """scrape_missing_bodies should skip articles with body >= BODY_MIN_LENGTH."""
    long_body = "A" * 250  # well over 200
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://example.com/long", "Long Article", long_body, "denver_post"),
    )
    conn.commit()

    count = scrape_missing_bodies(conn)

    assert count == 0
    mock_get.assert_not_called()


@patch("news.scraper.time.sleep")
@patch("news.scraper.httpx.get")
def test_scrape_missing_bodies_handles_scrape_failure(mock_get, mock_sleep, conn):
    """scrape_missing_bodies should not count articles where scraping failed."""
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://example.com/fail", "Failing Article", "short", "gj_sentinel"),
    )
    conn.commit()

    mock_get.side_effect = Exception("Timeout")

    count = scrape_missing_bodies(conn)

    assert count == 0
    # Body should remain unchanged
    row = conn.execute("SELECT body FROM articles WHERE url = ?", ("https://example.com/fail",)).fetchone()
    assert row[0] == "short"


@patch("news.scraper.time.sleep")
@patch("news.scraper.httpx.get")
def test_scrape_missing_bodies_rate_limits(mock_get, mock_sleep, conn):
    """scrape_missing_bodies should call time.sleep(1.0) between requests."""
    # Insert two articles with short bodies
    for i in range(2):
        conn.execute(
            "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
            (f"https://example.com/art-{i}", f"Article {i}", "short", "gj_sentinel"),
        )
    conn.commit()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body><article><p>Full content here.</p></article></body></html>"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    scrape_missing_bodies(conn)

    # time.sleep should have been called with 1.0 between articles
    assert mock_sleep.call_count >= 1
    mock_sleep.assert_called_with(1.0)
