"""
Export module — CSV/XLSX export and summary markdown generation.

Reads officials and key-staff data from the local SQLite database and
writes flat files into the ``output/`` directory for downstream consumption.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from db import get_connection

# -- Logging ---------------------------------------------------------------
log = logging.getLogger(__name__)

# -- Paths ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"


# ===========================================================================
# Export helpers
# ===========================================================================


def export_officials() -> pd.DataFrame:
    """Query all officials from the database and export to CSV and XLSX.

    Officials are ordered by ``office_level``, ``name``.  Output files:

    * ``output/co_officials.csv``
    * ``output/co_officials.xlsx`` (sheet name "CO Officials")

    Returns
    -------
    pd.DataFrame
        The exported officials data.
    """
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM officials ORDER BY office_level, name",
            conn,
        )
    finally:
        conn.close()

    log.info("Loaded %d officials from database", len(df))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / "co_officials.csv"
    xlsx_path = OUTPUT_DIR / "co_officials.xlsx"

    df.to_csv(csv_path, index=False)
    log.info("Wrote %s", csv_path)

    df.to_excel(xlsx_path, index=False, sheet_name="CO Officials")
    log.info("Wrote %s", xlsx_path)

    return df


def export_staff() -> pd.DataFrame:
    """Query all key staff joined with officials and export to CSV.

    Joins ``key_staff`` with ``officials`` to include the official's name
    and title alongside each staff record.  Output file:

    * ``output/co_key_staff.csv``

    Returns
    -------
    pd.DataFrame
        The exported staff data (may be empty).
    """
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                ks.*,
                o.name  AS official_name,
                o.title AS official_title
            FROM key_staff ks
            JOIN officials o ON ks.official_id = o.id
            ORDER BY o.name, ks.name
            """,
            conn,
        )
    finally:
        conn.close()

    if df.empty:
        log.info("No key-staff records found; skipping CSV export")
        return df

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / "co_key_staff.csv"
    df.to_csv(csv_path, index=False)
    log.info("Wrote %s (%d rows)", csv_path, len(df))

    return df


def write_summary(officials_df: pd.DataFrame) -> None:
    """Write a summary markdown file from the officials DataFrame.

    Output file: ``output/co_officials_summary.md``

    The summary includes:

    * Total officials count
    * Officials by level
    * Party breakdown
    * Contact-coverage percentages
    * Coverage assessment vs. estimated totals
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "co_officials_summary.md"

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(officials_df)

    # -- Officials by level ------------------------------------------------
    level_counts = (
        officials_df["office_level"]
        .value_counts()
        .sort_index()
        .reset_index()
    )
    level_counts.columns = ["office_level", "count"]

    level_table_rows = "\n".join(
        f"| {row.office_level} | {row.count} |"
        for row in level_counts.itertuples()
    )

    # -- Party breakdown ---------------------------------------------------
    party_series = officials_df["party"].fillna("Unknown/Nonpartisan")
    party_counts = (
        party_series
        .value_counts()
        .sort_index()
        .reset_index()
    )
    party_counts.columns = ["party", "count"]

    party_table_rows = "\n".join(
        f"| {row.party} | {row.count} |"
        for row in party_counts.itertuples()
    )

    # -- Contact coverage --------------------------------------------------
    has_twitter = officials_df["twitter_handle"].notna() & (
        officials_df["twitter_handle"] != ""
    )
    has_email = officials_df["email"].notna() & (
        officials_df["email"] != ""
    )

    pct_twitter = (has_twitter.sum() / total * 100) if total else 0
    pct_email = (has_email.sum() / total * 100) if total else 0

    # -- Coverage assessment -----------------------------------------------
    estimated_totals = {
        "statewide": 8,
        "state_legislature": 100,
        "county": 400,
        "municipal": 2000,
        "school_board": 1200,
    }

    found_by_level = (
        officials_df["office_level"]
        .value_counts()
        .to_dict()
    )

    coverage_rows = []
    for level, estimated in estimated_totals.items():
        found = found_by_level.get(level, 0)
        pct = found / estimated * 100 if estimated else 0
        coverage_rows.append(
            f"| {level} | {found} | ~{estimated} | {pct:.1f}% |"
        )
    coverage_table = "\n".join(coverage_rows)

    # -- Assemble markdown -------------------------------------------------
    md = f"""# Colorado Officials Database — Summary

*Generated: {generated}*

## Overview

- **Total officials:** {total}

## Officials by Level

| Office Level | Count |
|---|---|
{level_table_rows}

## Party Breakdown

| Party | Count |
|---|---|
{party_table_rows}

## Contact Coverage

| Metric | Percentage |
|---|---|
| Has Twitter handle | {pct_twitter:.1f}% |
| Has email | {pct_email:.1f}% |

## Coverage Assessment

| Level | Found | Estimated | Coverage |
|---|---|---|---|
{coverage_table}
"""

    out_path.write_text(md)
    log.info("Wrote summary to %s", out_path)


# ===========================================================================
# Pipeline
# ===========================================================================


def run() -> None:
    """Run the full export pipeline: officials, staff, and summary."""
    log.info("Starting export pipeline")

    officials_df = export_officials()
    export_staff()
    write_summary(officials_df)

    log.info("Export pipeline complete")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run()
