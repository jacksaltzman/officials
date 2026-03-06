"""Generate dashboard_data.json for the issues dashboard visualization."""

import json
import logging
import sqlite3
from pathlib import Path

from db import BASE_DIR

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

    # All articles with issue tags (sorted client-side for correct date ordering)
    rows = conn.execute(
        "SELECT a.id, a.title, a.url, a.source, a.published_at "
        "FROM articles a"
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
