"""Generate dashboard_data.json for the issues dashboard visualization."""

import json
import logging
import sqlite3
from pathlib import Path

from db import BASE_DIR
from news.county_normalization import normalize_county

log = logging.getLogger(__name__)

DASHBOARD_DIR = BASE_DIR / "dashboard" / "data"

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
    "vail_daily": "Mountain",
    "post_independent": "Western Slope",
}


def generate_dashboard_json(conn: sqlite3.Connection) -> dict:
    """Build the dashboard data structure from the database."""
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
    for raw_county, issue, cnt in county_rows:
        county = normalize_county(raw_county)
        if not county:
            continue
        if county not in counties:
            counties[county] = {"total": 0, "top_issue": issue, "issues": {}}
        counties[county]["total"] += cnt
        counties[county]["issues"][issue] = counties[county]["issues"].get(issue, 0) + cnt

    county_data = [
        {
            "county": name,
            "total_articles": data["total"],
            "top_issue": data["top_issue"],
            "issues": data["issues"],
        }
        for name, data in sorted(counties.items())
    ]

    # All articles with issue tags (sorted client-side for correct date ordering)
    rows = conn.execute(
        "SELECT a.id, a.title, a.url, a.source, a.published_at, a.sentiment "
        "FROM articles a"
    ).fetchall()

    recent_articles = []
    for row in rows:
        article_id, title, url, source, published_at, sentiment = row
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

        county_row = conn.execute(
            "SELECT county FROM article_regions WHERE article_id = ? AND county IS NOT NULL LIMIT 1",
            (article_id,),
        ).fetchone()

        recent_articles.append({
            "title": title,
            "url": url,
            "source": source,
            "region": SOURCE_TO_REGION.get(source, "Unknown"),
            "published_at": published_at,
            "issues": issue_names,
            "locations": regions,
            "county": normalize_county(county_row[0]) if county_row else None,
            "sentiment": sentiment,
        })

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
        article["also_covered_by"] = [r[0] for r in dups if r[0] != article["source"]]

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

    return {
        "issues_by_count": issues_by_count,
        "articles_by_region": articles_by_region,
        "recent_articles": recent_articles,
        "county_data": county_data,
        "cooccurrence": cooccurrence_data,
        "officials_by_county": officials_by_county,
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
