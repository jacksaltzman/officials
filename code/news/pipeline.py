"""News pipeline orchestrator: ingest articles and extract issues."""

import logging
import sqlite3

from news.rss_adapter import fetch_rss_articles, RSS_SOURCES
from news.google_news_adapter import fetch_google_news_articles, GOOGLE_NEWS_SOURCES
from news.filter_articles import filter_articles
from news.extract_issues import extract_issues_for_article
from news.scraper import scrape_missing_bodies
from news.dedup import find_duplicates

log = logging.getLogger(__name__)


def run_news_pipeline(conn: sqlite3.Connection) -> None:
    """Run the full news ingestion and extraction pipeline."""
    log.info("=" * 60)
    log.info("Colorado News Pipeline")
    log.info("=" * 60)

    # Phase 1: Ingest articles
    total = 0
    for source in RSS_SOURCES:
        total += fetch_rss_articles(conn, source)

    for source in GOOGLE_NEWS_SOURCES:
        total += fetch_google_news_articles(conn, source)

    log.info("Ingested %d new articles total", total)

    # Phase 2: Filter out obituaries, photo galleries, wire stories
    filtered = filter_articles(conn)
    log.info("Filtered %d junk articles", filtered)

    # Phase 3: Scrape full bodies for title-only articles
    scraped = scrape_missing_bodies(conn)
    log.info("Scraped %d article bodies", scraped)

    # Phase 4: Find cross-source duplicates
    find_duplicates(conn)

    # Phase 5: Extract issues for unprocessed articles
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
