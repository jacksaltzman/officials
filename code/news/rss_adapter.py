"""RSS feed ingestion adapter for Colorado news sources."""

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
    "colorado_sun": [
        "https://coloradosun.com/feed/",
    ],
}


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re_sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re_sub(r"\s+", " ", text).strip()


def _extract_body(entry) -> str:
    """Get the best available body text from a feedparser entry."""
    if hasattr(entry, "content") and entry.content:
        return _strip_html(entry.content[0].value)
    if hasattr(entry, "summary") and entry.summary:
        return _strip_html(entry.summary)
    return ""


def fetch_rss_articles(conn: sqlite3.Connection, source_name: str) -> int:
    """Fetch articles from RSS feeds for a given source and store in DB.

    Returns the number of new articles inserted.
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

            before = conn.total_changes
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO articles (url, title, body, author, published_at, source) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (url, title, body, author, published, source_name),
                )
                if conn.total_changes > before:
                    inserted += 1
            except sqlite3.IntegrityError:
                pass

        conn.commit()

    log.info("Inserted %d new articles from %s", inserted, source_name)
    return inserted
