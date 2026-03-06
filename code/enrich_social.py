"""
Social media enrichment stub — coverage reporting & manual handle updates.

Reports current Twitter / Facebook / email coverage across all officials
in the database.  Automated enrichment (X search, Google search) is
future work; for now the module provides a CLI for one-off handle updates.
"""

import logging

import pandas as pd

from db import get_connection

log = logging.getLogger(__name__)


# ── Coverage report ──────────────────────────────────────────────────────


def report_coverage() -> None:
    """Query all officials and print social-media coverage statistics.

    Prints overall counts and percentages for twitter_handle, facebook_url,
    and email, then a per-office_level breakdown of Twitter coverage.
    """
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM officials", conn)
    conn.close()

    total = len(df)
    if total == 0:
        log.warning("No officials in the database — nothing to report.")
        return

    # — Overall coverage ——————————————————————————————————————————————————
    twitter_count = df["twitter_handle"].notna().sum()
    facebook_count = df["facebook_url"].notna().sum()
    email_count = df["email"].notna().sum()

    print("\n===  Social-Media Coverage Report  ===\n")
    print(f"Total officials : {total}")
    print(f"Twitter coverage: {twitter_count:>4}  ({twitter_count / total * 100:5.1f}%)")
    print(f"Facebook coverage:{facebook_count:>4}  ({facebook_count / total * 100:5.1f}%)")
    print(f"Email coverage  : {email_count:>4}  ({email_count / total * 100:5.1f}%)")

    # — Per office_level breakdown ————————————————————————————————————————
    levels = sorted(df["office_level"].dropna().unique())
    if levels:
        print("\n--- Twitter coverage by office level ---")
        for level in levels:
            subset = df[df["office_level"] == level]
            level_total = len(subset)
            level_tw = subset["twitter_handle"].notna().sum()
            pct = level_tw / level_total * 100 if level_total else 0.0
            print(f"  {level:<12}  {level_tw:>4} / {level_total:<4}  ({pct:5.1f}%)")

    print()


# ── Manual handle update ─────────────────────────────────────────────────


def update_handle(official_id: str, twitter_handle: str, verified: bool = True) -> None:
    """Update a single official's twitter_handle and twitter_verified.

    Parameters
    ----------
    official_id : str
        The ``id`` value of the official to update.
    twitter_handle : str
        New Twitter/X handle (with or without leading '@').
    verified : bool
        Whether the handle has been manually verified (default True).
    """
    conn = get_connection()
    conn.execute(
        "UPDATE officials SET twitter_handle = ?, twitter_verified = ? WHERE id = ?",
        (twitter_handle, int(verified), official_id),
    )
    conn.commit()
    conn.close()
    log.info("Updated twitter_handle for %s → %s (verified=%s)", official_id, twitter_handle, verified)


# ── Entry point ──────────────────────────────────────────────────────────


def run() -> None:
    """Run the social-media enrichment stub."""
    log.info("=== Social-Media Enrichment (stub) ===")
    report_coverage()


if __name__ == "__main__":
    run()
