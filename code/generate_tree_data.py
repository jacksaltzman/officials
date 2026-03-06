"""
Generate a nested JSON tree from the officials SQLite database.

Reads all officials and builds a hierarchy suitable for the D3 tree
visualisation:

    Colorado
    ├── Statewide Officials
    ├── State Senate
    ├── State House
    ├── County Officials  → grouped by county
    └── Municipal Officials → grouped by municipality

Output: webapp/data/tree.json
"""

import json
import logging
import re
import sqlite3

from db import get_connection, BASE_DIR

# -- Logging ----------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# -- Paths ------------------------------------------------------------------
WEBAPP_DIR = BASE_DIR / "webapp"
DATA_DIR = WEBAPP_DIR / "data"


# ===========================================================================
# Helpers
# ===========================================================================

def _district_sort_key(district: str) -> int:
    """Extract the numeric district number for sorting.

    Examples
    --------
    >>> _district_sort_key('SD-12')
    12
    >>> _district_sort_key('HD-3')
    3
    >>> _district_sort_key('unknown')
    999999
    """
    match = re.search(r"(\d+)", district or "")
    return int(match.group(1)) if match else 999999


def _official_node(row: sqlite3.Row) -> dict:
    """Convert a database row into a leaf node dict for the tree."""
    return {
        "name": row["name"],
        "type": "official",
        "title": row["title"],
        "party": row["party"],
        "district": row["district"],
        "county": row["county"],
        "municipality": row["municipality"],
        "email": row["email"],
        "phone": row["phone"],
        "website": row["website"],
        "twitter_handle": row["twitter_handle"],
        "facebook_url": row["facebook_url"],
        "source": row["source"],
    }


# ===========================================================================
# Tree builder
# ===========================================================================

def build_tree(conn: sqlite3.Connection) -> dict:
    """Build the full nested tree from the officials database.

    Returns
    -------
    dict
        Root node with ``name='Colorado'``, ``type='category'``, and five
        child category nodes.
    """
    conn.row_factory = sqlite3.Row

    # -- Statewide Officials ------------------------------------------------
    rows = conn.execute(
        "SELECT * FROM officials WHERE office_level = 'statewide' ORDER BY title"
    ).fetchall()
    statewide = {
        "name": "Statewide Officials",
        "type": "category",
        "count": len(rows),
        "children": [_official_node(r) for r in rows],
    }

    # -- State Senate -------------------------------------------------------
    rows = conn.execute(
        "SELECT * FROM officials "
        "WHERE office_level = 'state_legislature' AND body = 'Senate'"
    ).fetchall()
    rows = sorted(rows, key=lambda r: _district_sort_key(r["district"]))
    state_senate = {
        "name": "State Senate",
        "type": "category",
        "count": len(rows),
        "children": [_official_node(r) for r in rows],
    }

    # -- State House --------------------------------------------------------
    rows = conn.execute(
        "SELECT * FROM officials "
        "WHERE office_level = 'state_legislature' AND body = 'House'"
    ).fetchall()
    rows = sorted(rows, key=lambda r: _district_sort_key(r["district"]))
    state_house = {
        "name": "State House",
        "type": "category",
        "count": len(rows),
        "children": [_official_node(r) for r in rows],
    }

    # -- County Officials ---------------------------------------------------
    rows = conn.execute(
        "SELECT * FROM officials WHERE office_level = 'county' ORDER BY county, name"
    ).fetchall()
    counties: dict[str, list] = {}
    for r in rows:
        county_name = r["county"] or "Unknown County"
        counties.setdefault(county_name, []).append(_official_node(r))

    county_children = []
    for county_name in sorted(counties):
        officials = counties[county_name]
        county_children.append({
            "name": county_name,
            "type": "category",
            "count": len(officials),
            "children": officials,
        })

    county_officials = {
        "name": "County Officials",
        "type": "category",
        "count": len(rows),
        "children": county_children,
    }

    # -- Municipal Officials ------------------------------------------------
    rows = conn.execute(
        "SELECT * FROM officials WHERE office_level = 'municipal' ORDER BY municipality, name"
    ).fetchall()
    municipalities: dict[str, list] = {}
    for r in rows:
        muni_name = r["municipality"] or "Unknown Municipality"
        municipalities.setdefault(muni_name, []).append(_official_node(r))

    muni_children = []
    for muni_name in sorted(municipalities):
        officials = municipalities[muni_name]
        muni_children.append({
            "name": muni_name,
            "type": "category",
            "count": len(officials),
            "children": officials,
        })

    municipal_officials = {
        "name": "Municipal Officials",
        "type": "category",
        "count": len(rows),
        "children": muni_children,
    }

    # -- Root ---------------------------------------------------------------
    root = {
        "name": "Colorado",
        "type": "category",
        "children": [
            statewide,
            state_senate,
            state_house,
            county_officials,
            municipal_officials,
        ],
    }

    return root


# ===========================================================================
# Entry point
# ===========================================================================

def run() -> None:
    """Generate webapp/data/tree.json from the officials database."""
    conn = get_connection()
    try:
        tree = build_tree(conn)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        out_path = DATA_DIR / "tree.json"
        out_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False))

        # Count total leaf nodes
        def _count_leaves(node: dict) -> int:
            if node.get("type") == "official":
                return 1
            return sum(_count_leaves(c) for c in node.get("children", []))

        total = _count_leaves(tree)
        log.info("Wrote %d official nodes to %s", total, out_path)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
