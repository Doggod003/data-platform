"""Entry point: python -m data_platform"""

from data_platform.config import settings
from data_platform.utils.logging import setup_logging


def main() -> None:
    logger = setup_logging(settings.log_level)
    logger.info("data_platform starting up")
    # Wire your pipelines here, e.g.:
    # from data_platform.pipelines.example import run
    # run()


if __name__ == "__main__":
    main()
