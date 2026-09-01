"""
Phase 24A — Generic provider framework.

Every data provider in this codebase implements BaseProvider and returns a
ProviderResult. Consumers never inspect provider internals — they read
ProviderResult.data for payload, ProviderResult.as_source_meta() for
transparency, and ProviderResult.as_provider_meta() for full diagnostics.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ProviderResult:
    """Carrier for provider-fetched data with full provenance metadata."""

    data: Any
    provider_name: str
    data_source: str       # human-readable source description or path
    authority: str         # who is the authoritative source (e.g. "NSE Holiday Circular")
    status: str            # HEALTHY | CACHED | EMERGENCY | FAILED
    fallback_level: int    # 0=primary, 1=secondary, 2=emergency
    cache_status: str      # HIT | MISS | BYPASS
    cache_age_seconds: int # 0 on a MISS
    ttl_seconds: int
    last_refresh: str      # ISO UTC timestamp of the underlying data load

    def as_provider_meta(self) -> dict:
        """Full provider metadata for diagnostics (D5)."""
        return {
            "provider_name":      self.provider_name,
            "data_source":        self.data_source,
            "authority":          self.authority,
            "status":             self.status,
            "cache_status":       self.cache_status,
            "cache_age_seconds":  self.cache_age_seconds,
            "ttl_seconds":        self.ttl_seconds,
            "last_refresh":       self.last_refresh,
            "fallback_level":     self.fallback_level,
        }

    def as_source_meta(self) -> dict:
        """Minimal transparency dict for embedding in consumer responses (D6)."""
        return {
            "provider":    self.provider_name,
            "authority":   self.authority,
            "data_source": self.data_source,
            "status":      self.status,
        }


class BaseProvider(ABC):
    """Abstract base for all data providers."""

    @abstractmethod
    def fetch(self) -> ProviderResult | None:
        """Attempt to fetch data.  Return None to signal failure (chain tries next)."""

    @abstractmethod
    def health(self) -> dict:
        """Return current health dict without triggering a live fetch."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider identifier."""
