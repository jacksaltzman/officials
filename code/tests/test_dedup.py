"""Tests for article deduplication."""
import sqlite3
import pytest

from news.dedup import normalize_title, title_similarity, find_duplicates


@pytest.fixture
def conn():
    import db as db_module
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON;")
    c.execute(db_module._SCHEMA_OFFICIALS)
    c.execute(db_module._SCHEMA_KEY_STAFF)
    for stmt in db_module._NEWS_SCHEMAS:
        c.execute(stmt)
    c.commit()
    return c


def test_normalize_title():
    assert normalize_title("Colorado's Budget Crisis \u2014 Report") == "colorados budget crisis report"


def test_title_similarity_identical():
    assert title_similarity("colorado budget crisis", "colorado budget crisis") == 1.0


def test_title_similarity_different():
    assert title_similarity("colorado budget crisis", "denver weather forecast") < 0.3


def test_title_similarity_partial():
    # "colorado budget shortfall this year" vs "colorado budget shortfall threatens funding"
    # intersection: {colorado, budget, shortfall} = 3, union: {colorado, budget, shortfall, this, year, threatens, funding} = 7
    # Jaccard = 3/7 ≈ 0.43
    score = title_similarity(
        "colorado budget shortfall this year",
        "colorado budget shortfall threatens funding",
    )
    assert 0.3 < score < 0.9


def test_find_duplicates_links_similar_articles(conn):
    # "colorado budget shortfall hits schools hard" vs "colorado budget shortfall impacts schools"
    # tokens a: {colorado, budget, shortfall, hits, schools, hard} = 6
    # tokens b: {colorado, budget, shortfall, impacts, schools} = 5
    # intersection: {colorado, budget, shortfall, schools} = 4, union = 7
    # Jaccard = 4/7 ≈ 0.57 — above 0.5 threshold
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://a.com/1", "Colorado budget shortfall hits schools hard", "denver_post"))
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://b.com/2", "Colorado budget shortfall impacts schools", "colorado_sun"))
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://c.com/3", "Denver Broncos win Super Bowl", "denver_post"))
    conn.commit()
    count = find_duplicates(conn)
    dupes = conn.execute("SELECT * FROM article_duplicates").fetchall()
    assert len(dupes) >= 1
    assert count >= 1


def test_find_duplicates_no_self_duplication(conn):
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://a.com/1", "Some article title", "denver_post"))
    conn.commit()
    find_duplicates(conn)
    dupes = conn.execute("SELECT * FROM article_duplicates").fetchall()
    assert len(dupes) == 0


def test_find_duplicates_skips_same_source(conn):
    """Nearly identical titles from the same source should not be linked."""
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://a.com/1", "Colorado budget shortfall hits schools", "denver_post"))
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://a.com/2", "Colorado budget shortfall hits schools hard", "denver_post"))
    conn.commit()
    count = find_duplicates(conn)
    assert count == 0


def test_find_duplicates_idempotent(conn):
    """Calling find_duplicates twice should not create duplicate rows."""
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://a.com/1", "Colorado budget shortfall hits schools hard", "denver_post"))
    conn.execute("INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
                 ("https://b.com/2", "Colorado budget shortfall impacts schools", "colorado_sun"))
    conn.commit()
    count1 = find_duplicates(conn)
    count2 = find_duplicates(conn)
    dupes = conn.execute("SELECT * FROM article_duplicates").fetchall()
    assert count1 >= 1
    assert count2 == 0  # no new duplicates on second run
    assert len(dupes) == 1
