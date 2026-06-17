from typing import Optional
from mcp.server.fastmcp import FastMCP
from src.options.service import get_options_service
from src.options import analytics


def register(mcp: FastMCP) -> None:

    # ------------------------------------------------------------------
    # Internal helpers (not MCP tools)
    # ------------------------------------------------------------------

    def _fetch(symbol: str, expiry: Optional[str]) -> tuple[dict, Optional[str]]:
        svc = get_options_service()
        chain = svc.get_option_chain(symbol.upper())
        available = chain.get("records", {}).get("expiryDates", [])
        resolved = expiry if expiry in available else (available[0] if available else None)
        return chain, resolved

    def _format_chain(chain: dict, symbol: str, expiry: Optional[str], atm_range: int) -> dict:
        records = chain.get("records", {})
        spot = records.get("underlyingValue")
        expiry_dates = records.get("expiryDates", [])
        data: list[dict] = records.get("data", [])

        if expiry:
            data = [d for d in data if d.get("expiryDate") == expiry]

        if atm_range > 0 and spot:
            all_sp = sorted({d.get("strikePrice", 0) for d in data})
            if all_sp:
                atm = min(all_sp, key=lambda x: abs(x - spot))
                idx = all_sp.index(atm)
                lo, hi = max(0, idx - atm_range), idx + atm_range + 1
                allowed = set(all_sp[lo:hi])
                data = [d for d in data if d.get("strikePrice") in allowed]

        strikes = []
        for d in data:
            ce = d.get("CE") or {}
            pe = d.get("PE") or {}
            strikes.append({
                "strike": d.get("strikePrice"),
                "expiry": d.get("expiryDate"),
                "CE": {
                    "oi":        ce.get("openInterest"),
                    "change_oi": ce.get("changeinOpenInterest"),
                    "volume":    ce.get("totalTradedVolume"),
                    "iv":        ce.get("impliedVolatility"),
                    "ltp":       ce.get("lastPrice"),
                    "bid":       ce.get("bidprice"),
                    "ask":       ce.get("askPrice"),
                } if ce else None,
                "PE": {
                    "oi":        pe.get("openInterest"),
                    "change_oi": pe.get("changeinOpenInterest"),
                    "volume":    pe.get("totalTradedVolume"),
                    "iv":        pe.get("impliedVolatility"),
                    "ltp":       pe.get("lastPrice"),
                    "bid":       pe.get("bidprice"),
                    "ask":       pe.get("askPrice"),
                } if pe else None,
            })

        return {
            "symbol":             symbol.upper(),
            "underlying_value":   spot,
            "expiry":             expiry,
            "available_expiries": expiry_dates,
            "total_strikes":      len(strikes),
            "strikes":            strikes,
        }

    # ------------------------------------------------------------------
    # MCP tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def get_expiries(symbol: str = "NIFTY") -> dict:
        """List the available option expiry dates for an index.

        Use the returned strings as the `expiry` argument to the other
        option tools. No authentication required.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'FINNIFTY', or 'MIDCPNIFTY'
                    (default 'NIFTY').
        """
        expiries = get_options_service().available_expiries(symbol.upper())
        return {
            "symbol": symbol.upper(),
            "count": len(expiries),
            "expiries": expiries,
        }

    @mcp.tool()
    def get_nifty_option_chain(
        expiry: Optional[str] = None,
        atm_range: int = 20,
    ) -> dict:
        """Fetch the NIFTY 50 index option chain from NSE.

        Returns per-strike CE/PE open interest, volume, implied volatility,
        last traded price, bid, and ask. No authentication required.

        Args:
            expiry: Expiry date as shown on NSE, e.g. '27-Jun-2024'.
                    Defaults to the nearest weekly/monthly expiry.
            atm_range: Number of strikes above and below ATM to return.
                       Set to 0 to return all strikes (large response).
        """
        chain, resolved = _fetch("NIFTY", expiry)
        return _format_chain(chain, "NIFTY", resolved, atm_range)

    @mcp.tool()
    def get_banknifty_option_chain(
        expiry: Optional[str] = None,
        atm_range: int = 20,
    ) -> dict:
        """Fetch the BANK NIFTY index option chain from NSE.

        Returns per-strike CE/PE open interest, volume, implied volatility,
        last traded price, bid, and ask. No authentication required.

        Args:
            expiry: Expiry date as shown on NSE, e.g. '27-Jun-2024'.
                    Defaults to the nearest weekly/monthly expiry.
            atm_range: Number of strikes above and below ATM to return.
                       Set to 0 to return all strikes.
        """
        chain, resolved = _fetch("BANKNIFTY", expiry)
        return _format_chain(chain, "BANKNIFTY", resolved, atm_range)

    @mcp.tool()
    def calculate_pcr(
        symbol: str = "NIFTY",
        expiry: Optional[str] = None,
    ) -> dict:
        """Calculate Put-Call Ratio (PCR) from NSE option chain OI and volume.

        PCR (OI) > 1.3 is broadly bullish — excess put writing.
        PCR (OI) < 0.7 is broadly bearish — excess call writing.

        Args:
            symbol: Index — 'NIFTY' or 'BANKNIFTY' (default 'NIFTY').
            expiry: Expiry date string. Defaults to nearest expiry.
        """
        chain, resolved = _fetch(symbol, expiry)
        return analytics.calculate_pcr(chain, resolved)

    @mcp.tool()
    def get_oi_analysis(
        symbol: str = "NIFTY",
        expiry: Optional[str] = None,
        top_n: int = 10,
    ) -> dict:
        """Return the top-OI call and put strikes for an index.

        Shows where large option positions are concentrated, useful for
        identifying key market levels and detecting unwinding/buildup.

        Args:
            symbol: 'NIFTY' or 'BANKNIFTY' (default 'NIFTY').
            expiry: Expiry date string. Defaults to nearest expiry.
            top_n: Number of top strikes to return per side (default 10).
        """
        chain, resolved = _fetch(symbol, expiry)
        return analytics.get_oi_analysis(chain, resolved, top_n)

    @mcp.tool()
    def identify_support_resistance_from_oi(
        symbol: str = "NIFTY",
        expiry: Optional[str] = None,
        top_n: int = 5,
    ) -> dict:
        """Identify support and resistance levels from option OI concentration.

        Resistance: strikes with the highest call OI — writers defend these levels.
        Support:    strikes with the highest put  OI — writers defend these levels.

        Returns nearest support below spot and nearest resistance above spot.

        Args:
            symbol: 'NIFTY' or 'BANKNIFTY' (default 'NIFTY').
            expiry: Expiry date string. Defaults to nearest expiry.
            top_n: Number of levels to surface per side (default 5).
        """
        chain, resolved = _fetch(symbol, expiry)
        return analytics.identify_support_resistance_from_oi(chain, resolved, top_n)

    @mcp.tool()
    def calculate_max_pain(
        symbol: str = "NIFTY",
        expiry: Optional[str] = None,
    ) -> dict:
        """Calculate the max pain strike for an index option expiry.

        Max pain is the strike where the aggregate in-the-money value of all
        options (loss to buyers, gain to writers) is minimised. The index
        historically gravitates toward this level as expiry approaches.

        Args:
            symbol: 'NIFTY' or 'BANKNIFTY' (default 'NIFTY').
            expiry: Expiry date string. Defaults to nearest expiry.
        """
        chain, resolved = _fetch(symbol, expiry)
        return analytics.calculate_max_pain(chain, resolved)
