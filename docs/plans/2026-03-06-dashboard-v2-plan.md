# Colorado Issues Dashboard v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the issues dashboard into a rich analytical tool with article scraping, 9 sources, sentiment, county map, trends, co-occurrence, deduplication, and an officials bridge.

**Architecture:** Three layers built in order — data quality (scraper, sources, dedup), extraction enhancements (sentiment, county in same Haiku call), then dashboard visualizations (map, trends, sentiment, co-occurrence, dedup display, officials drawer). All data flows through SQLite, exported to JSON, rendered with D3.js.

**Tech Stack:** Python 3, SQLite, readability-lxml, httpx, anthropic, feedparser, D3.js v7, Colorado counties TopoJSON

---

### Task 1: Article Body Scraper

**Files:**
- Create: `code/news/scraper.py`
- Modify: `code/requirements.txt` (add `readability-lxml>=0.8`)
- Modify: `code/news/pipeline.py` (add scraper step between ingestion and extraction)
- Test: `code/tests/test_scraper.py`

**Context:** ~200 Google News articles have only a title (body <200 chars). The scraper follows the Google News redirect URL to the actual newspaper site, extracts the article body with readability-lxml, and updates the `articles.body` column.

**Step 1: Add readability-lxml to requirements**

In `code/requirements.txt`, add after `lxml>=5.1`:
```
readability-lxml>=0.8
```

Run: `cd code && pip install readability-lxml`

**Step 2: Write the failing test**

```python
# code/tests/test_scraper.py
"""Tests for article body scraping."""
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from db import get_connection
from news.scraper import scrape_article_body, scrape_missing_bodies, BODY_MIN_LENGTH


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        author TEXT,
        published_at TEXT,
        source TEXT NOT NULL,
        ingested_at TEXT DEFAULT (datetime('now'))
    )""")
    c.commit()
    return c


def test_body_min_length_constant():
    assert BODY_MIN_LENGTH == 200


def test_scrape_article_body_returns_text():
    html = "<html><body><article><p>This is a real article about Colorado water rights.</p></article></body></html>"
    with patch("news.scraper.httpx.get") as mock_get:
        resp = MagicMock()
        resp.text = html
        resp.status_code = 200
        resp.is_redirect = False
        mock_get.return_value = resp
        result = scrape_article_body("https://example.com/article")
    assert result is not None
    assert "Colorado water rights" in result


def test_scrape_article_body_returns_none_on_failure():
    with patch("news.scraper.httpx.get", side_effect=Exception("timeout")):
        result = scrape_article_body("https://example.com/fail")
    assert result is None


def test_scrape_missing_bodies_updates_short_articles(conn):
    # Insert article with short body (title-only from Google News)
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://news.google.com/123", "Colorado budget crisis", "Colorado budget crisis", "pueblo_chieftain"),
    )
    conn.commit()
    html = "<html><body><p>The state of Colorado faces a major budget shortfall this year affecting schools and infrastructure across all 64 counties.</p></body></html>"
    with patch("news.scraper.httpx.get") as mock_get:
        resp = MagicMock()
        resp.text = html
        resp.status_code = 200
        resp.is_redirect = False
        mock_get.return_value = resp
        count = scrape_missing_bodies(conn)
    assert count == 1
    row = conn.execute("SELECT body FROM articles WHERE id = 1").fetchone()
    assert len(row[0]) > 200 or "budget shortfall" in row[0]


def test_scrape_missing_bodies_skips_long_articles(conn):
    # Insert article with substantial body — should be skipped
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://denverpost.com/article", "Title", "x" * 300, "denver_post"),
    )
    conn.commit()
    count = scrape_missing_bodies(conn)
    assert count == 0
```

**Step 3: Run test to verify it fails**

Run: `cd code && python -m pytest tests/test_scraper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news.scraper'`

**Step 4: Write minimal implementation**

```python
# code/news/scraper.py
"""Scrape full article bodies for title-only articles."""

import logging
import sqlite3
import time

import httpx
from readability import Document

log = logging.getLogger(__name__)

BODY_MIN_LENGTH = 200
_REQUEST_DELAY = 1.0  # seconds between requests
_TIMEOUT = 15.0


def scrape_article_body(url: str) -> str | None:
    """Fetch a URL, extract main article text. Returns None on failure."""
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; COIssuesDashboard/1.0)"},
        )
        if resp.status_code != 200:
            log.warning("HTTP %d for %s", resp.status_code, url)
            return None
        doc = Document(resp.text)
        # readability returns HTML; strip tags for plain text
        from bs4 import BeautifulSoup
        text = BeautifulSoup(doc.summary(), "lxml").get_text(separator="\n", strip=True)
        return text if len(text) > 50 else None
    except Exception as e:
        log.warning("Scrape failed for %s: %s", url, e)
        return None


def scrape_missing_bodies(conn: sqlite3.Connection) -> int:
    """Find articles with short/missing bodies, scrape full text. Returns count updated."""
    rows = conn.execute(
        "SELECT id, url FROM articles WHERE body IS NULL OR length(body) < ?",
        (BODY_MIN_LENGTH,),
    ).fetchall()

    if not rows:
        log.info("No articles need body scraping")
        return 0

    log.info("Scraping bodies for %d articles", len(rows))
    updated = 0
    for article_id, url in rows:
        body = scrape_article_body(url)
        if body:
            conn.execute("UPDATE articles SET body = ? WHERE id = ?", (body, article_id))
            conn.commit()
            updated += 1
            log.info("Scraped body for article %d (%d chars)", article_id, len(body))
        time.sleep(_REQUEST_DELAY)

    log.info("Scraped %d / %d articles", updated, len(rows))
    return updated
```

**Step 5: Run tests and verify they pass**

Run: `cd code && python -m pytest tests/test_scraper.py -v`
Expected: All 5 PASS

**Step 6: Wire scraper into pipeline**

In `code/news/pipeline.py`, add import and call between ingestion and extraction:

```python
from news.scraper import scrape_missing_bodies
```

After all `fetch_rss_articles` / `fetch_google_news_articles` calls and before the extraction loop, add:

```python
    # Phase 1.5: Scrape full bodies for title-only articles
    scraped = scrape_missing_bodies(conn)
    log.info("Scraped %d article bodies", scraped)
```

**Step 7: Commit**

```bash
git add code/news/scraper.py code/tests/test_scraper.py code/news/pipeline.py code/requirements.txt
git commit -m "feat: add article body scraper for title-only articles"
```

---

### Task 2: Add 5 New Sources

**Files:**
- Modify: `code/news/rss_adapter.py` (add Colorado Sun)
- Modify: `code/news/google_news_adapter.py` (add 4 sources)
- Modify: `code/news/pipeline.py` (add new sources to loop)
- Modify: `code/news/generate_dashboard_data.py` (add new SOURCE_TO_REGION entries)
- Modify: `code/tests/test_rss_adapter.py`
- Modify: `code/tests/test_google_news_adapter.py`

**Context:** Adding Colorado Sun (RSS), CO Springs Gazette, Fort Collins Coloradoan, Steamboat Pilot, Summit Daily (all Google News).

**Step 1: Update tests to expect new sources**

In `code/tests/test_rss_adapter.py`, update the test that checks RSS_SOURCES keys to also expect `"colorado_sun"`.

In `code/tests/test_google_news_adapter.py`, update the test that checks GOOGLE_NEWS_SOURCES keys to also expect `"co_springs_gazette"`, `"fort_collins_coloradoan"`, `"steamboat_pilot"`, `"summit_daily"`.

**Step 2: Run tests to verify they fail**

Run: `cd code && python -m pytest tests/test_rss_adapter.py tests/test_google_news_adapter.py -v`
Expected: FAIL — missing keys

**Step 3: Add sources**

In `code/news/rss_adapter.py`, add to `RSS_SOURCES`:
```python
    "colorado_sun": [
        "https://coloradosun.com/feed/",
    ],
```

In `code/news/google_news_adapter.py`, add to `GOOGLE_NEWS_SOURCES`:
```python
    "co_springs_gazette": "site:gazette.com Colorado",
    "fort_collins_coloradoan": "site:coloradoan.com Colorado",
    "steamboat_pilot": "site:steamboatpilot.com",
    "summit_daily": "site:summitdaily.com",
```

**Step 4: Update pipeline.py**

Add new sources to the ingestion loops:

```python
    for source in ["denver_post", "durango_herald", "colorado_sun"]:
        fetch_rss_articles(conn, source)
    for source in ["pueblo_chieftain", "gj_sentinel", "co_springs_gazette",
                    "fort_collins_coloradoan", "steamboat_pilot", "summit_daily"]:
        fetch_google_news_articles(conn, source)
```

**Step 5: Update SOURCE_TO_REGION in generate_dashboard_data.py**

```python
SOURCE_TO_REGION = {
    "denver_post": "Front Range",
    "durango_herald": "Southwest",
    "pueblo_chieftain": "Southern",
    "gj_sentinel": "Western Slope",
    "colorado_sun": "Statewide",
    "co_springs_gazette": "Pikes Peak",
    "fort_collins_coloradoan": "Northern",
    "steamboat_pilot": "Northwest",
    "summit_daily": "Mountain",
}
```

**Step 6: Update source filter dropdown in dashboard/index.html**

Add new `<option>` elements to the `#source-filter` select, and add source pill CSS classes:
```css
.source-pill--colorado_sun       { background: #F4A024; color: #111; }
.source-pill--co_springs_gazette { background: #1B3A5C; }
.source-pill--fort_collins_coloradoan { background: #5B2C6F; }
.source-pill--steamboat_pilot    { background: #1A6B4A; }
.source-pill--summit_daily       { background: #6B4226; }
```

Add to `SOURCE_NAMES` in JS:
```javascript
'colorado_sun':             'Colorado Sun',
'co_springs_gazette':       'CO Springs Gazette',
'fort_collins_coloradoan':  'Fort Collins Coloradoan',
'steamboat_pilot':          'Steamboat Pilot',
'summit_daily':             'Summit Daily',
```

**Step 7: Run tests**

Run: `cd code && python -m pytest tests/ -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add code/news/rss_adapter.py code/news/google_news_adapter.py code/news/pipeline.py code/news/generate_dashboard_data.py code/tests/ dashboard/index.html
git commit -m "feat: add 5 new Colorado sources (Sun, Gazette, Coloradoan, Pilot, Summit)"
```

---

### Task 3: Expanded Haiku Prompt (Sentiment + County)

**Files:**
- Modify: `code/news/extract_issues.py` (new prompt, store sentiment + county)
- Modify: `code/db.py` (add sentiment column, county column)
- Modify: `code/tests/test_extract_issues.py` (test new fields)
- Modify: `code/tests/test_news_schema.py` (test new columns)

**Context:** Extend the Claude Haiku extraction to also return `sentiment` (positive/neutral/negative) and `county` (best-guess Colorado county). Same API call, ~50 more tokens.

**Step 1: Update schema in db.py**

Add `sentiment TEXT` to `_SCHEMA_ARTICLES`:
```sql
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    author TEXT,
    published_at TEXT,
    source TEXT NOT NULL,
    sentiment TEXT,
    ingested_at TEXT DEFAULT (datetime('now'))
);
```

Add `county TEXT` to `_SCHEMA_ARTICLE_REGIONS`:
```sql
CREATE TABLE IF NOT EXISTS article_regions (
    article_id INTEGER REFERENCES articles(id),
    region_name TEXT NOT NULL,
    region_type TEXT NOT NULL,
    county TEXT,
    PRIMARY KEY (article_id, region_name)
);
```

**Note:** Since SQLite tables already exist, also add migration logic at the end of `get_connection()`:
```python
    # Schema migrations for v2
    try:
        conn.execute("ALTER TABLE articles ADD COLUMN sentiment TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE article_regions ADD COLUMN county TEXT")
    except sqlite3.OperationalError:
        pass
```

**Step 2: Update the extraction prompt**

In `code/news/extract_issues.py`, update `_SYSTEM_PROMPT`:
```python
_SYSTEM_PROMPT = """You are a local news analyst for Colorado. Given a news article, extract:
1. 1-3 issue topics the article relates to. Prefer topics from this list: {taxonomy}
   If the article clearly relates to a topic not on the list, create a concise new one.
2. The specific geographic locations mentioned (city and/or county in Colorado).
3. The overall sentiment of the article: "positive", "neutral", or "negative".
4. The best-guess Colorado county this article is primarily about.

Respond with JSON only, no other text:
{{"issues": ["Topic 1", "Topic 2"], "regions": [{{"name": "City Name", "type": "municipality"}}], "sentiment": "neutral", "county": "County Name"}}
"""
```

**Step 3: Store sentiment and county in extract_issues_for_article()**

After parsing the JSON result, add:
```python
    # Store sentiment
    sentiment = result.get("sentiment", "neutral")
    if sentiment in ("positive", "neutral", "negative"):
        conn.execute(
            "UPDATE articles SET sentiment = ? WHERE id = ?",
            (sentiment, article_id),
        )

    # Store county on regions
    county = result.get("county", "")
    if county:
        conn.execute(
            "UPDATE article_regions SET county = ? WHERE article_id = ? AND county IS NULL",
            (county, article_id),
        )
```

**Step 4: Update tests**

In `code/tests/test_extract_issues.py`, update the mock Haiku response to include `"sentiment": "negative"` and `"county": "Denver County"`. Add assertions:
```python
    sentiment = conn.execute("SELECT sentiment FROM articles WHERE id = ?", (article_id,)).fetchone()
    assert sentiment[0] == "negative"
```

In `code/tests/test_news_schema.py`, add a test:
```python
def test_articles_table_has_sentiment_column(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()}
    assert "sentiment" in cols
```

**Step 5: Run tests**

Run: `cd code && python -m pytest tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add code/db.py code/news/extract_issues.py code/tests/
git commit -m "feat: add sentiment and county extraction to Haiku prompt"
```

---

### Task 4: Re-run Extraction on All Articles

**Files:**
- Modify: `code/run_news.py` (add `--reextract` CLI flag)
- Modify: `code/news/pipeline.py` (add reextraction function)

**Context:** All existing articles need re-extraction to populate the new sentiment and county fields. Articles with empty bodies (now scraped) also need first-time extraction.

**Step 1: Add reextraction function to pipeline.py**

```python
def reextract_all(conn: sqlite3.Connection) -> None:
    """Re-run extraction on all articles to populate sentiment and county."""
    # Clear existing extractions so they get re-processed
    conn.execute("DELETE FROM article_issues")
    conn.execute("DELETE FROM article_regions")
    conn.execute("UPDATE articles SET sentiment = NULL")
    conn.commit()
    log.info("Cleared existing extractions, re-processing all articles")

    rows = conn.execute("SELECT id FROM articles").fetchall()
    log.info("Re-extracting %d articles", len(rows))
    for i, (article_id,) in enumerate(rows):
        try:
            extract_issues_for_article(conn, article_id)
        except Exception as e:
            log.error("Failed to re-extract article %d: %s", article_id, e)
        if (i + 1) % 50 == 0:
            log.info("Progress: %d / %d", i + 1, len(rows))
```

**Step 2: Add CLI flag to run_news.py**

```python
import sys

def main():
    reextract = "--reextract" in sys.argv
    conn = get_connection()
    try:
        if reextract:
            from news.pipeline import reextract_all
            reextract_all(conn)
        else:
            run_news_pipeline(conn)
    finally:
        conn.close()
    run_dashboard_export()
```

**Step 3: Commit (no test needed — orchestration only)**

```bash
git add code/run_news.py code/news/pipeline.py
git commit -m "feat: add --reextract flag for full re-extraction with sentiment/county"
```

**Step 4: Run the re-extraction**

Run: `cd code && python run_news.py --reextract`
Expected: All articles re-processed with sentiment and county fields populated. Monitor for errors.

---

### Task 5: Article Deduplication

**Files:**
- Create: `code/news/dedup.py`
- Modify: `code/db.py` (add `article_duplicates` table)
- Modify: `code/news/pipeline.py` (add dedup step after ingestion)
- Test: `code/tests/test_dedup.py`

**Context:** Articles about the same story from multiple sources should be grouped. Uses normalized title token overlap (>80% match = duplicate).

**Step 1: Add schema to db.py**

```python
_SCHEMA_ARTICLE_DUPLICATES = """CREATE TABLE IF NOT EXISTS article_duplicates (
    article_id INTEGER REFERENCES articles(id),
    duplicate_of_id INTEGER REFERENCES articles(id),
    similarity REAL,
    PRIMARY KEY (article_id, duplicate_of_id)
);"""
```

Add to `_NEWS_SCHEMAS` list and to the migration section in `get_connection()`.

**Step 2: Write the failing test**

```python
# code/tests/test_dedup.py
"""Tests for article deduplication."""
import sqlite3
import pytest

from news.dedup import normalize_title, title_similarity, find_duplicates


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
        body TEXT, author TEXT, published_at TEXT,
        source TEXT NOT NULL, sentiment TEXT,
        ingested_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE article_duplicates (
        article_id INTEGER, duplicate_of_id INTEGER,
        similarity REAL, PRIMARY KEY (article_id, duplicate_of_id)
    )""")
    c.commit()
    return c


def test_normalize_title():
    assert normalize_title("Colorado's Budget Crisis — Report") == "colorado budget crisis report"


def test_title_similarity_identical():
    assert title_similarity("colorado budget crisis", "colorado budget crisis") == 1.0


def test_title_similarity_different():
    assert title_similarity("colorado budget crisis", "denver weather forecast") < 0.3


def test_title_similarity_partial():
    score = title_similarity(
        "colorado faces major budget shortfall this year",
        "colorado budget shortfall threatens school funding",
    )
    assert 0.3 < score < 0.9


def test_find_duplicates_links_similar_articles(conn):
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://a.com/1", "Colorado faces major budget shortfall this year", "denver_post"))
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://b.com/2", "Colorado budget shortfall threatens school funding", "colorado_sun"))
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://c.com/3", "Denver Broncos win Super Bowl", "denver_post"))
    conn.commit()
    count = find_duplicates(conn)
    # Articles 1 and 2 are similar; article 3 is different
    dupes = conn.execute("SELECT * FROM article_duplicates").fetchall()
    assert len(dupes) >= 1
    assert count >= 1


def test_find_duplicates_no_self_duplication(conn):
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://a.com/1", "Some article title", "denver_post"))
    conn.commit()
    find_duplicates(conn)
    dupes = conn.execute("SELECT * FROM article_duplicates").fetchall()
    assert len(dupes) == 0
```

**Step 3: Run test to verify it fails**

Run: `cd code && python -m pytest tests/test_dedup.py -v`
Expected: FAIL — module not found

**Step 4: Write implementation**

```python
# code/news/dedup.py
"""Article deduplication using title similarity."""

import logging
import re
import sqlite3

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.5


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", text).strip()


def title_similarity(a: str, b: str) -> float:
    """Token overlap similarity (Jaccard index) on normalized titles."""
    tokens_a = set(normalize_title(a).split())
    tokens_b = set(normalize_title(b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def find_duplicates(conn: sqlite3.Connection) -> int:
    """Compare articles pairwise by title similarity, link duplicates. Returns count."""
    rows = conn.execute("SELECT id, title, source FROM articles ORDER BY id").fetchall()
    existing = {
        (r[0], r[1])
        for r in conn.execute("SELECT article_id, duplicate_of_id FROM article_duplicates").fetchall()
    }

    count = 0
    for i, (id_a, title_a, source_a) in enumerate(rows):
        for id_b, title_b, source_b in rows[i + 1:]:
            if source_a == source_b:
                continue  # only cross-source duplicates
            if (id_a, id_b) in existing or (id_b, id_a) in existing:
                continue
            sim = title_similarity(title_a, title_b)
            if sim >= SIMILARITY_THRESHOLD:
                # Earlier article is the "original"
                conn.execute(
                    "INSERT OR IGNORE INTO article_duplicates (article_id, duplicate_of_id, similarity) "
                    "VALUES (?, ?, ?)",
                    (id_b, id_a, round(sim, 3)),
                )
                count += 1

    conn.commit()
    log.info("Found %d duplicate pairs", count)
    return count
```

**Step 5: Wire into pipeline.py**

After scraping, before extraction:
```python
from news.dedup import find_duplicates

    # Phase 1.7: Find cross-source duplicates
    find_duplicates(conn)
```

**Step 6: Run tests**

Run: `cd code && python -m pytest tests/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add code/news/dedup.py code/tests/test_dedup.py code/db.py code/news/pipeline.py
git commit -m "feat: add article deduplication by title similarity"
```

---

### Task 6: County Choropleth Map

**Files:**
- Create: `dashboard/data/co-counties.json` (TopoJSON — download from public source)
- Modify: `dashboard/index.html` (replace region cards with map, add map rendering)
- Modify: `code/news/generate_dashboard_data.py` (add county-level data to JSON)

**Context:** Replace the 4 region cards with an interactive county choropleth. Each of Colorado's 64 counties colored by dominant issue. Click to filter. Uses the `county` field from extraction.

**Step 1: Download Colorado counties TopoJSON**

Run:
```bash
curl -o dashboard/data/co-counties.json "https://raw.githubusercontent.com/deldersveld/topojson/master/countries/us-states/CO-08-colorado-counties.json"
```

If that URL is unavailable, generate from Census TIGER/Line shapefiles using `topojson` CLI, or use any public Colorado county TopoJSON.

**Step 2: Update generate_dashboard_data.py**

Add a new section to `generate_dashboard_json()` that aggregates data by county:

```python
    # County-level data for choropleth
    county_rows = conn.execute(
        "SELECT ar.county, i.name, COUNT(*) as cnt "
        "FROM article_regions ar "
        "JOIN article_issues ai ON ar.article_id = ai.article_id "
        "JOIN issues i ON ai.issue_id = i.id "
        "WHERE ar.county IS NOT NULL AND ar.county != '' "
        "GROUP BY ar.county, i.name "
        "ORDER BY ar.county, cnt DESC"
    ).fetchall()

    counties = {}
    for county, issue, cnt in county_rows:
        if county not in counties:
            counties[county] = {"total": 0, "top_issue": issue, "issues": {}}
        counties[county]["total"] += cnt
        counties[county]["issues"][issue] = cnt

    county_data = [
        {
            "county": name,
            "total_articles": data["total"],
            "top_issue": data["top_issue"],
            "issues": data["issues"],
        }
        for name, data in sorted(counties.items())
    ]
```

Add `"county_data": county_data` to the returned dict.

Also add county and sentiment to each article in `recent_articles`:
```python
    # In the article loop, after locations:
    county_name = conn.execute(
        "SELECT county FROM article_regions WHERE article_id = ? AND county IS NOT NULL LIMIT 1",
        (article_id,),
    ).fetchone()

    recent_articles.append({
        ...existing fields...,
        "county": county_name[0] if county_name else None,
        "sentiment": conn.execute(
            "SELECT sentiment FROM articles WHERE id = ?", (article_id,)
        ).fetchone()[0],
    })
```

**Step 3: Add map to dashboard/index.html**

Replace the `.region-row` div with a map container:
```html
<div id="map-container" style="width:100%; height:320px; position:relative;"></div>
```

Add D3 geo rendering in JS:
```javascript
// ── Map ────────────────────────────────────────
const ISSUE_COLORS = {
    'Economy/Jobs': '#4C6971', 'Public Safety': '#C0392B',
    'Recreation/Tourism': '#27AE60', 'Education': '#8E44AD',
    'Transportation': '#E67E22', 'Healthcare': '#2980B9',
    'Housing': '#D4AC0D', 'Environment': '#1ABC9C',
    'Taxes/Budget': '#7F8C8D', 'Infrastructure': '#E74C3C',
    'Energy': '#F39C12', 'Agriculture': '#2ECC71',
    'Immigration': '#9B59B6', 'Gun Policy': '#E91E63',
    'Water Rights': '#00BCD4',
};
const DEFAULT_COUNTY_COLOR = '#E8E5E1';

let mapData = null;
let activeCounty = null;

async function loadMap() {
    const topo = await d3.json('data/co-counties.json');
    mapData = topo;
    renderMap();
}

function renderMap() {
    if (!mapData || !dashData) return;
    const container = document.getElementById('map-container');
    container.innerHTML = '';

    const width = container.clientWidth;
    const height = 320;
    const svg = d3.select(container).append('svg')
        .attr('width', width).attr('height', height);

    const objectKey = Object.keys(mapData.objects)[0];
    const geojson = topojson.feature(mapData, mapData.objects[objectKey]);
    const projection = d3.geoMercator().fitSize([width - 20, height - 20], geojson);
    const path = d3.geoPath().projection(projection);

    // Build county lookup from dashData
    const countyLookup = {};
    (dashData.county_data || []).forEach(c => {
        countyLookup[c.county.toUpperCase()] = c;
    });

    svg.selectAll('path')
        .data(geojson.features)
        .join('path')
        .attr('d', path)
        .attr('fill', d => {
            const name = (d.properties.NAME || '').toUpperCase();
            const data = countyLookup[name + ' COUNTY'] || countyLookup[name];
            if (data && data.top_issue) {
                return ISSUE_COLORS[data.top_issue] || '#4C6971';
            }
            return DEFAULT_COUNTY_COLOR;
        })
        .attr('stroke', '#fff')
        .attr('stroke-width', 0.5)
        .attr('cursor', 'pointer')
        .on('click', (event, d) => {
            const name = d.properties.NAME || '';
            activeCounty = (activeCounty === name) ? null : name;
            renderAll();
        })
        .append('title')
        .text(d => {
            const name = (d.properties.NAME || '').toUpperCase();
            const data = countyLookup[name + ' COUNTY'] || countyLookup[name];
            if (data) return `${d.properties.NAME}: ${data.top_issue} (${data.total_articles} articles)`;
            return d.properties.NAME + ': No coverage';
        });
}
```

Add `<script src="https://unpkg.com/topojson-client@3"></script>` to the `<head>`.

Update filtering functions to respect `activeCounty`. Update `renderAll()` to call `renderMap()`.

**Step 4: Test manually**

Run: preview the dashboard and verify the map renders, counties are colored, click filtering works.

**Step 5: Commit**

```bash
git add dashboard/ code/news/generate_dashboard_data.py
git commit -m "feat: add county choropleth map to dashboard"
```

---

### Task 7: Trend Lines

**Files:**
- Modify: `dashboard/index.html` (add trend chart below bar chart)
- Modify: `code/news/generate_dashboard_data.py` (add weekly time series data)

**Context:** Small multi-line chart showing top 5 issues over 4 weeks. Grouped by ISO week.

**Step 1: Add time series to generate_dashboard_data.py**

```python
    # Weekly issue trends (last 8 weeks)
    # We'll compute this client-side from article dates + issues
    # No additional server data needed — articles already have published_at and issues
```

Actually, compute this client-side from the existing article data — each article already has `published_at` and `issues`. No backend change needed.

**Step 2: Add trend chart to dashboard/index.html**

Below `#chart-container`, add:
```html
<div class="section-header" style="margin-top:20px;">
    <span>Trends</span>
</div>
<div class="chart-card" id="trend-container" style="height:180px;"></div>
```

Add JS function:
```javascript
function renderTrends() {
    const container = document.getElementById('trend-container');
    container.innerHTML = '';

    // Get all articles (no time filter for trends — always show 30d)
    const now = new Date();
    const cutoff = new Date(now);
    cutoff.setDate(cutoff.getDate() - 30);

    const articles = dashData.recent_articles.filter(a => {
        if (activeSource !== 'all' && a.source !== activeSource) return false;
        const d = parseDate(a.published_at);
        return d && d >= cutoff;
    });

    // Group by week + issue
    const weekBuckets = {};
    articles.forEach(a => {
        const d = parseDate(a.published_at);
        if (!d) return;
        // ISO week start (Monday)
        const weekStart = new Date(d);
        weekStart.setDate(weekStart.getDate() - weekStart.getDay() + 1);
        const key = weekStart.toISOString().slice(0, 10);
        a.issues.forEach(issue => {
            if (!weekBuckets[key]) weekBuckets[key] = {};
            weekBuckets[key][issue] = (weekBuckets[key][issue] || 0) + 1;
        });
    });

    const weeks = Object.keys(weekBuckets).sort();
    if (weeks.length < 2) {
        container.innerHTML = '<div class="empty-state">Need 2+ weeks of data for trends</div>';
        return;
    }

    // Top 5 issues by total count
    const totals = {};
    articles.forEach(a => a.issues.forEach(i => { totals[i] = (totals[i] || 0) + 1; }));
    const topIssues = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 5).map(e => e[0]);

    // Build series
    const series = topIssues.map(issue => ({
        issue,
        values: weeks.map(w => ({ week: w, count: (weekBuckets[w] || {})[issue] || 0 })),
    }));

    // D3 line chart
    const margin = { top: 10, right: 100, bottom: 30, left: 30 };
    const width = container.clientWidth - margin.left - margin.right;
    const height = 150 - margin.top - margin.bottom;

    const svg = d3.select(container).append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom)
        .append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3.scalePoint().domain(weeks).range([0, width]);
    const y = d3.scaleLinear()
        .domain([0, d3.max(series, s => d3.max(s.values, v => v.count)) || 1])
        .range([height, 0]);

    const color = d3.scaleOrdinal()
        .domain(topIssues)
        .range(['#4C6971', '#C0392B', '#27AE60', '#8E44AD', '#E67E22']);

    // Axes
    svg.append('g').attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(x).tickFormat(d => {
            const dt = new Date(d);
            return (dt.getMonth() + 1) + '/' + dt.getDate();
        }))
        .selectAll('text').style('font-size', '10px');

    svg.append('g').call(d3.axisLeft(y).ticks(4)).selectAll('text').style('font-size', '10px');

    // Lines
    const line = d3.line().x(d => x(d.week)).y(d => y(d.count)).curve(d3.curveMonotoneX);

    series.forEach(s => {
        const opacity = (activeIssue && activeIssue !== s.issue) ? 0.15 : 1;
        svg.append('path')
            .datum(s.values)
            .attr('fill', 'none')
            .attr('stroke', color(s.issue))
            .attr('stroke-width', activeIssue === s.issue ? 3 : 1.5)
            .attr('opacity', opacity)
            .attr('d', line);

        // Label at end
        const last = s.values[s.values.length - 1];
        svg.append('text')
            .attr('x', width + 5)
            .attr('y', y(last.count))
            .attr('font-size', '10px')
            .attr('fill', color(s.issue))
            .attr('opacity', opacity)
            .attr('dominant-baseline', 'middle')
            .text(s.issue.length > 15 ? s.issue.slice(0, 13) + '…' : s.issue);
    });
}
```

Call `renderTrends()` from `renderAll()`.

**Step 3: Test manually in preview**

**Step 4: Commit**

```bash
git add dashboard/index.html
git commit -m "feat: add issue trend lines to dashboard"
```

---

### Task 8: Sentiment Indicators

**Files:**
- Modify: `dashboard/index.html` (sentiment dots in feed, stacked bars)

**Context:** Green/gray/red dots in article feed. Bar chart shows sentiment breakdown on hover.

**Step 1: Add sentiment dot CSS**

```css
.sentiment-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    margin-right: 4px;
    vertical-align: middle;
}
.sentiment-dot--positive { background: #27AE60; }
.sentiment-dot--neutral  { background: #BDC3C7; }
.sentiment-dot--negative { background: #C0392B; }
```

**Step 2: Add sentiment dot to feed items**

In `renderFeed()`, before the date span:
```javascript
const sentimentDot = a.sentiment
    ? `<span class="sentiment-dot sentiment-dot--${a.sentiment}" title="${a.sentiment}"></span>`
    : '';
```

Include in feed-meta: `${sentimentDot}<span class="feed-date">${dateStr}</span>`

**Step 3: Add sentiment breakdown to bar chart hover**

In `renderBarChart()`, compute sentiment counts per issue from filtered articles, and add a tooltip on hover showing "Positive: X, Neutral: Y, Negative: Z".

Use the `.bar-fill` element to show stacked colors:
```javascript
// Inside the bar rendering, replace single fill with stacked:
const sentCounts = { positive: 0, neutral: 0, negative: 0 };
filtered.forEach(a => {
    if (a.issues.includes(issue.name) && a.sentiment) {
        sentCounts[a.sentiment]++;
    }
});
const total = sentCounts.positive + sentCounts.neutral + sentCounts.negative || 1;
row.querySelector('.bar-track').innerHTML = `
    <span class="bar-fill" style="width:${(sentCounts.positive/total*100*issue.count/maxCount)}%; background:#27AE60;"></span>
    <span class="bar-fill" style="width:${(sentCounts.neutral/total*100*issue.count/maxCount)}%; background:#BDC3C7; position:absolute; left:${...}"></span>
    ...
`;
```

**Note:** The stacked bar approach is tricky with absolute positioning. A simpler alternative: keep the single teal bar but add a tooltip on hover showing the sentiment breakdown. Implement whichever is cleaner.

**Step 4: Commit**

```bash
git add dashboard/index.html
git commit -m "feat: add sentiment indicators to dashboard feed and bar chart"
```

---

### Task 9: Issue Co-occurrence Matrix

**Files:**
- Modify: `dashboard/index.html` (add toggle + heatmap)
- Modify: `code/news/generate_dashboard_data.py` (add co-occurrence data)

**Context:** Heatmap showing which issues appear together. Toggle below bar chart.

**Step 1: Compute co-occurrence in generate_dashboard_data.py**

```python
    # Issue co-occurrence
    cooccurrence = {}
    article_issue_map = {}
    for row in conn.execute(
        "SELECT ai.article_id, i.name FROM article_issues ai "
        "JOIN issues i ON ai.issue_id = i.id"
    ).fetchall():
        article_issue_map.setdefault(row[0], []).append(row[1])

    for issues_list in article_issue_map.values():
        for i, a in enumerate(issues_list):
            for b in issues_list[i + 1:]:
                pair = tuple(sorted([a, b]))
                cooccurrence[pair] = cooccurrence.get(pair, 0) + 1

    cooccurrence_data = [
        {"issue_a": pair[0], "issue_b": pair[1], "count": count}
        for pair, count in sorted(cooccurrence.items(), key=lambda x: -x[1])
    ]
```

Add `"cooccurrence": cooccurrence_data` to the returned dict.

**Step 2: Add heatmap toggle to dashboard**

Below the bar chart:
```html
<button id="toggle-cooccurrence" style="margin-top:12px; font-size:12px; cursor:pointer; background:none; border:1px solid #ccc; padding:4px 10px; border-radius:4px;">
    Show Co-occurrence
</button>
<div id="cooccurrence-container" class="chart-card" style="display:none; margin-top:12px;"></div>
```

Render as a D3 matrix heatmap or simple HTML table with colored cells.

**Step 3: Commit**

```bash
git add dashboard/index.html code/news/generate_dashboard_data.py
git commit -m "feat: add issue co-occurrence matrix to dashboard"
```

---

### Task 10: Article Deduplication Display

**Files:**
- Modify: `code/news/generate_dashboard_data.py` (add duplicate info to articles)
- Modify: `dashboard/index.html` (group duplicates in feed)

**Context:** Show "Also covered by: Source A, Source B" badge on duplicate articles.

**Step 1: Add duplicate info to JSON export**

In `generate_dashboard_json()`, after building `recent_articles`, annotate duplicates:

```python
    # Add duplicate info
    for article in recent_articles:
        article_id_row = conn.execute(
            "SELECT id FROM articles WHERE url = ?", (article["url"],)
        ).fetchone()
        if not article_id_row:
            article["also_covered_by"] = []
            continue
        aid = article_id_row[0]
        dups = conn.execute(
            "SELECT a.source FROM article_duplicates ad "
            "JOIN articles a ON a.id = ad.article_id "
            "WHERE ad.duplicate_of_id = ? "
            "UNION "
            "SELECT a.source FROM article_duplicates ad "
            "JOIN articles a ON a.id = ad.duplicate_of_id "
            "WHERE ad.article_id = ?",
            (aid, aid),
        ).fetchall()
        article["also_covered_by"] = [SOURCE_TO_REGION.get(r[0], r[0]) for r in dups if r[0] != article["source"]]
```

**Step 2: Show badge in dashboard feed**

In `renderFeed()`, after issue pills:
```javascript
const alsoCovered = (a.also_covered_by || []);
const coverageBadge = alsoCovered.length > 0
    ? `<span class="coverage-badge">Also: ${alsoCovered.map(s => esc(SOURCE_NAMES[s] || s)).join(', ')}</span>`
    : '';
```

Add CSS:
```css
.coverage-badge {
    font-size: 10px;
    color: #888;
    font-style: italic;
    margin-left: 4px;
}
```

**Step 3: Commit**

```bash
git add dashboard/index.html code/news/generate_dashboard_data.py
git commit -m "feat: show article duplication badges in feed"
```

---

### Task 11: Officials Drawer on County Click

**Files:**
- Modify: `code/news/generate_dashboard_data.py` (add officials-by-county data)
- Modify: `dashboard/index.html` (add drawer panel, wire to map click)

**Context:** When clicking a county on the map, show the state legislators and county officials who represent that area. Data comes from the existing `officials` table.

**Step 1: Add officials-by-county to JSON export**

```python
    # Officials by county
    officials_rows = conn.execute(
        "SELECT name, title, office_level, party, county, municipality, email, website "
        "FROM officials WHERE county IS NOT NULL AND county != '' "
        "ORDER BY county, office_level, name"
    ).fetchall()

    officials_by_county = {}
    for name, title, level, party, county, municipality, email, website in officials_rows:
        county_key = county.strip()
        if county_key not in officials_by_county:
            officials_by_county[county_key] = []
        officials_by_county[county_key].append({
            "name": name, "title": title, "level": level,
            "party": party, "email": email, "website": website,
        })
```

Add `"officials_by_county": officials_by_county` to the returned dict.

**Step 2: Add drawer HTML and CSS**

```html
<div id="officials-drawer" class="drawer" style="display:none;">
    <div class="drawer-header">
        <span id="drawer-county-name"></span>
        <button id="drawer-close" style="background:none; border:none; font-size:18px; cursor:pointer;">&times;</button>
    </div>
    <div id="drawer-content"></div>
</div>
```

CSS:
```css
.drawer {
    position: fixed; right: 0; top: 56px; bottom: 0;
    width: 360px; background: #fff;
    border-left: 1px solid #E8E5E1;
    box-shadow: -4px 0 12px rgba(0,0,0,0.08);
    z-index: 20; overflow-y: auto;
    padding: 20px;
    transition: transform 0.2s;
}
.drawer-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 16px;
    font-family: 'Oswald', sans-serif; font-weight: 600;
    font-size: 16px; text-transform: uppercase; letter-spacing: 1px;
}
.official-card {
    padding: 10px 0; border-bottom: 1px solid #f0f0f0;
}
.official-name { font-weight: 600; font-size: 14px; }
.official-title { font-size: 12px; color: #666; }
.official-party { font-size: 11px; color: #999; }
.official-contact { font-size: 11px; color: #4C6971; }
.official-contact a { color: #4C6971; text-decoration: none; }
.official-contact a:hover { text-decoration: underline; }
```

**Step 3: Wire map click to drawer**

In the map click handler:
```javascript
.on('click', (event, d) => {
    const name = d.properties.NAME || '';
    activeCounty = (activeCounty === name) ? null : name;
    if (activeCounty) {
        showOfficialsDrawer(activeCounty);
    } else {
        hideOfficialsDrawer();
    }
    renderAll();
})
```

```javascript
function showOfficialsDrawer(countyName) {
    const drawer = document.getElementById('officials-drawer');
    const content = document.getElementById('drawer-content');
    document.getElementById('drawer-county-name').textContent = countyName + ' County';

    const officials = (dashData.officials_by_county || {})[countyName] ||
                      (dashData.officials_by_county || {})[countyName + ' County'] || [];

    if (officials.length === 0) {
        content.innerHTML = '<div class="empty-state">No officials data for this county</div>';
    } else {
        content.innerHTML = officials.map(o => `
            <div class="official-card">
                <div class="official-name">${esc(o.name)}</div>
                <div class="official-title">${esc(o.title || '')}</div>
                <div class="official-party">${esc(o.party || '')}</div>
                ${o.email ? `<div class="official-contact"><a href="mailto:${esc(o.email)}">${esc(o.email)}</a></div>` : ''}
                ${o.website ? `<div class="official-contact"><a href="${esc(o.website)}" target="_blank">Website</a></div>` : ''}
            </div>
        `).join('');
    }

    drawer.style.display = 'block';
}

function hideOfficialsDrawer() {
    document.getElementById('officials-drawer').style.display = 'none';
}

document.getElementById('drawer-close').addEventListener('click', () => {
    activeCounty = null;
    hideOfficialsDrawer();
    renderAll();
});
```

**Step 4: Test manually — click a county, verify drawer shows officials**

**Step 5: Commit**

```bash
git add dashboard/index.html code/news/generate_dashboard_data.py
git commit -m "feat: add officials drawer on county map click"
```

---

### Task 12: Final Integration Run + Push

**Step 1: Run the full pipeline with new sources and scraper**

```bash
cd code && python run_news.py
```

Verify: new sources ingested, bodies scraped, issues extracted with sentiment + county.

**Step 2: Re-extract to populate sentiment and county for all articles**

```bash
cd code && python run_news.py --reextract
```

**Step 3: Regenerate dashboard data**

This happens automatically at the end of run_news.py.

**Step 4: Run all tests**

```bash
cd code && python -m pytest tests/ -v
```

Expected: All PASS

**Step 5: Preview the dashboard**

Verify: map renders with county colors, trend lines show, sentiment dots visible, co-occurrence toggle works, officials drawer opens on county click.

**Step 6: Push to GitHub**

```bash
git push origin fresh-main:main
```

**Step 7: Copy all files to main Officials directory**

```bash
cp -R code/ "/Users/jacksaltzman/Library/Mobile Documents/com~apple~CloudDocs/Accountable/Officials/code/"
cp -R dashboard/ "/Users/jacksaltzman/Library/Mobile Documents/com~apple~CloudDocs/Accountable/Officials/dashboard/"
```
