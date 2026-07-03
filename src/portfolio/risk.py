"""
Risk analysis helpers — concentration risk and largest position sizing.
"""
from __future__ import annotations

from src.brokers.models import Holding


class RiskAnalyzer:

    def concentration_risk(self, holdings: list[Holding]) -> dict:
        """Return concentration risk metrics for the holdings list."""
        if not holdings:
            return {
                "largest_position": "",
                "largest_position_percent": 0.0,
                "top5_percent": 0.0,
                "risk_level": "low",
            }
        values = [(h.symbol, h.current_price * h.quantity) for h in holdings]
        values.sort(key=lambda x: -x[1])
        total = sum(v for _, v in values) or 1
        largest_pct = values[0][1] / total * 100
        top5_pct = sum(v for _, v in values[:5]) / total * 100

        if largest_pct > 40:
            risk_level = "high"
        elif largest_pct > 20:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "largest_position": values[0][0],
            "largest_position_percent": round(largest_pct, 2),
            "top5_percent": round(top5_pct, 2),
            "risk_level": risk_level,
        }

    def largest_positions(
        self, holdings: list[Holding], top_n: int = 5
    ) -> list[dict]:
        """Return the top_n positions by value, sorted descending."""
        if not holdings:
            return []
        values = [
            {
                "symbol": h.symbol,
                "broker": h.broker,
                "value": round(h.current_price * h.quantity, 2),
                "quantity": h.quantity,
                "pnl": round(h.pnl, 2),
                "pnl_percent": round(h.pnl_percent, 2),
            }
            for h in holdings
        ]
        return sorted(values, key=lambda x: -x["value"])[:top_n]

    def single_stock_exposure(self, holdings: list[Holding]) -> dict:
        """Return each symbol's share of total portfolio value (percent)."""
        total = sum(h.current_price * h.quantity for h in holdings) or 1
        return {
            h.symbol: round(h.current_price * h.quantity / total * 100, 2)
            for h in sorted(
                holdings, key=lambda x: -(x.current_price * x.quantity)
            )
        }
