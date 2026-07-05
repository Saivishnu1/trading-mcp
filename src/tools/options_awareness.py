"""
Phase 6 — Option Structure Awareness MCP tool.
"""
from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.options_awareness.engine import OptionsAwarenessEngine


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def analyze_option_structure(
        symbol: str,
        expiry: Optional[str] = None,
    ) -> dict:
        """Unified option chain analysis — OI walls, max pain, PCR, IV skew, and S/R levels.

        Replaces get_oi_analysis and identify_support_resistance_from_oi with a
        richer, single-call interface. Factual observations only — no signals,
        no targets, no confidence scores.

        Args:
            symbol: "NIFTY", "BANKNIFTY", "SENSEX", "BANKEX", or equity symbol
            expiry: "27-Jun-2024" format — defaults to nearest expiry
        """
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "analyze_option_structure")

        sym = symbol.upper().strip()
        engine = OptionsAwarenessEngine()
        result = engine.analyze(sym, expiry)

        has_error = "error" in result
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_INVALID if has_error else _meta.DQ_VALID,
            source="NSE" if sym not in ("SENSEX", "BANKEX") else "BSE",
            account_type="MARKET_DATA_ONLY",
            warning=(
                None if _meta.is_market_hours()
                else "Outside market hours — OI reflects previous session."
            ),
        )
        return _meta.wrap(result, m)
