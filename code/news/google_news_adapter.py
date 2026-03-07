"""Google News RSS ingestion adapter for Colorado news sources."""

import logging
import sqlite3
import time
from html import unescape
from re import sub as re_sub
from urllib.parse import quote_plus

import feedparser
from googlenewsdecoder import gnewsdecoder

log = logging.getLogger(__name__)

GOOGLE_NEWS_SOURCES: dict[str, str] = {
    "pueblo_chieftain": "site:chieftain.com",
    "gj_sentinel": "site:gjsentinel.com",
    "fort_collins_coloradoan": "site:coloradoan.com Colorado",
}

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def _strip_html(html: str) -> str:
    text = re_sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    return re_sub(r"\s+", " ", text).strip()


def _decode_google_url(url: str) -> str:
    """Decode a Google News redirect URL to the original article URL.

    If the URL starts with ``https://news.google.com/``, uses
    ``gnewsdecoder`` to resolve it. Falls back to the original URL on
    any error or for non-Google URLs.
    """
    if not url.startswith("https://news.google.com/"):
        return url
    try:
        result = gnewsdecoder(url)
        return result.get("decoded_url", url)
    except Exception:
        log.debug("Failed to decode Google News URL: %s", url, exc_info=True)
        return url


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
        url = _decode_google_url(entry.link)
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


def decode_existing_google_urls(conn: sqlite3.Connection) -> int:
    """Decode all existing Google News URLs in the articles table.

    Queries articles whose URL starts with ``https://news.google.com/``,
    decodes each one, and updates the row if the decoded URL differs.
    Sleeps 0.5 s between decodes to avoid rate-limiting.

    Returns the number of rows updated.
    """
    rows = conn.execute(
        "SELECT id, url FROM articles WHERE url LIKE 'https://news.google.com/%'"
    ).fetchall()

    updated = 0
    for article_id, url in rows:
        decoded = _decode_google_url(url)
        if decoded != url:
            conn.execute(
                "UPDATE articles SET url = ? WHERE id = ?",
                (decoded, article_id),
            )
            updated += 1
        time.sleep(0.5)

    conn.commit()
    log.info("Decoded %d existing Google News URLs out of %d", updated, len(rows))
    return updated
