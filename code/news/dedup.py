"""Article deduplication using title similarity."""

import logging
import re
import sqlite3

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.5


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", text).strip()


def title_similarity(a: str, b: str) -> float:
    """Token overlap similarity (Jaccard index) on normalized titles."""
    tokens_a = set(normalize_title(a).split())
    tokens_b = set(normalize_title(b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def find_duplicates(conn: sqlite3.Connection) -> int:
    """Compare articles pairwise by title similarity, link duplicates. Returns count."""
    rows = conn.execute("SELECT id, title, source FROM articles ORDER BY id").fetchall()
    existing = {
        (r[0], r[1])
        for r in conn.execute("SELECT article_id, duplicate_of_id FROM article_duplicates").fetchall()
    }

    count = 0
    for i, (id_a, title_a, source_a) in enumerate(rows):
        for id_b, title_b, source_b in rows[i + 1:]:
            if source_a == source_b:
                continue  # only cross-source duplicates
            if (id_a, id_b) in existing or (id_b, id_a) in existing:
                continue
            sim = title_similarity(title_a, title_b)
            if sim >= SIMILARITY_THRESHOLD:
                # Earlier article is the "original"
                conn.execute(
                    "INSERT OR IGNORE INTO article_duplicates (article_id, duplicate_of_id, similarity) "
                    "VALUES (?, ?, ?)",
                    (id_b, id_a, round(sim, 3)),
                )
                count += 1

    conn.commit()
    log.info("Found %d duplicate pairs", count)
    return count
