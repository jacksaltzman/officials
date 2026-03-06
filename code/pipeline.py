"""Main pipeline: orchestrate all phases of the Officials database build."""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    """Run the full pipeline."""
    log.info("=" * 60)
    log.info("Colorado Officials Database Pipeline")
    log.info("=" * 60)

    # Phase 1: State legislators
    from open_states import run as run_open_states
    run_open_states()

    # Phase 2a: Statewide officials
    from scrapers.statewide import run as run_statewide
    run_statewide()

    # Phase 2b: County officials
    from scrapers.county import run as run_county
    run_county()

    # Phase 2c: Municipal officials
    from scrapers.municipal import run as run_municipal
    run_municipal()

    # Phase 2d: School board officials
    from scrapers.school_board import run as run_school_board
    run_school_board()

    # Export
    from export import run as run_export
    run_export()

    # Generate tree visualization data
    from generate_tree_data import run as run_tree_data
    run_tree_data()

    log.info("=" * 60)
    log.info("Pipeline complete!")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
