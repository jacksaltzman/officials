"""Tests for the news-related database schema."""

import sqlite3
import pytest


@pytest.fixture
def conn():
    """In-memory database with schema applied."""
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


def test_articles_table_exists(conn):
    cursor = conn.execute("PRAGMA table_info(articles)")
    cols = {row[1] for row in cursor.fetchall()}
    assert "id" in cols
    assert "url" in cols
    assert "title" in cols
    assert "body" in cols
    assert "author" in cols
    assert "published_at" in cols
    assert "source" in cols
    assert "ingested_at" in cols


def test_issues_table_exists(conn):
    cursor = conn.execute("PRAGMA table_info(issues)")
    cols = {row[1] for row in cursor.fetchall()}
    assert "id" in cols
    assert "name" in cols
    assert "slug" in cols


def test_article_issues_junction(conn):
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)", ("https://example.com/1", "Test Article", "denver_post"))
    conn.execute("INSERT INTO issues (name, slug) VALUES (?, ?)", ("Water Rights", "water-rights"))
    conn.execute("INSERT INTO article_issues (article_id, issue_id) VALUES (?, ?)", (1, 1))
    conn.commit()
    row = conn.execute("SELECT * FROM article_issues").fetchone()
    assert row == (1, 1)


def test_article_regions_junction(conn):
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)", ("https://example.com/2", "Test Article 2", "durango_herald"))
    conn.execute("INSERT INTO article_regions (article_id, region_name, region_type) VALUES (?, ?, ?)", (1, "Durango", "municipality"))
    conn.commit()
    row = conn.execute("SELECT * FROM article_regions").fetchone()
    assert row == (1, "Durango", "municipality")


def test_url_uniqueness(conn):
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)", ("https://example.com/dup", "First", "denver_post"))
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)", ("https://example.com/dup", "Second", "denver_post"))
