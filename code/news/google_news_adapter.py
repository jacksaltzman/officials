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
    text = re_sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re_sub(r"\s+", " ", text).strip()


def fetch_google_news_articles(conn: sqlite3.Connection, source_name: str) -> int:
    """Fetch articles from Google News RSS for a given source and store in DB.

    Returns the number of new articles inserted.
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

        before = conn.total_changes
        try:
            conn.execute(
                "INSERT OR IGNORE INTO articles (url, title, body, published_at, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (url, title, snippet, published, source_name),
            )
            if conn.total_changes > before:
                inserted += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    log.info("Inserted %d new articles from %s", inserted, source_name)
    return inserted
