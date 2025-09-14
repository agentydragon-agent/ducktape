import logging


def setup_logging(config, log_level: str = "INFO") -> None:
    """Configure basic logging for wt components.

    - Logs to stdout and to `$WT_DIR/wt.log`
    - Uses standard text formatter (no JSON)
    - Log level controlled by log_level argument (defaults to INFO)
    """
    levels = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
    }
    logging.basicConfig(
        level=levels.get(log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.wt_dir / "wt.log"),
        ],
    )
