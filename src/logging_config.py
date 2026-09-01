"""Centralized logging setup for the three long-running processes that
share one Oracle VM, one PostgreSQL database, and one journald: the MCP
server (systemd unit zerodha-mcp), the position monitor (zerodha-monitor),
and the Telegram admin bot (telegram-admin).

Before this module existed, each process called logging.basicConfig()
independently (src/server.py, src/monitor/service.py,
src/telegram_admin/main.py) with three slightly different formats and no
way to tell which process emitted a given journald line, or to trace a
single request/incident across all three.

configure_logging() is the single call site for all three -- call it once,
from the process entry point only (main() / main_stdio() / the __main__
block), never at import time in a library module. Importing src.* from a
test must not silently reconfigure the root logger and hijack pytest's own
log capture, which is exactly what the old module-level basicConfig calls
did.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timezone

# Correlation ID for the current request/operation, set by src/server.py's
# ASGI app from an incoming X-Request-ID header (or a fresh one) and read
# by the logging.Filter below so every log line during that request carries
# the same id, across whichever of the three processes actually handles it.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_configured = False


class _RequestIdFilter(logging.Filter):
    """Injects the current request_id (or "-" outside a request context)
    into every LogRecord, so both formatters below can reference it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    """Minimal structured formatter -- deliberately not a new dependency
    (no python-json-logger/structlog). One json.dumps call per record."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _human_formatter(service: str) -> logging.Formatter:
    return logging.Formatter(
        fmt=f"%(asctime)s [{service}] %(name)s %(levelname)s [%(request_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def configure_logging(
    service: str,
    level: str | None = None,
    json_output: bool | None = None,
) -> None:
    """Configure the root logger for one of the three processes.

    service     — "mcp" | "monitor" | "telegram-admin". Appears on every
                  log record so journald output from all three units is
                  attributable.
    level       — defaults to $LOG_LEVEL, then "INFO".
    json_output — defaults to $LOG_FORMAT == "json". Human-readable output
                  is the default so a developer's first local run is
                  readable without extra setup; set LOG_FORMAT=json in the
                  systemd unit files for structured production logs.

    Idempotent: a second call is a no-op rather than double-attaching
    handlers and duplicating every subsequent log line.
    """
    global _configured
    if _configured:
        return

    resolved_level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    resolved_level = getattr(logging, resolved_level_name, logging.INFO)

    if json_output is None:
        json_output = os.environ.get("LOG_FORMAT", "").strip().lower() == "json"

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(_RequestIdFilter())

    try:
        formatter: logging.Formatter = (
            _JsonFormatter(service) if json_output else _human_formatter(service)
        )
    except Exception:
        # Never let a logging-setup problem prevent the process from
        # starting -- fall back to the plain formatter unconditionally.
        formatter = _human_formatter(service)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(resolved_level)
    root.handlers.clear()
    root.addHandler(handler)

    _configured = True


def new_request_id() -> str:
    """Generate a short, URL-safe correlation id for a new request/operation."""
    return secrets.token_hex(8)
