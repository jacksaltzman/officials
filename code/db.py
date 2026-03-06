"""
Database layer for the Colorado elected-officials project.

Provides SQLite schema creation, connection management, and CRUD helpers
for the `officials` and `key_staff` tables.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# -- Logging ---------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# -- Paths ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # Officials/
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "officials.db"

# -- API key ----------------------------------------------------------------
# Search for Environment.txt in BASE_DIR first, then walk up to the
# main Officials/ directory (handles git-worktree layouts where the file
# lives in the canonical project root rather than the worktree copy).
OPENSTATES_API_KEY: str = ""
_candidate_dirs = [BASE_DIR]
# Walk up from BASE_DIR looking for the Officials project root
_cursor = BASE_DIR
for _ in range(6):
    _cursor = _cursor.parent
    _candidate = _cursor / "Environment.txt"
    if _candidate.exists():
        _candidate_dirs.append(_cursor)
        break

for _dir in _candidate_dirs:
    _env_path = _dir / "Environment.txt"
    if _env_path.exists():
        for _line in _env_path.read_text().strip().splitlines():
            if _line.startswith("OPENSTATES_API_KEY="):
                OPENSTATES_API_KEY = _line.split("=", 1)[1].strip()
                break
    if OPENSTATES_API_KEY:
        break

if not OPENSTATES_API_KEY:
    log.warning("No OPENSTATES_API_KEY found in Environment.txt")

# -- Schema -----------------------------------------------------------------
_SCHEMA_OFFICIALS = """
CREATE TABLE IF NOT EXISTS officials (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    office_level TEXT NOT NULL,
    office_branch TEXT,
    body TEXT,
    district TEXT,
    party TEXT,
    state TEXT NOT NULL DEFAULT 'CO',
    county TEXT,
    municipality TEXT,
    email TEXT,
    phone TEXT,
    website TEXT,
    twitter_handle TEXT,
    twitter_verified INTEGER DEFAULT 0,
    facebook_url TEXT,
    photo_url TEXT,
    source TEXT NOT NULL,
    source_id TEXT,
    scraped_at TEXT NOT NULL
);
"""

_SCHEMA_KEY_STAFF = """
CREATE TABLE IF NOT EXISTS key_staff (
    id TEXT PRIMARY KEY,
    official_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT,
    email TEXT,
    twitter_handle TEXT,
    facebook_url TEXT,
    source TEXT NOT NULL,
    FOREIGN KEY (official_id) REFERENCES officials(id)
);
"""

# -- Column lists (used for upsert helpers) ---------------------------------
_OFFICIALS_COLS = [
    "id", "name", "first_name", "last_name", "title",
    "office_level", "office_branch", "body", "district", "party",
    "state", "county", "municipality",
    "email", "phone", "website",
    "twitter_handle", "twitter_verified", "facebook_url", "photo_url",
    "source", "source_id", "scraped_at",
]

_KEY_STAFF_COLS = [
    "id", "official_id", "name", "role",
    "email", "twitter_handle", "facebook_url", "source",
]


# ===========================================================================
# Connection & Schema
# ===========================================================================

def get_connection() -> sqlite3.Connection:
    """Return a sqlite3 connection to the officials database.

    Creates ``DATA_DIR`` and both tables on first call.  Enables WAL
    journal mode and foreign-key enforcement.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    conn.execute(_SCHEMA_OFFICIALS)
    conn.execute(_SCHEMA_KEY_STAFF)
    conn.commit()

    log.info("Database ready at %s", DB_PATH)
    return conn


# ===========================================================================
# Helpers
# ===========================================================================

def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def upsert_official(conn: sqlite3.Connection, official: dict) -> None:
    """INSERT OR REPLACE a row into the ``officials`` table.

    Parameters
    ----------
    conn : sqlite3.Connection
        An open database connection.
    official : dict
        Mapping of column names to values.  Must include at least
        ``id``, ``name``, ``office_level``, ``source``, and ``scraped_at``.
    """
    cols = [c for c in _OFFICIALS_COLS if c in official]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    values = [official[c] for c in cols]

    conn.execute(
        f"INSERT OR REPLACE INTO officials ({col_names}) VALUES ({placeholders})",
        values,
    )
    conn.commit()


def upsert_staff(conn: sqlite3.Connection, staff: dict) -> None:
    """INSERT OR REPLACE a row into the ``key_staff`` table.

    Parameters
    ----------
    conn : sqlite3.Connection
        An open database connection.
    staff : dict
        Mapping of column names to values.  Must include at least
        ``id``, ``official_id``, ``name``, and ``source``.
    """
    cols = [c for c in _KEY_STAFF_COLS if c in staff]
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    values = [staff[c] for c in cols]

    conn.execute(
        f"INSERT OR REPLACE INTO key_staff ({col_names}) VALUES ({placeholders})",
        values,
    )
    conn.commit()


def count_officials(conn: sqlite3.Connection, office_level: Optional[str] = None) -> int:
    """Return the number of rows in the ``officials`` table.

    Parameters
    ----------
    conn : sqlite3.Connection
        An open database connection.
    office_level : str, optional
        If provided, count only officials at this office level
        (e.g. ``"state"``, ``"federal"``, ``"local"``).
    """
    if office_level is not None:
        row = conn.execute(
            "SELECT COUNT(*) FROM officials WHERE office_level = ?",
            (office_level,),
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM officials").fetchone()
    return row[0]
