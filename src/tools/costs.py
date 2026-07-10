"""Trade-count and cost-visibility MCP tools (Priority 4, 2026-07-10).

Brokerage/STT/exchange charges were only visible after manually checking the
INDmoney ledger — this surfaces a directional, in-session estimate instead.
Not a reconciliation against the broker's actual ledger; see the returned
`note` field. Reuses the same Zerodha orders() call as get_orders (src/tools/
journal.py) rather than duplicating the fetch.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src.broker import require_broker as _require_broker
from src import meta as _meta

# Zerodha's flat per-order brokerage on the app-based tier — directionally
# useful default, not a precise reconciliation (configurable via param).
_DEFAULT_BROKERAGE_PER_ORDER = 20.0

# Rough STT + exchange transaction charges as a percentage of turnover for
# options — a coarse blended estimate, not exchange-exact. Turnover here is
# option premium x quantity (not notional), matching what's available from
# the order list without an extra fetch.
_DEFAULT_STT_PCT_OF_TURNOVER = 0.05


def _completed_orders_today(orders: list[dict]) -> list[dict]:
    return [o for o in orders if (o.get("status") or "").upper() == "COMPLETE"]


def _cost_meta(data: dict, *, zerodha_connected: bool) -> dict:
    return _meta.build_meta(
        type_=_meta.TYPE_FACT,
        validation_status=_meta.VALIDATION_VERIFIED,
        data_quality=_meta.DQ_INVALID if "error" in data else _meta.DQ_VALID,
        source="zerodha_api",
        account_type="MARKET_DATA_ONLY",
        zerodha_connected=zerodha_connected,
        warning="Estimates only — see INDmoney/Kite ledger for exact charges.",
    )


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_trade_cost_estimate(brokerage_per_order: float = _DEFAULT_BROKERAGE_PER_ORDER) -> dict:
        """Estimate today's trade count and brokerage/STT costs.

        Directional visibility only — not an exact reconciliation. Pulls
        today's completed orders from your Zerodha account and estimates
        brokerage at a flat per-order rate plus a rough STT/exchange-charge
        percentage of turnover. Requires an active Zerodha session (call
        zerodha_login first).

        Args:
            brokerage_per_order: Flat brokerage assumed per completed order,
                in rupees (default 20, matching Zerodha's app-based tier).
        """
        connected = False
        try:
            orders = _require_broker().orders()
            connected = True
            completed = _completed_orders_today(orders)

            turnover = sum(
                float(o.get("average_price") or 0) * float(o.get("filled_quantity") or o.get("quantity") or 0)
                for o in completed
            )
            estimated_brokerage = round(len(completed) * brokerage_per_order, 2)
            estimated_stt_charges = (
                round(turnover * _DEFAULT_STT_PCT_OF_TURNOVER / 100, 2) if turnover else None
            )
            estimated_total_cost = round(
                estimated_brokerage + (estimated_stt_charges or 0.0), 2
            )

            data = {
                "trades_today": len(completed),
                "estimated_brokerage": estimated_brokerage,
                "estimated_stt_charges": estimated_stt_charges,
                "estimated_total_cost": estimated_total_cost,
                "note": "Estimates only — see INDmoney/Kite ledger for exact charges.",
                "assumptions": {
                    "brokerage_per_order": brokerage_per_order,
                    "stt_pct_of_turnover": _DEFAULT_STT_PCT_OF_TURNOVER if turnover else None,
                },
            }
        except Exception as exc:
            data = {"error": str(exc)}
        return _meta.wrap(data, _cost_meta(data, zerodha_connected=connected))
