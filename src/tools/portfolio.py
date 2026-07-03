from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP
from src.broker import require_broker
from src import meta as _meta


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_holdings() -> list[dict]:
        """Return your long-term demat holdings.

        Each entry includes tradingsymbol, exchange, quantity, average_price,
        last_price, pnl, and day_change. Requires an active session
        (call zerodha_login first).
        """
        return require_broker().holdings()

    @mcp.tool()
    def get_positions() -> dict:
        """Return your current intraday and carry-forward positions.

        Returns a dict with 'net' and 'day' keys, each a list of position
        dicts. Requires an active session.
        """
        return require_broker().positions()

    @mcp.tool()
    def get_margins(segment: str = "equity") -> dict:
        """Return available fund margins for a segment.

        Args:
            segment: 'equity' or 'commodity' (default 'equity').

        Requires an active session.
        """
        if segment not in ("equity", "commodity"):
            raise ValueError("segment must be 'equity' or 'commodity'")
        return require_broker().margins(segment=segment)

    @mcp.tool()
    async def analyze_portfolio(broker: str = "all") -> dict:
        """Returns unified portfolio analytics across brokers.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")

        Provides: broker exposure, asset allocation, sector breakdown,
        networth summary, unrealized P&L, concentration risk, and factual
        observations. Does not generate recommendations or price targets.
        """
        from src.brokers.indmoney import INDmoneyBroker
        from src.brokers.zerodha import ZerodhaBroker
        from src.brokers.models import Holding, Position, Fund
        from src.portfolio.analyzer import PortfolioAnalyzer

        all_holdings: list[Holding] = []
        all_positions: list[Position] = []
        all_funds: list[Fund] = []

        async def _fetch_broker(adapter) -> None:
            try:
                auth = await adapter.is_authenticated()
            except Exception:
                auth = False
            if not auth:
                return
            try:
                results = await asyncio.gather(
                    adapter.get_holdings(),
                    adapter.get_positions(),
                    adapter.get_funds(),
                    return_exceptions=True,
                )
                holdings_res, positions_res, funds_res = results
                if isinstance(holdings_res, list):
                    all_holdings.extend(holdings_res)
                if isinstance(positions_res, list):
                    all_positions.extend(positions_res)
                if isinstance(funds_res, list):
                    all_funds.extend(funds_res)
            except Exception:
                pass

        tasks = []
        if broker in ("zerodha", "all"):
            tasks.append(_fetch_broker(ZerodhaBroker()))
        if broker in ("indmoney", "all"):
            tasks.append(_fetch_broker(INDmoneyBroker()))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        data = await PortfolioAnalyzer().get_unified_portfolio(
            all_holdings, all_positions, all_funds
        )

        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="broker_api",
            account_type="LIVE_ACCOUNT",
        )
        return _meta.wrap(data, m)
