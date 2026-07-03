"""
Asset allocation helpers — slice portfolio value by broker, sector,
asset class, and exchange.
"""
from __future__ import annotations

from src.brokers.models import Holding, Position
from src.portfolio.sector_map import get_sector


class AssetAllocator:

    def by_broker(self, holdings: list[Holding]) -> dict:
        """Allocate portfolio value by broker."""
        totals: dict[str, float] = {}
        for h in holdings:
            totals[h.broker] = totals.get(h.broker, 0) + h.current_price * h.quantity
        total = sum(totals.values()) or 1
        return {
            broker: {
                "value": round(val, 2),
                "percent": round(val / total * 100, 2),
            }
            for broker, val in totals.items()
        }

    def by_asset_class(
        self, holdings: list[Holding], positions: list[Position]
    ) -> dict:
        """Split into equity (holdings) vs derivatives (positions)."""
        equity_val = sum(h.current_price * h.quantity for h in holdings)
        deriv_pnl = sum(p.pnl for p in positions)
        total = (equity_val + max(deriv_pnl, 0)) or 1
        return {
            "equity": {
                "value": round(equity_val, 2),
                "percent": round(equity_val / total * 100, 2),
            },
            "derivatives": {
                "value": round(deriv_pnl, 2),
                "percent": round(max(deriv_pnl, 0) / total * 100, 2),
            },
        }

    def by_sector(self, holdings: list[Holding]) -> dict:
        """Aggregate holdings value by sector."""
        totals: dict[str, float] = {}
        for h in holdings:
            sector = get_sector(h.symbol)
            totals[sector] = totals.get(sector, 0) + h.current_price * h.quantity
        total = sum(totals.values()) or 1
        return {
            sector: {
                "value": round(val, 2),
                "percent": round(val / total * 100, 2),
            }
            for sector, val in sorted(totals.items(), key=lambda x: -x[1])
        }

    def by_exchange(self, holdings: list[Holding]) -> dict:
        """Aggregate holdings value by exchange."""
        totals: dict[str, float] = {}
        for h in holdings:
            ex = h.exchange or "Unknown"
            totals[ex] = totals.get(ex, 0) + h.current_price * h.quantity
        total = sum(totals.values()) or 1
        return {
            ex: {
                "value": round(val, 2),
                "percent": round(val / total * 100, 2),
            }
            for ex, val in totals.items()
        }
