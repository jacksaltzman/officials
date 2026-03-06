"""Tests for LLM-based issue extraction."""

import sqlite3
import json
import pytest
from unittest.mock import patch, MagicMock

from news.extract_issues import extract_issues_for_article, ISSUE_TAXONOMY


@pytest.fixture
def conn():
    """In-memory database with full schema and a test article."""
    import db as db_module
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON;")
    c.execute(db_module._SCHEMA_OFFICIALS)
    c.execute(db_module._SCHEMA_KEY_STAFF)
    for stmt in db_module._NEWS_SCHEMAS:
        c.execute(stmt)
    c.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        (
            "https://example.com/water",
            "Durango faces water shortage amid drought",
            "The city of Durango in La Plata County is facing a severe water shortage "
            "as drought conditions persist across southwest Colorado. City officials are "
            "considering water use restrictions for the summer months.",
            "durango_herald",
        ),
    )
    c.commit()
    yield c
    c.close()


def test_taxonomy_defined():
    """ISSUE_TAXONOMY should contain expected starter issues."""
    assert "Water Rights" in ISSUE_TAXONOMY
    assert "Housing" in ISSUE_TAXONOMY
    assert "Education" in ISSUE_TAXONOMY


@patch("news.extract_issues.anthropic")
def test_extract_stores_issues_and_regions(mock_anthropic, conn):
    """Extraction should store issues and regions from LLM response."""
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "issues": ["Water Rights", "Environment"],
        "regions": [
            {"name": "Durango", "type": "municipality"},
            {"name": "La Plata County", "type": "county"},
        ],
        "sentiment": "negative",
        "county": "La Plata County",
    }))]
    mock_client.messages.create.return_value = mock_response

    extract_issues_for_article(conn, 1)

    issues = conn.execute(
        "SELECT i.name FROM article_issues ai "
        "JOIN issues i ON ai.issue_id = i.id "
        "WHERE ai.article_id = 1"
    ).fetchall()
    issue_names = {row[0] for row in issues}
    assert "Water Rights" in issue_names
    assert "Environment" in issue_names

    regions = conn.execute(
        "SELECT region_name, region_type FROM article_regions WHERE article_id = 1"
    ).fetchall()
    region_set = {(r[0], r[1]) for r in regions}
    assert ("Durango", "municipality") in region_set
    assert ("La Plata County", "county") in region_set

    # Verify sentiment stored
    sentiment = conn.execute("SELECT sentiment FROM articles WHERE id = 1").fetchone()
    assert sentiment[0] == "negative"

    # Verify county stored on regions
    counties = conn.execute("SELECT county FROM article_regions WHERE article_id = 1").fetchall()
    assert any(r[0] == "La Plata County" for r in counties)
