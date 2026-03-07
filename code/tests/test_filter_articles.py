"""Tests for content filtering (obituaries, photo galleries, wire stories)."""

import sqlite3
import pytest

from news.filter_articles import is_obituary, is_gallery, is_wire_story, filter_articles


@pytest.fixture
def conn():
    """In-memory database with full schema."""
    import db as db_module
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON;")
    c.execute(db_module._SCHEMA_OFFICIALS)
    c.execute(db_module._SCHEMA_KEY_STAFF)
    for stmt in db_module._NEWS_SCHEMAS:
        c.execute(stmt)
    c.commit()
    return c


# -- is_obituary tests -------------------------------------------------------

def test_is_obituary_chieftain_pattern():
    """Title ending with '- Pueblo Chieftain' is an obituary."""
    assert is_obituary("John Smith - Pueblo Chieftain") is True


def test_is_obituary_dash_chieftain():
    """Title ending with '- Chieftain' is an obituary."""
    assert is_obituary("Jane Doe - Chieftain") is True


def test_is_obituary_real_article():
    """Normal news title is NOT an obituary."""
    assert is_obituary("Pueblo mayor addresses housing") is False


# -- is_gallery tests ---------------------------------------------------------

def test_is_gallery():
    """Title starting with 'Photos:' is a gallery."""
    assert is_gallery("Photos: Durango flooding") is True


def test_is_gallery_normal():
    """Normal title is NOT a gallery."""
    assert is_gallery("City council votes on budget") is False


# -- is_wire_story tests ------------------------------------------------------

def test_is_wire_story_ap_in_title():
    """Title containing '(AP)' is a wire story."""
    assert is_wire_story("Biden visits Colorado (AP)", None) is True


def test_is_wire_story_reuters_in_body():
    """Body containing '(Reuters)' is a wire story."""
    assert is_wire_story("Market rally continues", "Stocks rose sharply (Reuters) today") is True


def test_is_wire_story_normal():
    """Normal article without wire tags is not a wire story."""
    assert is_wire_story("Local school board meets", "The board discussed budgets") is False


# -- filter_articles integration tests ----------------------------------------

def test_filter_articles_removes_obituaries(conn):
    """Obituary inserted into DB should be deleted by filter_articles."""
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://chieftain.com/obit1", "John Smith - Pueblo Chieftain", "pueblo_chieftain"),
    )
    conn.commit()

    deleted = filter_articles(conn)

    assert deleted == 1
    remaining = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert remaining == 0


def test_filter_articles_keeps_real_articles(conn):
    """Real news article should survive filtering."""
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://example.com/news", "Pueblo mayor addresses housing crisis", "pueblo_chieftain"),
    )
    conn.commit()

    deleted = filter_articles(conn)

    assert deleted == 0
    remaining = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert remaining == 1


def test_filter_articles_removes_gallery(conn):
    """Photo gallery should be deleted by filter_articles."""
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://example.com/gallery", "Photos: Durango flooding aftermath", "durango_herald"),
    )
    conn.commit()

    deleted = filter_articles(conn)
    assert deleted == 1


def test_filter_articles_removes_wire_story(conn):
    """Wire story should be deleted by filter_articles."""
    conn.execute(
        "INSERT INTO articles (url, title, body, source) VALUES (?, ?, ?, ?)",
        ("https://example.com/wire", "Economy update", "The economy grew (AP) at 3%", "denver_post"),
    )
    conn.commit()

    deleted = filter_articles(conn)
    assert deleted == 1


def test_filter_articles_cleans_junction_tables(conn):
    """Deleting an article should also remove its junction-table rows."""
    conn.execute(
        "INSERT INTO articles (url, title, source) VALUES (?, ?, ?)",
        ("https://chieftain.com/obit2", "Mary Jones - Chieftain", "pueblo_chieftain"),
    )
    conn.execute("INSERT INTO issues (name, slug) VALUES (?, ?)", ("Test Issue", "test-issue"))
    conn.execute("INSERT INTO article_issues (article_id, issue_id) VALUES (?, ?)", (1, 1))
    conn.execute(
        "INSERT INTO article_regions (article_id, region_name, region_type) VALUES (?, ?, ?)",
        (1, "Pueblo", "municipality"),
    )
    conn.commit()

    deleted = filter_articles(conn)
    assert deleted == 1

    # Junction rows should be gone
    assert conn.execute("SELECT COUNT(*) FROM article_issues").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM article_regions").fetchone()[0] == 0
