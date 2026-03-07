"""Content filtering to remove obituaries, photo galleries, and wire stories.

Runs after ingestion, before scraping. Deletes matching articles from DB
to save Haiku credits and keep the dashboard clean.
"""

import logging
import re
import sqlite3

log = logging.getLogger(__name__)

# Obituary: short title ending in "- Pueblo Chieftain" or "- Chieftain"
_OBITUARY_RE = re.compile(r"^.+\s-\s(?:Pueblo\s)?Chieftain$")

# Wire service indicators found in title or body
_WIRE_INDICATORS = ["(AP)", "(Reuters)", "(UPI)", "(AFP)"]


def is_obituary(title: str) -> bool:
    """Return True if *title* matches the obituary pattern.

    Obituaries from the Pueblo Chieftain typically have short personal-name
    titles ending with ``- Pueblo Chieftain`` or ``- Chieftain``.
    """
    return bool(_OBITUARY_RE.search(title))


def is_gallery(title: str) -> bool:
    """Return True if *title* looks like a photo gallery listing."""
    return title.startswith("Photos:")


def is_wire_story(title: str, body: str | None) -> bool:
    """Return True if the article appears to be a wire-service story.

    Checks both *title* and *body* for common wire-service tags such as
    ``(AP)``, ``(Reuters)``, etc.
    """
    text = title + (" " + body if body else "")
    return any(tag in text for tag in _WIRE_INDICATORS)


def filter_articles(conn: sqlite3.Connection) -> int:
    """Delete obituaries, photo galleries, and wire stories from the DB.

    Also cleans up associated rows in ``article_issues``,
    ``article_regions``, and ``article_duplicates`` junction tables.

    Returns the number of articles deleted.
    """
    rows = conn.execute("SELECT id, title, body FROM articles").fetchall()

    ids_to_delete: list[int] = []
    for article_id, title, body in rows:
        if is_obituary(title) or is_gallery(title) or is_wire_story(title, body):
            ids_to_delete.append(article_id)

    if not ids_to_delete:
        log.info("Filter: 0 articles removed")
        return 0

    placeholders = ",".join("?" for _ in ids_to_delete)

    # Clean junction tables first (FK order)
    conn.execute(
        f"DELETE FROM article_issues WHERE article_id IN ({placeholders})",
        ids_to_delete,
    )
    conn.execute(
        f"DELETE FROM article_regions WHERE article_id IN ({placeholders})",
        ids_to_delete,
    )
    conn.execute(
        f"DELETE FROM article_duplicates "
        f"WHERE article_id IN ({placeholders}) OR duplicate_of_id IN ({placeholders})",
        ids_to_delete + ids_to_delete,
    )

    # Delete the articles themselves
    conn.execute(
        f"DELETE FROM articles WHERE id IN ({placeholders})",
        ids_to_delete,
    )
    conn.commit()

    log.info("Filter: removed %d articles (obituaries/galleries/wire)", len(ids_to_delete))
    return len(ids_to_delete)
