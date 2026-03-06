# Colorado Issues Dashboard — Design Document

**Date:** 2026-03-06
**Goal:** Build a statewide issue landscape dashboard that answers "What are the top issues across Colorado and how do they vary by region?" by ingesting local newspaper coverage, extracting issue topics, and presenting them in a standalone visualization.

## Data Sources

Four Colorado newspapers covering distinct regions:

| Paper | Region | Ingestion Method | Data Richness |
|-------|--------|-----------------|---------------|
| Denver Post | Front Range metro | RSS (`/feed/`) | Full article body, categories, author |
| Durango Herald | Southwest / Four Corners | RSS (`/feeds/local-news`, `/feeds/news`, `/feeds/business`, `/feeds/education`) | Full article body, topic-specific feeds |
| Pueblo Chieftain | Southern Colorado | Google News (`site:chieftain.com`) | Headlines + snippets |
| Grand Junction Sentinel | Western Slope | Google News (`site:gjsentinel.com`) | Headlines + snippets |

## Architecture

```
RSS Feeds ──┐
             ├──▶ Ingestion ──▶ SQLite ──▶ LLM Extraction ──▶ SQLite ──▶ JSON Export ──▶ Dashboard
Google News ─┘     (common       (articles    (Claude Haiku      (issues,     (static        (HTML/D3.js)
                    schema)        table)       tags issues +     regions)      aggregation)
                                                geography)
```

## 1. Ingestion Layer

Two adapters producing a common article format:

### RSS Adapter (Denver Post, Durango Herald)

- Polls feeds on configurable schedule (default: every 6 hours)
- Denver Post: single `/feed/` endpoint with full `content:encoded` bodies
- Durango Herald: topic-specific feeds (`/feeds/local-news`, `/feeds/news`, `/feeds/business`, `/feeds/education`)
- Deduplicates by article URL (guid)
- Extracts: title, full text, author, publish date, source paper, categories (if provided by feed)

### Google News Adapter (Pueblo Chieftain, Grand Junction Sentinel)

- Searches Google News for `site:chieftain.com` and `site:gjsentinel.com`
- Returns headlines + snippets (1-2 sentences)
- Less content per article but sufficient for topic extraction from headlines
- Extracts: title, snippet, publish date, source paper, article URL

### Common Article Schema

```sql
CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    body TEXT,              -- full text (RSS) or snippet (Google News)
    author TEXT,
    published_at TEXT,
    source TEXT NOT NULL,   -- 'denver_post', 'durango_herald', 'pueblo_chieftain', 'gj_sentinel'
    ingested_at TEXT DEFAULT (datetime('now'))
);
```

## 2. Topic Extraction

LLM-based issue tagging using Claude Haiku on each article.

### Prompt Strategy

Each article is processed with a prompt that:
1. Extracts 1-3 issue topics from a starting taxonomy
2. Allows new topics if the article doesn't fit existing categories
3. Extracts specific geographic location (city and county)

### Starting Issue Taxonomy

Water Rights, Housing, Public Safety, Education, Transportation, Healthcare, Environment, Economy/Jobs, Agriculture, Energy, Taxes/Budget, Immigration, Gun Policy, Recreation/Tourism, Infrastructure

This list is a starting point, not a hard constraint. The LLM can surface new issues not on the list.

### Schema Additions

```sql
CREATE TABLE issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL
);

CREATE TABLE article_issues (
    article_id INTEGER REFERENCES articles(id),
    issue_id INTEGER REFERENCES issues(id),
    PRIMARY KEY (article_id, issue_id)
);

CREATE TABLE article_regions (
    article_id INTEGER REFERENCES articles(id),
    region_name TEXT NOT NULL,       -- e.g. 'Durango', 'La Plata County'
    region_type TEXT NOT NULL,       -- 'municipality' or 'county'
    PRIMARY KEY (article_id, region_name)
);
```

### Geographic Precision

The LLM tags geography at the city/county level (not just "which paper covered it") to support future map visualizations. A lookup table maps municipalities and counties to:
- The four paper coverage regions (for v1 dashboard aggregation)
- Lat/lng coordinates (for future choropleth or dot map)

The existing officials database already contains county data that can be reused.

### Cost Estimate

At ~50-100 articles/day across four papers, using Haiku for extraction: pennies per day.

## 3. Dashboard Visualization

Standalone static HTML + D3.js page, same tech stack as the officials tree app. Deployable to Vercel.

### Layout

**Top bar:** Title ("Colorado Issues"), time range selector (7 / 30 / 90 days), source filter (all papers or individual).

**Issue rankings (left, ~40% width):** Ranked horizontal bar chart of issue topics sorted by article count. Each bar labeled with issue name and count. Clicking an issue filters the regional breakdown and article feed.

**Regional breakdown (right, ~60% width):** Simple Colorado map divided into four paper coverage regions (Front Range, Southern, Southwest, Western Slope), color-coded by article intensity (more articles = darker shade). Below the map, a scrollable feed of recent article headlines grouped by region — title, source paper, date, issue tags as small pills. Clicking a headline opens the source article.

### Data Flow

Pipeline generates a `dashboard_data.json` with pre-aggregated counts by issue, region, and time period. No server required — fully static.

## 4. Future Extensions

- **Issue map:** Choropleth or dot map at county/municipality level using the precise geographic tags already being captured
- **Official linkage:** Connect articles to officials in the database when they're mentioned by name
- **Trend analysis:** Issue frequency over time — what's rising, what's fading
- **Additional papers:** Colorado Springs Gazette, Fort Collins Coloradoan, Colorado Sun for broader coverage
- **Full-text scraping:** Upgrade Google News sources to web scrapers with subscription authentication for richer extraction
