"""
PortfolioAnalyzer — builds unified portfolio analytics from normalized
broker data (Holdings, Positions, Funds).

Does NOT generate buy/sell recommendations, price targets, confidence
scores, or probability estimates.
"""
from __future__ import annotations

from src.brokers.models import Holding, Position, Fund
from src.portfolio.allocator import AssetAllocator
from src.portfolio.risk import RiskAnalyzer


class PortfolioAnalyzer:

    async def get_unified_portfolio(
        self,
        holdings: list[Holding],
        positions: list[Position],
        funds: list[Fund],
    ) -> dict:
        """Build full portfolio analytics from normalized broker data."""
        allocator = AssetAllocator()
        risk = RiskAnalyzer()

        total_holdings_value = sum(h.current_price * h.quantity for h in holdings)
        total_positions_pnl = sum(p.pnl for p in positions)
        total_cash = sum(f.available for f in funds)
        total_pnl = sum(h.pnl for h in holdings)
        total_invested = sum(h.avg_price * h.quantity for h in holdings)
        unrealized_pct = (
            (total_pnl / total_invested * 100) if total_invested > 0 else 0.0
        )

        broker_exposure = allocator.by_broker(holdings)
        sector_exposure = allocator.by_sector(holdings)
        concentration = risk.concentration_risk(holdings)
        largest_positions = risk.largest_positions(holdings, top_n=5)

        observations = self._build_observations(
            holdings,
            positions,
            funds,
            sector_exposure,
            concentration,
            total_holdings_value,
            total_cash,
        )

        return {
            "broker_exposure": broker_exposure,
            "asset_allocation": allocator.by_asset_class(holdings, positions),
            "sector_exposure": sector_exposure,
            "networth": {
                "holdings_value": round(total_holdings_value, 2),
                "positions_pnl": round(total_positions_pnl, 2),
                "available_cash": round(total_cash, 2),
                "total": round(
                    total_holdings_value + total_positions_pnl + total_cash, 2
                ),
            },
            "pnl": {
                "unrealized": round(total_pnl, 2),
                "unrealized_percent": round(unrealized_pct, 2),
                "realized_today": 0.0,  # Would need trade-book for this
            },
            "concentration_risk": concentration,
            "largest_positions": largest_positions,
            "broker_data": {
                "analyst_targets": [],
                "broker_recommendations": [],
                "fundamentals": {},
            },
            "observations": observations,
        }

    def _build_observations(
        self,
        holdings: list[Holding],
        positions: list[Position],
        funds: list[Fund],
        sector_exposure: dict,
        concentration: dict,
        total_value: float,
        total_cash: float,
    ) -> list[str]:
        obs: list[str] = []
        if not holdings:
            obs.append("No holdings data available.")
            return obs

        # Sector concentration — top 3 sectors above 5%
        for sector, data in sorted(
            sector_exposure.items(), key=lambda x: -x[1]["percent"]
        )[:3]:
            if data["percent"] > 5:
                obs.append(
                    f"{sector} sector represents {data['percent']:.1f}% of portfolio."
                )

        # Largest single position
        if concentration["largest_position"]:
            obs.append(
                f"Largest position: {concentration['largest_position']} "
                f"({concentration['largest_position_percent']:.1f}% of portfolio)."
            )

        # Top-5 concentration
        if concentration.get("top5_percent", 0) > 0:
            obs.append(
                f"Top 5 positions account for {concentration['top5_percent']:.1f}% "
                f"of total value."
            )

        # Available cash
        if total_cash > 0:
            obs.append(f"Available cash across brokers: ₹{total_cash:,.0f}.")

        # Multi-broker spread
        brokers_active = len(set(h.broker for h in holdings))
        if brokers_active > 1:
            obs.append(f"Holdings spread across {brokers_active} brokers.")

        return obs
