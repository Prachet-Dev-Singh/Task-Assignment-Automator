"""
app/logging_config.py — Structured logging configuration using structlog.

Provides structured contextual logging across both FastAPI HTTP requests
and Celery background workers. In production, logs are output as JSON lines
with task_id and email_id automatically included.
"""

import logging
import sys
import structlog


def configure_logging(log_level: str = "INFO"):
    """Initialize structlog with standard library integration."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer() if sys.stdout.isatty() else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    """Return a structlog logger bound to the module name."""
    return structlog.get_logger(name)

