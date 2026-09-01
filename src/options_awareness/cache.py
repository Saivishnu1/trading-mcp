"""
File-based EOD cache for option chain data.

Cache files: /tmp/option_cache_{symbol}_{expiry_slug}.json
TTL:
  market hours (09:15–15:30 IST) → 300 s  (live refresh every 5 min)
  post-market                    → 86400 s (reuse last session snapshot)

Each cache entry:
  {
    "chain":       <raw chain dict>,
    "resolved":    <expiry string>,
    "cached_at":   <ISO-8601 UTC timestamp>,
    "cached_at_ist": <ISO-8601 IST timestamp>
  }

The engine stamps the MCP result with cache_status / cached_at / note when
it serves a post-market snapshot.
"""
from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_IST = timezone(timedelta(hours=5, minutes=30))
_MARKET_OPEN  = (9, 15)
_MARKET_CLOSE = (15, 30)

CACHE_TTL_MARKET   = 300      # 5 min during session
CACHE_TTL_POST     = 86400    # 24 h after close

_CACHE_DIR = Path(tempfile.gettempdir())


def _is_market_hours() -> bool:
    now = datetime.now(_IST)
    open_  = now.replace(hour=_MARKET_OPEN[0],  minute=_MARKET_OPEN[1],  second=0, microsecond=0)
    close_ = now.replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1], second=0, microsecond=0)
    return open_ <= now <= close_


def _cache_path(symbol: str, expiry: str | None) -> Path:
    slug = re.sub(r"[^\w]", "_", (expiry or "nearest"))
    return _CACHE_DIR / f"option_cache_{symbol.upper()}_{slug}.json"


def _ttl() -> int:
    return CACHE_TTL_MARKET if _is_market_hours() else CACHE_TTL_POST


def read_cache(symbol: str, expiry: str | None) -> dict | None:
    """Return cached entry if it exists and is within TTL, else None."""
    path = _cache_path(symbol, expiry)
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(entry["cached_at"])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age <= _ttl():
            return entry
    except Exception:
        pass
    return None


def write_cache(symbol: str, expiry: str | None, chain: dict, resolved: str | None) -> None:
    """Persist chain to cache file. Silent on failure."""
    path = _cache_path(symbol, expiry)
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(_IST)
    entry = {
        "chain":         chain,
        "resolved":      resolved,
        "cached_at":     now_utc.isoformat(),
        "cached_at_ist": now_ist.isoformat(),
    }
    try:
        path.write_text(json.dumps(entry), encoding="utf-8")
    except Exception:
        pass


def cache_metadata(entry: dict) -> dict:
    """Build the cache_status dict to attach to MCP results."""
    return {
        "cache_status": "EOD_SNAPSHOT",
        "cached_at":    entry.get("cached_at_ist") or entry.get("cached_at"),
        "note":         "Post-market — data reflects last session close",
    }
