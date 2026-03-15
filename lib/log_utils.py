"""Logging utilities for safe exception handling."""

import logging
import traceback


def log_swallowed(logger, msg, exc):
    """Log a swallowed exception at WARNING level with DEBUG traceback.

    Use this instead of bare ``except: pass`` to make failures visible
    without spamming production logs.
    """
    logger.warning('%s: %s', msg, exc)
    logger.debug('Traceback for %s:\n%s', msg, traceback.format_exc())
