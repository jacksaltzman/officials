"""Tests for dashboard data JSON export."""

import json
import sqlite3
import pytest

from news.generate_dashboard_data import generate_dashboard_json


@pytest.fixture
def conn():
    """In-memory database with schema, sample articles, issues, and regions."""
    import db as db_module
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON;")
    c.execute(db_module._SCHEMA_OFFICIALS)
    c.execute(db_module._SCHEMA_KEY_STAFF)
    for stmt in db_module._NEWS_SCHEMAS:
        c.execute(stmt)

    # Insert sample data
    c.execute(
        "INSERT INTO articles (url, title, body, source, published_at) VALUES (?, ?, ?, ?, ?)",
        ("https://example.com/1", "Water crisis in Durango", "Body text",
         "durango_herald", "2026-03-01"),
    )
    c.execute(
        "INSERT INTO articles (url, title, body, source, published_at) VALUES (?, ?, ?, ?, ?)",
        ("https://example.com/2", "Denver housing boom", "Body text",
         "denver_post", "2026-03-02"),
    )
    c.execute("INSERT INTO issues (name, slug) VALUES (?, ?)", ("Water Rights", "water-rights"))
    c.execute("INSERT INTO issues (name, slug) VALUES (?, ?)", ("Housing", "housing"))
    c.execute("INSERT INTO article_issues VALUES (?, ?)", (1, 1))
    c.execute("INSERT INTO article_issues VALUES (?, ?)", (2, 2))
    c.execute("INSERT INTO article_regions VALUES (?, ?, ?)", (1, "Durango", "municipality"))
    c.execute("INSERT INTO article_regions VALUES (?, ?, ?)", (1, "La Plata County", "county"))
    c.execute("INSERT INTO article_regions VALUES (?, ?, ?)", (2, "Denver", "municipality"))
    c.commit()
    yield c
    c.close()


def test_generate_returns_valid_structure(conn):
    data = generate_dashboard_json(conn)
    assert "issues_by_count" in data
    assert "articles_by_region" in data
    assert "recent_articles" in data


def test_issues_ranked_by_count(conn):
    data = generate_dashboard_json(conn)
    issues = data["issues_by_count"]
    assert len(issues) == 2
    names = [i["name"] for i in issues]
    assert "Water Rights" in names
    assert "Housing" in names


def test_recent_articles_include_issue_tags(conn):
    data = generate_dashboard_json(conn)
    articles = data["recent_articles"]
    assert len(articles) == 2
    for article in articles:
        assert "issues" in article
        assert "title" in article
        assert "source" in article
