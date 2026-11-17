"""The console log and the rotating log file (SPEC §13.3).

The log records Workspace-relative paths only, never Note content or secrets. The
launch URL carries a one-time code, so it is printed, never logged; uvicorn's access
log is off because request lines can carry that code too.
"""

import logging
import logging.handlers
import sys
from pathlib import Path

LOG_FILE = Path("logs") / "memex.log"
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(home: Path) -> Path:
    """Send `memex` and `uvicorn` logs to the console and `<home>/logs/memex.log`."""
    path = home / LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(FORMAT)
    to_file = logging.handlers.RotatingFileHandler(
        path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    to_console = logging.StreamHandler(sys.stderr)
    for handler in (to_file, to_console):
        handler.setFormatter(formatter)
    for name in ("memex", "uvicorn"):
        logger = logging.getLogger(name)
        logger.handlers[:] = [to_file, to_console]
        logger.setLevel(logging.INFO)
        logger.propagate = False
    logging.getLogger("uvicorn.access").disabled = True
    return path
