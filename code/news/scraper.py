"""Article body scraper for title-only articles.

Google News RSS feeds provide only article titles (body <200 chars).
This module follows article URLs, extracts the main content using
readability + BeautifulSoup, and updates the database.
"""

import logging
import sqlite3
import time

import httpx
from readability import Document
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BODY_MIN_LENGTH = 200

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def scrape_article_body(url: str) -> str | None:
    """Fetch a URL and extract the main article text.

    Parameters
    ----------
    url : str
        The article URL to scrape.

    Returns
    -------
    str or None
        The extracted article text, or None if the request fails
        or no content can be extracted.
    """
    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=15,
            headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", url, exc)
        return None

    try:
        doc = Document(response.text)
        html_content = doc.summary()
        soup = BeautifulSoup(html_content, "lxml")
        text = soup.get_text(separator=" ", strip=True)
        return text if text else None
    except Exception as exc:
        log.warning("Failed to extract content from %s: %s", url, exc)
        return None


def scrape_missing_bodies(conn: sqlite3.Connection) -> int:
    """Scrape article bodies for rows with short or missing body text.

    Queries the articles table for rows where the body is NULL or
    shorter than BODY_MIN_LENGTH, fetches each URL, extracts the
    main content, and updates the database.  Rate-limited with a
    1-second delay between requests.

    Parameters
    ----------
    conn : sqlite3.Connection
        An open database connection.

    Returns
    -------
    int
        The number of articles successfully updated.
    """
    rows = conn.execute(
        "SELECT id, url FROM articles "
        "WHERE body IS NULL OR length(body) < ?",
        (BODY_MIN_LENGTH,),
    ).fetchall()

    if not rows:
        log.info("No articles need body scraping")
        return 0

    log.info("Found %d articles needing body scraping", len(rows))
    updated = 0

    for article_id, url in rows:
        body = scrape_article_body(url)
        if body:
            conn.execute(
                "UPDATE articles SET body = ? WHERE id = ?",
                (body, article_id),
            )
            conn.commit()
            updated += 1
            log.info("Scraped body for article %d: %s", article_id, url)
        else:
            log.warning("Could not scrape body for article %d: %s", article_id, url)

        time.sleep(1.0)

    log.info("Updated %d of %d articles", updated, len(rows))
    return updated
