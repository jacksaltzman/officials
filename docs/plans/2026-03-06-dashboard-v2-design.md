# Colorado Issues Dashboard v2 — Design

## Goal

Transform the current issues dashboard from a simple bar chart + article feed into a rich, multi-view analytical tool with a Colorado county map, trend analysis, sentiment layer, issue co-occurrence, article deduplication, and an officials bridge — all powered by a deeper data pipeline that scrapes full article bodies, pulls from 9 sources (up from 4), and deduplicates overlapping coverage.

## Architecture

Three layers, built in order:

1. **Data quality** — scraper, new sources, deduplication
2. **Extraction enhancements** — sentiment, county tagging in the same Haiku call
3. **Dashboard visualizations** — map, trends, sentiment, co-occurrence, dedup display, officials drawer

---

## Layer 1: Data Pipeline Upgrades

### Article body scraping

New module `code/news/scraper.py`. When an article's body is short (<200 chars — i.e. title-only Google News articles), follow the URL through redirects to the actual newspaper page, extract main content with `readability-lxml` (Python port of Mozilla Readability). Store the scraped body back to the `articles.body` column. Rate-limited to 1 req/sec with retry logic. Runs as a pipeline step between ingestion and issue extraction.

### 5 new sources (total: 9)

Add to `rss_adapter.py` and `google_news_adapter.py`:

| Source | Method | Region |
|--------|--------|--------|
| Colorado Sun | RSS | Statewide |
| CO Springs Gazette | Google News (`site:gazette.com`) | Pikes Peak |
| Fort Collins Coloradoan | Google News (`site:coloradoan.com`) | Northern |
| Steamboat Pilot | Google News (`site:steamboatpilot.com`) | Northwest |
| Summit Daily | Google News (`site:summitdaily.com`) | Mountain |

Existing sources unchanged: Denver Post (RSS, Front Range), Durango Herald (RSS, Southwest), Pueblo Chieftain (Google News, Southern), GJ Sentinel (Google News, Western Slope).

### Deduplication

After ingestion, compare new articles against existing ones using normalized title token overlap. Articles >80% similar linked via a new `article_duplicates` table (`article_id`, `duplicate_of_id`). Dashboard groups duplicates — shows earliest version with a "covered by N sources" badge.

---

## Layer 2: Extraction Enhancements

### Expanded Haiku prompt

Extend the current `{issues, regions}` response to also return:

- `"sentiment": "positive" | "neutral" | "negative"` — overall article tone
- `"county": "County Name"` — best-guess Colorado county for the choropleth map

New response format:
```json
{
  "issues": ["Topic 1", "Topic 2"],
  "regions": [{"name": "City", "type": "municipality"}],
  "sentiment": "neutral",
  "county": "Denver County"
}
```

Same single Haiku call, ~50 more tokens in response. Zero extra API cost.

### DB schema changes

- Add `sentiment TEXT` column to `articles` table
- Add `county TEXT` column to `article_regions` table

### Re-extraction

Re-run extraction on:
1. Existing articles that currently have zero issue tags (~100 articles, previously title-only, now with scraped bodies)
2. All existing articles to add sentiment and county data (the old issue/region tags remain, we layer on the new fields)

---

## Layer 3: Dashboard Visualizations

### County choropleth map

Replaces the 4 region cards at the top of the dashboard. Uses a Colorado counties TopoJSON file (~50KB) rendered with D3 `geoPath`. Each of Colorado's 64 counties colored by dominant issue using a categorical palette. Hover shows county name, top issues, article count. Click a county to filter the issue chart and article feed. Counties with no coverage shown in light gray. Legend maps colors to issues.

### Trend lines

Below the bar chart. Small multi-line chart showing the top 5 issues over 30 days, grouped by week. X-axis = week, Y-axis = article count. Each line color-matched to its issue. Clicking an issue in the bar chart highlights its trend line.

### Sentiment indicators

- **Article feed:** Small colored dot next to each article — green (positive), gray (neutral), red (negative).
- **Bar chart:** Subtle stacked effect — each issue bar split by sentiment proportion. Hover shows breakdown: "Economy/Jobs: 20 positive, 12 neutral, 4 negative."

### Issue co-occurrence

Matrix heatmap accessible via a toggle below the issue chart. Shows which issues frequently appear together in the same article. Cells sized/colored by co-occurrence count. Helps answer "when we talk about Housing, what else comes up?"

### Article deduplication display

Duplicate articles collapsed into a single feed item with a "Also covered by: Denver Post, Colorado Sun" badge. Click to expand and see all versions.

### Officials bridge

When you click a county on the map, a sidebar/drawer shows the state legislators and county officials for that area (pulled from the existing `officials` table). Answers "who represents the people dealing with this issue?"

---

## Implementation Order

1. Article body scraper
2. 5 new sources
3. Expanded Haiku prompt (sentiment + county)
4. Re-run extraction on all articles
5. Deduplication
6. County choropleth map
7. Trend lines
8. Sentiment indicators in bar chart and feed
9. Co-occurrence matrix
10. Article dedup display in feed
11. Officials drawer on county click

## Tech Stack

- Python 3, SQLite, `readability-lxml`, `httpx`, `anthropic`
- D3.js v7, Colorado counties TopoJSON
- Static HTML/CSS/JS dashboard (no framework)
- Design language: DM Sans + Oswald, #FDFBF9 background, #4C6971 accent
