from typing import Optional

from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.market.symbols import normalize_symbol_extended as _norm
from src.market.symbols import parse as _parse
from src.options import analytics
from src.options.bse_service import get_bse_options_service
from src.options.service import get_options_service


def register(mcp: FastMCP) -> None:

    # ------------------------------------------------------------------
    # Internal helpers (not MCP tools)
    # ------------------------------------------------------------------

    def _fetch(symbol: str, expiry: Optional[str]) -> tuple[dict, Optional[str]]:
        svc = get_options_service()
        metadata = svc.get_option_chain(symbol)
        available = metadata.get("records", {}).get("expiryDates", [])
        resolved = expiry if expiry in available else (available[0] if available else None)
        chain = svc.get_option_chain(symbol, resolved)
        return chain, resolved

    def _fetch_bse(symbol: str, expiry: Optional[str]) -> tuple[dict, Optional[str]]:
        svc = get_bse_options_service()
        metadata = svc.get_option_chain(symbol)
        available = metadata.get("records", {}).get("expiryDates", [])
        resolved = expiry if expiry in available else (available[0] if available else None)
        chain = svc.get_option_chain(symbol, resolved)
        return chain, resolved

    def _format_chain(chain: dict, symbol: str, expiry: Optional[str], atm_range: int) -> dict:
        records = chain.get("records", {})
        spot = records.get("underlyingValue")
        expiry_dates = records.get("expiryDates", [])
        data: list[dict] = records.get("data", [])

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
            "symbol":             symbol,
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
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "get_expiries")
        nse_sym = _parse(symbol.strip())[1].upper().removesuffix(".NS").removesuffix(".BO")
        expiries = get_options_service().available_expiries(nse_sym)
        return {
            "symbol": nse_sym,
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
    def get_sensex_option_chain(
        expiry: Optional[str] = None,
        atm_range: int = 20,
    ) -> dict:
        """Fetch the SENSEX index option chain from BSE.

        Returns per-strike CE/PE open interest, volume, implied volatility,
        last traded price, bid, and ask. No authentication required.

        Args:
            expiry: Expiry date as shown on BSE, e.g. '25 Jun 2026'.
                    Defaults to the nearest weekly/monthly expiry.
            atm_range: Number of strikes above and below ATM to return.
                       Set to 0 to return all strikes.
        """
        chain, resolved = _fetch_bse("SENSEX", expiry)
        return _format_chain(chain, "SENSEX", resolved, atm_range)

    @mcp.tool()
    def get_bankex_option_chain(
        expiry: Optional[str] = None,
        atm_range: int = 20,
    ) -> dict:
        """Fetch the BANKEX index option chain from BSE.

        Returns per-strike CE/PE open interest, volume, implied volatility,
        last traded price, bid, and ask. No authentication required.

        Args:
            expiry: Expiry date as shown on BSE, e.g. '25 Jun 2026'.
                    Defaults to the nearest weekly/monthly expiry.
            atm_range: Number of strikes above and below ATM to return.
                       Set to 0 to return all strikes.
        """
        chain, resolved = _fetch_bse("BANKEX", expiry)
        return _format_chain(chain, "BANKEX", resolved, atm_range)

    @mcp.tool()
    def get_equity_option_chain(
        symbol: str,
        expiry: Optional[str] = None,
        atm_range: int = 10,
    ) -> dict:
        """Fetch the NSE equity option chain for any F&O stock.

        Returns per-strike CE/PE open interest, volume, implied volatility,
        last traded price, bid, and ask. No authentication required.

        Works for any NSE-listed equity with an active F&O segment:
        RELIANCE, INFY, TCS, SBIN, HDFC, ICICIBANK, etc.

        Args:
            symbol:    NSE equity symbol — e.g. 'RELIANCE' or 'NSE:RELIANCE'.
            expiry:    Expiry date as shown on NSE, e.g. '30-Jun-2026'.
                       Defaults to the nearest monthly expiry.
            atm_range: Number of strikes above and below ATM to return (default 10).
                       Set to 0 to return all strikes.
        """
        sym, corrected, fmt = _norm(symbol, "get_equity_option_chain")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "get_equity_option_chain")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        nse_sym = _parse(symbol.strip())[1].upper().removesuffix(".NS").removesuffix(".BO")
        chain, resolved = _fetch(nse_sym, expiry)
        return _format_chain(chain, nse_sym, resolved, atm_range)

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
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "calculate_pcr")
        nse_sym = _parse(symbol.strip())[1].upper().removesuffix(".NS").removesuffix(".BO")
        chain, resolved = _fetch(nse_sym, expiry)
        return analytics.calculate_pcr(chain, resolved)

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
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "calculate_max_pain")
        nse_sym = _parse(symbol.strip())[1].upper().removesuffix(".NS").removesuffix(".BO")
        chain, resolved = _fetch(nse_sym, expiry)
        return analytics.calculate_max_pain(chain, resolved)

    @mcp.tool()
    def get_option_chain_depth(
        symbol: str = "NIFTY",
        expiry: Optional[str] = None,
        atm_range: int = 10,
    ) -> dict:
        """Per-strike option chain depth with summary analytics.

        Returns per-strike call_oi, put_oi, oi_change, volume, iv, ltp for
        strikes within atm_range of ATM. Summary includes ATM strike,
        max_pain, pcr_oi, pcr_volume.

        Facts only — no signals, no confidence scores, no interpretations.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', or any NSE F&O equity symbol.
            expiry: Expiry date string (e.g. '27-Jun-2024'). Defaults to nearest.
            atm_range: Number of strikes above and below ATM to return (default 10).
                       Set to 0 to return all strikes.
        """
        sym, corrected, fmt = _norm(symbol, "get_option_chain_depth")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "get_option_chain_depth")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        nse_sym = _parse(symbol.strip())[1].upper().removesuffix(".NS").removesuffix(".BO")

        data: dict[str, object]
        try:
            svc = get_options_service()
            chain = svc.get_option_chain(nse_sym, expiry)
        except Exception as exc:
            data = {"error": str(exc), "symbol": nse_sym}
            m = _meta.build_meta(
                type_=_meta.TYPE_FACT,
                validation_status=_meta.VALIDATION_VERIFIED,
                data_quality=_meta.DQ_INVALID,
                source="NSE",
                account_type="MARKET_DATA_ONLY",
                **_norm_kw,
            )
            return _meta.wrap(data, m)

        records = chain.get("records", {})
        spot = records.get("underlyingValue")
        expiry_dates = records.get("expiryDates", [])
        resolved = expiry if expiry in expiry_dates else (expiry_dates[0] if expiry_dates else None)

        rows = analytics._strikes_for_expiry(chain, resolved)
        all_strikes: list[float] = sorted({
            float(r["strikePrice"]) for r in rows if r.get("strikePrice") is not None
        })

        # ATM = strike closest to spot
        atm_strike: float | None = None
        if spot and all_strikes:
            atm_strike = min(all_strikes, key=lambda s: abs(s - spot))

        # Filter to ±atm_range strikes around ATM
        if atm_range > 0 and atm_strike is not None and all_strikes:
            atm_idx = all_strikes.index(atm_strike)
            lo = max(0, atm_idx - atm_range)
            hi = min(len(all_strikes) - 1, atm_idx + atm_range)
            range_set = set(all_strikes[lo : hi + 1])
            filtered = [r for r in rows if r.get("strikePrice") in range_set]
        else:
            filtered = rows

        strikes_data = []
        for row in filtered:
            ce = row.get("CE") or {}
            pe = row.get("PE") or {}
            strikes_data.append({
                "strike": row.get("strikePrice"),
                "call_oi": ce.get("openInterest"),
                "call_oi_change": ce.get("changeinOpenInterest"),
                "call_volume": ce.get("totalTradedVolume"),
                "call_iv": ce.get("impliedVolatility"),
                "call_ltp": ce.get("lastPrice"),
                "put_oi": pe.get("openInterest"),
                "put_oi_change": pe.get("changeinOpenInterest"),
                "put_volume": pe.get("totalTradedVolume"),
                "put_iv": pe.get("impliedVolatility"),
                "put_ltp": pe.get("lastPrice"),
            })

        pcr = analytics.calculate_pcr(chain, resolved)
        mp = analytics.calculate_max_pain(chain, resolved)

        data = {
            "symbol": nse_sym,
            "spot": spot,
            "expiry": resolved,
            "atm_strike": atm_strike,
            "strikes": strikes_data,
            "summary": {
                "atm_strike": atm_strike,
                "max_pain": mp.get("max_pain"),
                "pcr_oi": pcr.get("pcr_oi"),
                "pcr_volume": pcr.get("pcr_volume"),
            },
            "limitations": [
                "oi_change is per-session intraday only, not absolute.",
                "IV sourced from NSE intraday trade data — not a standardised model.",
                "Data cached 60 s by options service.",
            ],
        }

        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID if strikes_data else _meta.DQ_INVALID,
            source="NSE",
            account_type="MARKET_DATA_ONLY",
            stale_threshold_seconds=60,
            **_norm_kw,
        )
        return _meta.wrap(data, m)

