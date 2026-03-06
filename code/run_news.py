"""CLI entry point for the news pipeline."""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from db import get_connection
from news.pipeline import run_news_pipeline
from news.generate_dashboard_data import run as run_dashboard_export


def main() -> None:
    """Run news ingestion, extraction, and dashboard export."""
    reextract = "--reextract" in sys.argv

    conn = get_connection()
    try:
        if reextract:
            from news.pipeline import reextract_all
            reextract_all(conn)
        else:
            run_news_pipeline(conn)
    finally:
        conn.close()

    run_dashboard_export()


if __name__ == "__main__":
    main()
