"""
core/logging.py — Structured JSON logging setup.
Call configure_logging() once at the entry point of every service.
"""

import json
import logging
import sys
from datetime import UTC, datetime


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        log_object: dict = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra fields the caller passed as keyword arguments.
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }:
                log_object[key] = value

        if record.exc_info:
            log_object["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_object, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with JSON output to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)

    # Quieten noisy third-party loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
