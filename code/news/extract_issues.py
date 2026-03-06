"""LLM-based issue and geography extraction using Claude Haiku."""

import json
import logging
import sqlite3
from re import sub as re_sub

import anthropic

log = logging.getLogger(__name__)

ISSUE_TAXONOMY = [
    "Water Rights", "Housing", "Public Safety", "Education",
    "Transportation", "Healthcare", "Environment", "Economy/Jobs",
    "Agriculture", "Energy", "Taxes/Budget", "Immigration",
    "Gun Policy", "Recreation/Tourism", "Infrastructure",
]

_SYSTEM_PROMPT = """You are a local news analyst for Colorado. Given a news article, extract:
1. 1-3 issue topics the article relates to. Prefer topics from this list: {taxonomy}
   If the article clearly relates to a topic not on the list, create a concise new one.
2. The specific geographic locations mentioned (city and/or county in Colorado).

Respond with JSON only, no other text:
{{"issues": ["Topic 1", "Topic 2"], "regions": [{{"name": "City Name", "type": "municipality"}}, {{"name": "County Name", "type": "county"}}]}}
"""


def _get_or_create_issue(conn: sqlite3.Connection, issue_name: str) -> int:
    """Get or create an issue row, return its id."""
    slug = re_sub(r"[^a-z0-9]+", "-", issue_name.lower()).strip("-")
    row = conn.execute("SELECT id FROM issues WHERE slug = ?", (slug,)).fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT INTO issues (name, slug) VALUES (?, ?)",
        (issue_name, slug),
    )
    conn.commit()
    return conn.execute("SELECT id FROM issues WHERE slug = ?", (slug,)).fetchone()[0]


def extract_issues_for_article(conn: sqlite3.Connection, article_id: int) -> None:
    """Extract issues and regions for a single article using Claude Haiku."""
    row = conn.execute(
        "SELECT title, body FROM articles WHERE id = ?", (article_id,)
    ).fetchone()
    if not row:
        log.warning("Article %d not found", article_id)
        return

    title, body = row
    article_text = f"Title: {title}\n\n{body or ''}"

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-20250414",
        max_tokens=300,
        system=_SYSTEM_PROMPT.format(taxonomy=", ".join(ISSUE_TAXONOMY)),
        messages=[{"role": "user", "content": article_text}],
    )

    try:
        result = json.loads(response.content[0].text)
    except (json.JSONDecodeError, IndexError) as e:
        log.error("Failed to parse LLM response for article %d: %s", article_id, e)
        return

    # Store issues
    for issue_name in result.get("issues", []):
        issue_id = _get_or_create_issue(conn, issue_name)
        conn.execute(
            "INSERT OR IGNORE INTO article_issues (article_id, issue_id) VALUES (?, ?)",
            (article_id, issue_id),
        )

    # Store regions
    for region in result.get("regions", []):
        name = region.get("name", "")
        rtype = region.get("type", "municipality")
        if name:
            conn.execute(
                "INSERT OR IGNORE INTO article_regions (article_id, region_name, region_type) "
                "VALUES (?, ?, ?)",
                (article_id, name, rtype),
            )

    conn.commit()
    log.info("Article %d: issues=%s", article_id, result.get("issues", []))
