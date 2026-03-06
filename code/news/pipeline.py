"""News pipeline orchestrator: ingest articles and extract issues."""

import logging
import sqlite3

from news.rss_adapter import fetch_rss_articles
from news.google_news_adapter import fetch_google_news_articles
from news.extract_issues import extract_issues_for_article
from news.scraper import scrape_missing_bodies

log = logging.getLogger(__name__)


def run_news_pipeline(conn: sqlite3.Connection) -> None:
    """Run the full news ingestion and extraction pipeline."""
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

    # Phase 1.5: Scrape full bodies for title-only articles
    scraped = scrape_missing_bodies(conn)
    log.info("Scraped %d article bodies", scraped)

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
