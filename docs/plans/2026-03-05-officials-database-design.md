# Design: Colorado Elected Officials Database (Pilot)

**Date:** 2026-03-05
**Status:** Approved

## Goal

Build a comprehensive database of every sub-federal elected official in Colorado — state legislators, statewide officers, county officials, municipal officials, and school board members — plus key staff and social media handles. The eventual purpose is tweet analysis to understand local issues.

This is a pilot for a single state. If successful, the pipeline scales state-by-state to all 50 states.

## Approach

**Free-first pipeline (Approach A):** Use the free Open States API for state legislators, scrape Colorado government directories for local officials, and enrich with social media handles via automated search. Paid data sources (Ballotpedia, BallotReady) are available as fallbacks if scraping proves insufficient.

## Phases

### Phase 1 — State Legislators (Open States API)

Pull all 100 Colorado state legislators (35 Senate + 65 House) from the Open States API v3. This gives structured data: name, party, district, contact info, and partial social media handles.

- **Source:** Open States API (free, API key in existing `Environment.txt`)
- **Coverage:** ~100% of state legislators
- **Data:** Name, party, district, chamber, contact info, social links (where available)

### Phase 2 — Statewide & Local Officials (Web Scraping)

Scrape Colorado government websites for officials at all other levels.

| Level | Source | Estimated Officials | Expected Coverage |
|-------|--------|-------------------|-------------------|
| Statewide | Governor's office + individual officer sites | ~8 | ~100% |
| County | Colorado Counties Inc. (CCI) directory + county websites | ~400 | ~80-90% |
| Municipal | Colorado Municipal League (CML) directory + top 20 city sites | ~2,000 | ~60-70% |
| School Board | CO School Boards Association (CASB) + district sites | ~1,200 | ~50-60% |
| **Total** | | **~3,700** | **~65-75%** |

Statewide officials (~8 people) are hardcoded initially — not worth building a scraper for a stable, tiny set.

Gaps will concentrate in small rural municipalities and school districts. Filled incrementally.

### Phase 3 — Social Media Enrichment

Find Twitter/X handles for each official using a tiered approach:

1. **Open States data** — handles already on file (state legislators)
2. **Official website scraping** — look for twitter.com/x.com links on bio pages
3. **X profile search** — search for `"{name}" {title} Colorado`
4. **Google search fallback** — `site:twitter.com OR site:x.com "{name}" "{title}" Colorado`

Confidence scoring:

| Source | Confidence | `twitter_verified` |
|--------|-----------|-------------------|
| Open States / official website link | High | `true` |
| X search — bio matches title + location | Medium | `true` |
| X search — name match only | Low | `false` (manual review) |
| Not found | — | `null` |

Priority: state legislators + statewide + county officials (~500 people) first. Municipal and school board members are lower priority for handle discovery.

### Phase 4 — Tweet Collection & Analysis (Future)

Not built in this phase. Requires Twitter/X API access (~$200/mo for Basic tier or ~$180/mo for third-party scraper). Will be designed separately once the officials + handles database is validated.

## Data Model

### Officials Table — one row per official

| Column | Type | Example |
|--------|------|---------|
| `id` | str | `CO-SL-001` |
| `name` | str | `Julie McCluskie` |
| `first_name` | str | `Julie` |
| `last_name` | str | `McCluskie` |
| `title` | str | `State Representative` |
| `office_level` | str | `state_legislature` |
| `office_branch` | str | `legislative` |
| `body` | str | `House` |
| `district` | str | `HD-13` |
| `party` | str | `Democratic` |
| `state` | str | `CO` |
| `county` | str | nullable — for county/local officials |
| `municipality` | str | nullable — for city officials |
| `email` | str | `julie.mccluskie@state.co.us` |
| `phone` | str | `303-866-2909` |
| `website` | str | nullable |
| `twitter_handle` | str | nullable |
| `twitter_verified` | bool | `true` |
| `facebook_url` | str | nullable |
| `photo_url` | str | nullable |
| `source` | str | `openstates` |
| `source_id` | str | Open States person ID |
| `scraped_at` | datetime | `2026-03-05T12:00:00` |

### `office_level` values

- `statewide` — Governor, AG, Secretary of State, Treasurer, Lt. Governor
- `state_legislature` — State Senate & House
- `county` — Commissioners, clerks, sheriffs, assessors, coroners
- `municipal` — Mayors, city council members
- `school_board` — School board members

### Key Staff Table — linked by `official_id`

| Column | Type | Example |
|--------|------|---------|
| `id` | str | `CO-SL-001-S1` |
| `official_id` | str | `CO-SL-001` |
| `name` | str | `Jane Doe` |
| `role` | str | `Chief of Staff` |
| `email` | str | nullable |
| `twitter_handle` | str | nullable |
| `facebook_url` | str | nullable |
| `source` | str | `scrape_co_leg` |

### Storage

**SQLite** (`officials.db`) as primary store. CSV/XLSX exports generated from it.

## File Structure

```
Officials/
  code/
    pipeline.py                # Main entry point — orchestrates all phases
    open_states.py             # Phase 1: Open States API client
    scrapers/
      __init__.py
      statewide.py             # Governor, AG, SoS, Treasurer
      county.py                # County commissioners, clerks, sheriffs
      municipal.py             # Mayors, city councils
      school_board.py          # School board members
    enrich_social.py           # Phase 3: Twitter/X handle discovery
    export.py                  # CSV/XLSX export
    db.py                      # SQLite helpers (create tables, insert, query)
    requirements.txt
  data/
    officials.db               # SQLite database
  output/
    co_officials.csv
    co_officials.xlsx
    co_key_staff.csv
    co_officials_summary.md
  docs/plans/
    2026-03-05-officials-database-design.md
  Environment.txt              # OPENSTATES_API_KEY (existing)
```

## Tech Stack

- **Python 3.11+** (matching CC and YP projects)
- **requests** — Open States API calls
- **beautifulsoup4 + httpx** — web scraping
- **sqlite3** — built-in database
- **pandas + openpyxl** — CSV/XLSX export

## Output Deliverables

### Exports

- **`co_officials.csv` / `.xlsx`** — one row per official, all columns
- **`co_key_staff.csv` / `.xlsx`** — one row per staff member, linked by `official_id`
- **`co_officials_summary.md`** — methodology, coverage stats, gaps, party breakdown

### Summary Contents

- Total officials by level
- Coverage stats (found vs estimated per level)
- Social media coverage (% with Twitter handle, % verified)
- Top gaps (which counties/cities have missing data)
- Party breakdown by level

## Data Sources

| Source | Cost | Coverage | Used For |
|--------|------|----------|----------|
| Open States API v3 | Free | State legislators (all 50 states) | Phase 1 |
| Colorado Counties Inc. (CCI) | Free (public directory) | County officials | Phase 2 |
| Colorado Municipal League (CML) | Free (public directory) | Municipal officials | Phase 2 |
| CO School Boards Assoc. (CASB) | Free (public directory) | School board members | Phase 2 |
| Individual gov websites | Free | Gap-filling | Phase 2 |
| X/Twitter search | Free (web search) | Handle discovery | Phase 3 |
| Google search | Free | Handle discovery fallback | Phase 3 |

## Fallback Data Sources (if free approach has significant gaps)

| Source | Cost | Coverage |
|--------|------|----------|
| Ballotpedia CSV dump | ~$600 one-time | Comprehensive all-level officials |
| Cicero API | $0.003/lookup | Officials + social media by address |
| BallotReady API | Enterprise pricing | 200K+ officials with social links |

## Caveats

1. Local official coverage will be incomplete for small rural jurisdictions in the pilot
2. Social media handle matching is imperfect — low-confidence matches require manual review
3. Official data goes stale as elections happen — pipeline should be re-runnable
4. Key staff data is the hardest to find — most staff directories are poorly maintained
5. Municipal and school board data is the least standardized across Colorado
6. Open States social media fields are volunteer-contributed and incomplete
