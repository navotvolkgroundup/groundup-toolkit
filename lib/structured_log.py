"""Structured JSON logging with automatic credential redaction.

Usage:
    from lib.structured_log import get_logger
    log = get_logger("my-service")
    log.info("Processing item", extra={"item_id": 42})
"""

import json
import logging
import os
from datetime import datetime, timezone

from lib.safe_log import sanitize_error

_STRUCTURED = os.environ.get("STRUCTURED_LOGS", "0") == "1"


class _JsonFormatter(logging.Formatter):
    """Outputs one JSON object per log line with credential redaction."""

    def __init__(self, service):
        super().__init__()
        self.service = service

    def format(self, record):
        msg = sanitize_error(record.getMessage())
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "msg": msg,
        }
        # Merge any extra keys the caller passed (skip internal logging attrs)
        _internal = {
            "name", "msg", "args", "created", "relativeCreated", "exc_info",
            "exc_text", "stack_info", "lineno", "funcName", "pathname",
            "filename", "module", "levelno", "levelname", "msecs",
            "processName", "process", "threadName", "thread", "taskName",
            "message",
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _internal}
        if extras:
            entry["extra"] = extras
        if record.exc_info and record.exc_info[0]:
            entry["exc"] = sanitize_error(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


class _HumanFormatter(logging.Formatter):
    """Human-readable format with credential redaction."""

    def __init__(self, service):
        super().__init__(
            fmt=f"%(asctime)s [{service}] %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record):
        return sanitize_error(super().format(record))


def get_logger(service, level=logging.INFO):
    """Return a logger configured for *service* with JSON or human output."""
    logger = logging.getLogger(service)
    if logger.handlers:          # already configured
        return logger
    logger.setLevel(level)
    handler = logging.StreamHandler()
    if _STRUCTURED:
        handler.setFormatter(_JsonFormatter(service))
    else:
        handler.setFormatter(_HumanFormatter(service))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
