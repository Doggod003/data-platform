"""Example pipeline showing the extract -> transform -> load pattern.

Copy this file as a template for each new pipeline.
"""

import logging

logger = logging.getLogger(__name__)


def extract() -> list[dict]:
    """Pull raw data from a source (API, file, database)."""
    return [{"id": 1, "value": 10}, {"id": 2, "value": 20}]


def transform(rows: list[dict]) -> list[dict]:
    """Clean / reshape the data."""
    return [{**r, "value_doubled": r["value"] * 2} for r in rows]


def load(rows: list[dict]) -> None:
    """Write results to the destination."""
    logger.info("Loaded %d rows", len(rows))


def run() -> None:
    load(transform(extract()))
