"""Standalone entrypoint: python -m src.monitor.service

Runs independently of the FastAPI/MCP server process (systemd unit on the
Oracle VM). Never start this inside the FastAPI startup event.

Takes an exclusive flock on MONITOR_LOCK_FILE for the lifetime of the process
so a duplicate systemd start (or manual re-run) exits immediately instead of
running two schedulers that would double-fire alerts and race on peaks/SL.
fcntl is Linux-only, matching every other DB/asyncio dependency in this
package — this module is never imported on Windows dev.
"""
import asyncio
import fcntl
import logging
import os
import sys

from src.monitor.scheduler import MarketMonitor

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_LOCK_FILE = os.environ.get("MONITOR_LOCK_FILE", "/tmp/zerodha-monitor.lock")


def _acquire_singleton_lock():
    """Return an open file handle holding an exclusive, non-blocking flock.

    The lock is released automatically when the process exits (or the fd is
    closed), so no explicit cleanup is required — an OS-level guarantee that
    survives a hard crash, unlike a lock row in Postgres.
    """
    fh = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.error("Another zerodha-monitor process already holds %s — exiting.", _LOCK_FILE)
        fh.close()
        sys.exit(1)
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


async def main() -> None:
    monitor = MarketMonitor()
    await monitor.run()


if __name__ == "__main__":
    _lock_handle = _acquire_singleton_lock()
    try:
        asyncio.run(main())
    finally:
        _lock_handle.close()
