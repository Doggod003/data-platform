"""Zillow Research public data client.

Zillow publishes free CSVs at files.zillowstatic.com — no API key needed.
ZHVI = Zillow Home Value Index (typical home value, smoothed, seasonally adjusted).
Docs: https://www.zillow.com/research/data/
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

ZHVI_URLS = {
    "county": (
        "https://files.zillowstatic.com/research/public_csvs/zhvi/"
        "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
    ),
    "metro": (
        "https://files.zillowstatic.com/research/public_csvs/zhvi/"
        "Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
    ),
}


def fetch_zhvi(geo: str = "county") -> pd.DataFrame:
    """Download the ZHVI dataset for the given geography level.

    Returns the raw wide-format frame: one row per region, one column per month.
    """
    url = ZHVI_URLS[geo]
    logger.info("Downloading ZHVI (%s) from Zillow Research", geo)
    df = pd.read_csv(url)
    logger.info("Got %d rows, %d columns", len(df), df.shape[1])
    return df
