# Colorado Issues Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a news ingestion pipeline that pulls articles from four Colorado newspapers, extracts local issue topics via LLM, and presents them in a standalone dashboard visualization.

**Architecture:** Two ingestion adapters (RSS for Denver Post/Durango Herald, Google News for Pueblo Chieftain/GJ Sentinel) feed articles into SQLite. Claude Haiku extracts issue topics and geographic tags. A static JSON export powers a D3.js dashboard.

**Tech Stack:** Python 3, SQLite, feedparser (RSS), httpx (Google News), anthropic SDK (Haiku), D3.js, HTML/CSS

---

### Task 1: Add New Dependencies

**Files:**
- Modify: `code/requirements.txt`

**Step 1: Add feedparser and anthropic to requirements**

```
requests>=2.31
beautifulsoup4>=4.12
httpx>=0.27
pandas>=2.1
openpyxl>=3.1
pdfplumber>=0.11
lxml>=5.1
feedparser>=6.0
anthropic>=0.40
```

**Step 2: Install dependencies**

Run: `pip install -r code/requirements.txt`
Expected: All packages install successfully

**Step 3: Commit**

```bash
git add code/requirements.txt
git commit -m "deps: add feedparser and anthropic SDK"
```

---

### Task 2: Add News Schema to Database Layer

**Files:**
- Modify: `code/db.py`
- Create: `code/tests/test_news_schema.py`

**Step 1: Write the failing test**

Create `code/tests/__init__.py` (empty) and `code/tests/test_news_schema.py`:

```python
"""Tests for the news-related database schema."""

import sqlite3
import pytest
from db import get_connection


@pytest.fixture
def conn():
    """In-memory database with schema applied."""
    import db as db_module
    original_path = db_module.DB_PATH
    db_module.DB_PATH = ":memory:"
    # We need a fresh in-memory connection with schema
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON;")
    # Apply all schema
    c.execute(db_module._SCHEMA_OFFICIALS)
    c.execute(db_module._SCHEMA_KEY_STAFF)
    # Apply news schema (will be added in step 3)
    for stmt in db_module._NEWS_SCHEMAS:
        c.execute(stmt)
    c.commit()
    yield c
    c.close()
    db_module.DB_PATH = original_path


def test_articles_table_exists(conn):
    """articles table should exist with expected columns."""
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
    """issues table should exist with expected columns."""
    cursor = conn.execute("PRAGMA table_info(issues)")
    cols = {row[1] for row in cursor.fetchall()}
    assert "id" in cols
    assert "name" in cols
    assert "slug" in cols


def test_article_issues_junction(conn):
    """article_issues junction table should link articles to issues."""
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://example.com/1", "Test Article", "denver_post"),
    )
    conn.execute(
        "INSERT INTO issues (name, slug) VALUES (?, ?)",
        ("Water Rights", "water-rights"),
    )
    conn.execute(
        "INSERT INTO article_issues (article_id, issue_id) VALUES (?, ?)",
        (1, 1),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM article_issues").fetchone()
    assert row == (1, 1)


def test_article_regions_junction(conn):
    """article_regions junction table should link articles to regions."""
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://example.com/2", "Test Article 2", "durango_herald"),
    )
    conn.execute(
        "INSERT INTO article_regions (article_id, region_name, region_type) VALUES (?, ?, ?)",
        (1, "Durango", "municipality"),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM article_regions").fetchone()
    assert row == (1, "Durango", "municipality")


def test_url_uniqueness(conn):
    """Duplicate article URLs should be rejected."""
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://example.com/dup", "First", "denver_post"),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
            ("https://example.com/dup", "Second", "denver_post"),
        )
```

**Step 2: Run test to verify it fails**

Run: `cd code && python -m pytest tests/test_news_schema.py -v`
Expected: FAIL — `_NEWS_SCHEMAS` not found in db module

**Step 3: Add news schema to db.py**

Add these schema constants after `_SCHEMA_KEY_STAFF` in `code/db.py`:

```python
_SCHEMA_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    author TEXT,
    published_at TEXT,
    source TEXT NOT NULL,
    ingested_at TEXT DEFAULT (datetime('now'))
);
"""

_SCHEMA_ISSUES = """
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL
);
"""

_SCHEMA_ARTICLE_ISSUES = """
CREATE TABLE IF NOT EXISTS article_issues (
    article_id INTEGER REFERENCES articles(id),
    issue_id INTEGER REFERENCES issues(id),
    PRIMARY KEY (article_id, issue_id)
);
"""

_SCHEMA_ARTICLE_REGIONS = """
CREATE TABLE IF NOT EXISTS article_regions (
    article_id INTEGER REFERENCES articles(id),
    region_name TEXT NOT NULL,
    region_type TEXT NOT NULL,
    PRIMARY KEY (article_id, region_name)
);
"""

_NEWS_SCHEMAS = [
    _SCHEMA_ARTICLES,
    _SCHEMA_ISSUES,
    _SCHEMA_ARTICLE_ISSUES,
    _SCHEMA_ARTICLE_REGIONS,
]
```

In the `get_connection()` function, add after the existing schema creation lines:

```python
    for stmt in _NEWS_SCHEMAS:
        conn.execute(stmt)
```

**Step 4: Run tests to verify they pass**

Run: `cd code && python -m pytest tests/test_news_schema.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add code/db.py code/tests/__init__.py code/tests/test_news_schema.py
git commit -m "feat: add articles, issues, and region schema for news pipeline"
```

---

### Task 3: RSS Ingestion Adapter

**Files:**
- Create: `code/news/rss_adapter.py`
- Create: `code/news/__init__.py`
- Create: `code/tests/test_rss_adapter.py`

**Step 1: Write the failing test**

```python
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
    """RSS_SOURCES should have entries for denver_post and durango_herald."""
    assert "denver_post" in RSS_SOURCES
    assert "durango_herald" in RSS_SOURCES


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
```

**Step 2: Run test to verify it fails**

Run: `cd code && python -m pytest tests/test_rss_adapter.py -v`
Expected: FAIL — `news.rss_adapter` module not found

**Step 3: Implement RSS adapter**

Create `code/news/__init__.py` (empty file).

Create `code/news/rss_adapter.py`:

```python
"""RSS feed ingestion adapter for Denver Post and Durango Herald."""

import logging
import sqlite3
from html import unescape
from re import sub as re_sub

import feedparser

log = logging.getLogger(__name__)

RSS_SOURCES: dict[str, list[str]] = {
    "denver_post": [
        "https://www.denverpost.com/feed/",
    ],
    "durango_herald": [
        "https://www.durangoherald.com/feeds/local-news",
        "https://www.durangoherald.com/feeds/news",
        "https://www.durangoherald.com/feeds/business",
        "https://www.durangoherald.com/feeds/education",
    ],
}


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re_sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re_sub(r"\s+", " ", text).strip()


def _extract_body(entry) -> str:
    """Get the best available body text from a feedparser entry."""
    # Prefer content:encoded (full article)
    if hasattr(entry, "content") and entry.content:
        return _strip_html(entry.content[0].value)
    # Fall back to summary
    if hasattr(entry, "summary") and entry.summary:
        return _strip_html(entry.summary)
    return ""


def fetch_rss_articles(conn: sqlite3.Connection, source_name: str) -> int:
    """Fetch articles from RSS feeds for a given source and store in DB.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database connection with news schema applied.
    source_name : str
        Key in RSS_SOURCES (e.g. 'denver_post').

    Returns
    -------
    int
        Number of new articles inserted.
    """
    urls = RSS_SOURCES.get(source_name, [])
    if not urls:
        log.warning("No RSS feeds configured for %s", source_name)
        return 0

    inserted = 0
    for feed_url in urls:
        log.info("Fetching RSS: %s", feed_url)
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            title = entry.title
            url = entry.link
            body = _extract_body(entry)
            author = entry.get("author", None)
            published = entry.get("published", None)

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO articles (url, title, body, author, published_at, source) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (url, title, body, author, published, source_name),
                )
                if conn.total_changes:
                    inserted += 1
            except sqlite3.IntegrityError:
                pass  # duplicate URL, skip

        conn.commit()

    log.info("Inserted %d new articles from %s", inserted, source_name)
    return inserted
```

**Step 4: Run tests to verify they pass**

Run: `cd code && python -m pytest tests/test_rss_adapter.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add code/news/__init__.py code/news/rss_adapter.py code/tests/test_rss_adapter.py
git commit -m "feat: add RSS ingestion adapter for Denver Post and Durango Herald"
```

---

### Task 4: Google News Ingestion Adapter

**Files:**
- Create: `code/news/google_news_adapter.py`
- Create: `code/tests/test_google_news_adapter.py`

**Step 1: Write the failing test**

```python
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
    """GOOGLE_NEWS_SOURCES should have entries for chieftain and sentinel."""
    assert "pueblo_chieftain" in GOOGLE_NEWS_SOURCES
    assert "gj_sentinel" in GOOGLE_NEWS_SOURCES


def _make_rss_entry(title, link, snippet, published="2026-03-06"):
    """Create a mock feedparser entry for Google News RSS."""
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.summary = snippet
    entry.get.side_effect = lambda k, d=None: {
        "published": published,
    }.get(k, d)
    entry.content = []
    return entry


@patch("news.google_news_adapter.feedparser.parse")
def test_fetch_stores_articles(mock_parse, conn):
    """Articles from Google News should be stored in the articles table."""
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
    """Same URL should not be inserted twice."""
    entry = _make_rss_entry("Same", "https://news.google.com/rss/articles/dup", "Snippet")
    mock_feed = MagicMock()
    mock_feed.entries = [entry]
    mock_parse.return_value = mock_feed

    fetch_google_news_articles(conn, "pueblo_chieftain")
    fetch_google_news_articles(conn, "pueblo_chieftain")

    count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert count == 1
```

**Step 2: Run test to verify it fails**

Run: `cd code && python -m pytest tests/test_google_news_adapter.py -v`
Expected: FAIL — `news.google_news_adapter` not found

**Step 3: Implement Google News adapter**

Create `code/news/google_news_adapter.py`:

```python
"""Google News RSS ingestion adapter for Pueblo Chieftain and GJ Sentinel."""

import logging
import sqlite3
from html import unescape
from re import sub as re_sub
from urllib.parse import quote_plus

import feedparser

log = logging.getLogger(__name__)

GOOGLE_NEWS_SOURCES: dict[str, str] = {
    "pueblo_chieftain": "site:chieftain.com",
    "gj_sentinel": "site:gjsentinel.com",
}

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re_sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re_sub(r"\s+", " ", text).strip()


def fetch_google_news_articles(conn: sqlite3.Connection, source_name: str) -> int:
    """Fetch articles from Google News RSS for a given source and store in DB.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database connection with news schema applied.
    source_name : str
        Key in GOOGLE_NEWS_SOURCES (e.g. 'pueblo_chieftain').

    Returns
    -------
    int
        Number of new articles inserted.
    """
    query = GOOGLE_NEWS_SOURCES.get(source_name)
    if not query:
        log.warning("No Google News query configured for %s", source_name)
        return 0

    feed_url = _GOOGLE_NEWS_RSS.format(query=quote_plus(query))
    log.info("Fetching Google News RSS: %s", feed_url)
    feed = feedparser.parse(feed_url)

    inserted = 0
    for entry in feed.entries:
        title = entry.title
        url = entry.link
        snippet = _strip_html(entry.summary) if hasattr(entry, "summary") else ""
        published = entry.get("published", None)

        try:
            conn.execute(
                "INSERT OR IGNORE INTO articles (url, title, body, published_at, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (url, title, snippet, published, source_name),
            )
            if conn.total_changes:
                inserted += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    log.info("Inserted %d new articles from %s", inserted, source_name)
    return inserted
```

**Step 4: Run tests to verify they pass**

Run: `cd code && python -m pytest tests/test_google_news_adapter.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add code/news/google_news_adapter.py code/tests/test_google_news_adapter.py
git commit -m "feat: add Google News ingestion adapter for Chieftain and Sentinel"
```

---

### Task 5: LLM Issue Extraction

**Files:**
- Create: `code/news/extract_issues.py`
- Create: `code/tests/test_extract_issues.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `cd code && python -m pytest tests/test_extract_issues.py -v`
Expected: FAIL — `news.extract_issues` not found

**Step 3: Implement issue extraction**

Create `code/news/extract_issues.py`:

```python
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
    """Extract issues and regions for a single article using Claude Haiku.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database connection with news schema applied.
    article_id : int
        The article row id to process.
    """
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
```

**Step 4: Run tests to verify they pass**

Run: `cd code && python -m pytest tests/test_extract_issues.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add code/news/extract_issues.py code/tests/test_extract_issues.py
git commit -m "feat: add LLM-based issue and region extraction via Claude Haiku"
```

---

### Task 6: News Pipeline Orchestrator

**Files:**
- Create: `code/news/pipeline.py`
- Create: `code/tests/test_news_pipeline.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `cd code && python -m pytest tests/test_news_pipeline.py -v`
Expected: FAIL — `news.pipeline` not found

**Step 3: Implement pipeline orchestrator**

Create `code/news/pipeline.py`:

```python
"""News pipeline orchestrator: ingest articles and extract issues."""

import logging
import sqlite3

from news.rss_adapter import fetch_rss_articles
from news.google_news_adapter import fetch_google_news_articles
from news.extract_issues import extract_issues_for_article

log = logging.getLogger(__name__)


def run_news_pipeline(conn: sqlite3.Connection) -> None:
    """Run the full news ingestion and extraction pipeline.

    1. Fetch articles from all four sources
    2. Extract issues and regions for any unprocessed articles
    """
    log.info("=" * 60)
    log.info("Colorado News Pipeline")
    log.info("=" * 60)

    # Phase 1: Ingest articles
    total = 0
    for source in ["denver_post", "durango_herald"]:
        total += fetch_rss_articles(conn, source)

    for source in ["pueblo_chieftain", "gj_sentinel"]:
        total += fetch_google_news_articles(conn, source)

    log.info("Ingested %d new articles total", total)

    # Phase 2: Extract issues for unprocessed articles
    unprocessed = conn.execute(
        "SELECT a.id FROM articles a "
        "LEFT JOIN article_issues ai ON a.id = ai.article_id "
        "WHERE ai.article_id IS NULL"
    ).fetchall()

    log.info("Processing %d untagged articles", len(unprocessed))
    for (article_id,) in unprocessed:
        try:
            extract_issues_for_article(conn, article_id)
        except Exception as e:
            log.error("Failed to extract issues for article %d: %s", article_id, e)

    log.info("=" * 60)
    log.info("News pipeline complete!")
    log.info("=" * 60)
```

**Step 4: Run tests to verify they pass**

Run: `cd code && python -m pytest tests/test_news_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add code/news/pipeline.py code/tests/test_news_pipeline.py
git commit -m "feat: add news pipeline orchestrator"
```

---

### Task 7: Dashboard Data Export

**Files:**
- Create: `code/news/generate_dashboard_data.py`
- Create: `code/tests/test_dashboard_data.py`

**Step 1: Write the failing test**

```python
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
    """Output should have issues_by_count, articles_by_region, and recent_articles."""
    data = generate_dashboard_json(conn)
    assert "issues_by_count" in data
    assert "articles_by_region" in data
    assert "recent_articles" in data


def test_issues_ranked_by_count(conn):
    """Issues should be ranked by article count descending."""
    data = generate_dashboard_json(conn)
    issues = data["issues_by_count"]
    assert len(issues) == 2
    # Both have 1 article, so order is alphabetical tiebreak
    names = [i["name"] for i in issues]
    assert "Water Rights" in names
    assert "Housing" in names


def test_recent_articles_include_issue_tags(conn):
    """Each recent article should include its issue tags."""
    data = generate_dashboard_json(conn)
    articles = data["recent_articles"]
    assert len(articles) == 2
    for article in articles:
        assert "issues" in article
        assert "title" in article
        assert "source" in article
```

**Step 2: Run test to verify it fails**

Run: `cd code && python -m pytest tests/test_dashboard_data.py -v`
Expected: FAIL — `news.generate_dashboard_data` not found

**Step 3: Implement dashboard data export**

Create `code/news/generate_dashboard_data.py`:

```python
"""Generate dashboard_data.json for the issues dashboard visualization."""

import json
import logging
import sqlite3
from pathlib import Path

from db import BASE_DIR

log = logging.getLogger(__name__)

DASHBOARD_DIR = BASE_DIR / "dashboard" / "data"

# Map paper sources to broad regions
SOURCE_TO_REGION = {
    "denver_post": "Front Range",
    "durango_herald": "Southwest",
    "pueblo_chieftain": "Southern",
    "gj_sentinel": "Western Slope",
}


def generate_dashboard_json(conn: sqlite3.Connection) -> dict:
    """Build the dashboard data structure from the database.

    Returns
    -------
    dict
        Dashboard data with issues_by_count, articles_by_region, and recent_articles.
    """
    # Issues ranked by article count
    issues = conn.execute(
        "SELECT i.name, i.slug, COUNT(ai.article_id) as cnt "
        "FROM issues i "
        "JOIN article_issues ai ON i.id = ai.issue_id "
        "GROUP BY i.id "
        "ORDER BY cnt DESC, i.name ASC"
    ).fetchall()

    issues_by_count = [
        {"name": row[0], "slug": row[1], "count": row[2]}
        for row in issues
    ]

    # Article counts by broad region
    region_counts = {}
    for source, region in SOURCE_TO_REGION.items():
        row = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE source = ?", (source,)
        ).fetchone()
        region_counts[region] = region_counts.get(region, 0) + row[0]

    articles_by_region = [
        {"region": region, "count": count}
        for region, count in sorted(region_counts.items(), key=lambda x: -x[1])
    ]

    # Recent articles with issue tags
    rows = conn.execute(
        "SELECT a.id, a.title, a.url, a.source, a.published_at "
        "FROM articles a "
        "ORDER BY a.published_at DESC "
        "LIMIT 100"
    ).fetchall()

    recent_articles = []
    for row in rows:
        article_id, title, url, source, published_at = row
        issue_rows = conn.execute(
            "SELECT i.name FROM article_issues ai "
            "JOIN issues i ON ai.issue_id = i.id "
            "WHERE ai.article_id = ?",
            (article_id,),
        ).fetchall()
        issue_names = [r[0] for r in issue_rows]

        region_rows = conn.execute(
            "SELECT region_name, region_type FROM article_regions WHERE article_id = ?",
            (article_id,),
        ).fetchall()
        regions = [{"name": r[0], "type": r[1]} for r in region_rows]

        recent_articles.append({
            "title": title,
            "url": url,
            "source": source,
            "region": SOURCE_TO_REGION.get(source, "Unknown"),
            "published_at": published_at,
            "issues": issue_names,
            "locations": regions,
        })

    return {
        "issues_by_count": issues_by_count,
        "articles_by_region": articles_by_region,
        "recent_articles": recent_articles,
    }


def run() -> None:
    """Generate dashboard/data/dashboard_data.json."""
    from db import get_connection
    conn = get_connection()
    try:
        data = generate_dashboard_json(conn)
        DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
        out_path = DASHBOARD_DIR / "dashboard_data.json"
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        log.info(
            "Wrote dashboard data: %d issues, %d articles",
            len(data["issues_by_count"]),
            len(data["recent_articles"]),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    run()
```

**Step 4: Run tests to verify they pass**

Run: `cd code && python -m pytest tests/test_dashboard_data.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add code/news/generate_dashboard_data.py code/tests/test_dashboard_data.py
git commit -m "feat: add dashboard data JSON export"
```

---

### Task 8: Dashboard HTML/D3.js Visualization

**Files:**
- Create: `dashboard/index.html`
- Create: `dashboard/data/.gitkeep`

**Step 1: Create the dashboard directory structure**

```bash
mkdir -p dashboard/data
touch dashboard/data/.gitkeep
```

**Step 2: Build the dashboard page**

Create `dashboard/index.html` — a standalone HTML page using D3.js with:

- **Top bar:** "Colorado Issues" title, time range pills (7d / 30d / 90d), source filter dropdown (All / Denver Post / Durango Herald / Pueblo Chieftain / GJ Sentinel)
- **Left panel (~40%):** Horizontal bar chart of issues ranked by article count. Bars are clickable to filter.
- **Right panel (~60%):** Four-region summary cards (Front Range, Southern, Southwest, Western Slope) showing article count per region, colored by intensity. Below: scrollable article feed showing title, source pill, date, and issue tag pills. Clicking a headline opens the source article in a new tab.

Style should match the officials app: `DM Sans` + `Oswald` fonts, `#FDFBF9` background, `#111111` top bar, `#4C6971` accent color.

Data loaded from `data/dashboard_data.json` via fetch.

Use the `@superpowers:frontend-design` skill guidance when implementing this page — it should be distinctive and polished, not generic.

**Step 3: Commit**

```bash
git add dashboard/
git commit -m "feat: add Colorado Issues dashboard visualization"
```

---

### Task 9: Wire Up CLI Entry Point

**Files:**
- Create: `code/run_news.py`

**Step 1: Create the entry point**

Create `code/run_news.py`:

```python
"""CLI entry point for the news pipeline."""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from db import get_connection
from news.pipeline import run_news_pipeline
from news.generate_dashboard_data import run as run_dashboard_export


def main() -> None:
    """Run news ingestion, extraction, and dashboard export."""
    conn = get_connection()
    try:
        run_news_pipeline(conn)
    finally:
        conn.close()

    run_dashboard_export()


if __name__ == "__main__":
    main()
```

**Step 2: Test it runs end-to-end**

Run: `cd code && python run_news.py`
Expected: Logs showing RSS fetches, Google News fetches, LLM extraction, and dashboard JSON written to `dashboard/data/dashboard_data.json`

**Step 3: Commit**

```bash
git add code/run_news.py
git commit -m "feat: add CLI entry point for news pipeline"
```

---

### Task 10: Run All Tests and Push

**Step 1: Run the full test suite**

Run: `cd code && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Push to remote**

```bash
git push origin fresh-main:main
```

**Step 3: Verify on GitHub**

Check https://github.com/jacksaltzman/officials for the new files.
