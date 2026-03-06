"""
Statewide elected officials for Colorado.

A small, stable set of ~5 officials that changes only at election cycles,
so hardcoding is appropriate.  The ``run()`` function upserts them into
the SQLite database via the ``db`` module.
"""

import logging
import sys
from pathlib import Path

# Ensure the parent ``code/`` directory is on sys.path so we can
# ``import db`` regardless of how this module is invoked.
_CODE_DIR = str(Path(__file__).resolve().parent.parent)
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from db import get_connection, upsert_official, count_officials, now_iso  # noqa: E402

log = logging.getLogger(__name__)

# ── Hardcoded official records ────────────────────────────────────────────

STATEWIDE_OFFICIALS: list[dict] = [
    {
        "id": "CO-SW-GOV",
        "name": "Jared Polis",
        "first_name": "Jared",
        "last_name": "Polis",
        "title": "Governor",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "303-866-2471",
        "website": "https://www.colorado.gov/governor/",
        "twitter_handle": "@GovofCO",
        "twitter_verified": 1,
        "facebook_url": "https://www.facebook.com/GovernorPolis",
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
    {
        "id": "CO-SW-LTGOV",
        "name": "Dianne Primavera",
        "first_name": "Dianne",
        "last_name": "Primavera",
        "title": "Lieutenant Governor",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "303-866-2471",
        "website": "https://ltgovernor.colorado.gov/",
        "twitter_handle": "@LtGovPrimavera",
        "twitter_verified": 1,
        "facebook_url": None,
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
    {
        "id": "CO-SW-AG",
        "name": "Phil Weiser",
        "first_name": "Phil",
        "last_name": "Weiser",
        "title": "Attorney General",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "720-508-6000",
        "website": "https://coag.gov/",
        "twitter_handle": "@AGPhilWeiser",
        "twitter_verified": 1,
        "facebook_url": None,
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
    {
        "id": "CO-SW-SOS",
        "name": "Jena Griswold",
        "first_name": "Jena",
        "last_name": "Griswold",
        "title": "Secretary of State",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "303-894-2200",
        "website": "https://www.sos.state.co.us/",
        "twitter_handle": "@JenaGriswold",
        "twitter_verified": 1,
        "facebook_url": None,
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
    {
        "id": "CO-SW-TREAS",
        "name": "Dave Young",
        "first_name": "Dave",
        "last_name": "Young",
        "title": "State Treasurer",
        "office_level": "statewide",
        "office_branch": "executive",
        "body": None,
        "district": None,
        "party": "Democratic",
        "state": "CO",
        "county": None,
        "municipality": None,
        "email": None,
        "phone": "303-866-2441",
        "website": "https://www.colorado.gov/treasury",
        "twitter_handle": None,
        "twitter_verified": 0,
        "facebook_url": None,
        "photo_url": None,
        "source": "manual",
        "source_id": None,
    },
]


# ── Entry point ───────────────────────────────────────────────────────────


def run() -> None:
    """Upsert all statewide officials into the database."""
    conn = get_connection()

    for official in STATEWIDE_OFFICIALS:
        official["scraped_at"] = now_iso()
        upsert_official(conn, official)

    conn.commit()

    total = count_officials(conn, office_level="statewide")
    log.info("Upserted %d statewide officials.  Total statewide rows: %d",
             len(STATEWIDE_OFFICIALS), total)
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    run()
