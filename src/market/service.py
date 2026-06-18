"""
Unified market-data service.

Resolution order per call:
  1. jugaad-data NSELive  — real-time NSE data, free, no auth (NSE stocks only)
  2. yfinance             — Yahoo Finance fallback (BSE, indices, historical)

Symbol formats accepted everywhere:
  NSE:INFY   BSE:RELIANCE   INFY.NS   ^NSEI   (pass-through yfinance tickers)
"""

import io
import logging
import math
import threading
from datetime import date, datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

_INDEX_YF: dict[str, str] = {
    "NIFTY 50": "^NSEI",
    "NIFTY50": "^NSEI",
    "SENSEX": "^BSESN",
    "BANKNIFTY": "^NSEBANK",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY IT": "^CNXIT",
    "NIFTY MIDCAP 100": "^CNXMIDCAP",
    "NIFTY MIDCAP": "^CNXMIDCAP",
}


def _parse(instrument: str) -> tuple[str | None, str]:
    """Return (exchange, symbol). exchange is None for raw yfinance tickers."""
    if ":" in instrument:
        exchange, sym = instrument.split(":", 1)
        return exchange.upper(), sym.upper()
    return None, instrument


def _to_yf(instrument: str) -> str:
    exchange, sym = _parse(instrument)
    if exchange is None:
        return instrument  # already in yfinance format
    if sym in _INDEX_YF:
        return _INDEX_YF[sym]
    if exchange == "NSE":
        return f"{sym}.NS"
    if exchange == "BSE":
        return f"{sym}.BO"
    return instrument


def _is_nse_stock(instrument: str) -> bool:
    exchange, sym = _parse(instrument)
    return exchange == "NSE" and sym not in _INDEX_YF


# ---------------------------------------------------------------------------
# NSELive (primary for live quotes)
# ---------------------------------------------------------------------------

_nse_live = None
_nse_lock = threading.Lock()


def _get_nse_live():
    global _nse_live
    with _nse_lock:
        if _nse_live is None:
            try:
                from jugaad_data.nse import NSELive  # type: ignore[import]
                _nse_live = NSELive()
            except ImportError:
                logger.warning("jugaad-data not installed; NSELive unavailable")
                _nse_live = False  # sentinel: tried and failed
    return _nse_live if _nse_live is not False else None


def _nse_quote_raw(symbol: str) -> dict | None:
    nse = _get_nse_live()
    if nse is None:
        return None
    try:
        return nse.stock_quote(symbol)
    except Exception as exc:
        logger.debug("NSELive.stock_quote(%s) failed: %s", symbol, exc)
        return None


def _nse_to_normalized(raw: dict, instrument: str) -> dict:
    pi = raw.get("priceInfo", {})
    hl = pi.get("intraDayHighLow", {})
    ti = raw.get("marketDeptOrderBook", {}).get("tradeInfo", {})
    return {
        "instrument": instrument,
        "last_price": pi.get("lastPrice"),
        "open": pi.get("open"),
        "high": hl.get("max"),
        "low": hl.get("min"),
        "close": pi.get("close"),
        "previous_close": pi.get("previousClose"),
        "change": pi.get("change"),
        "change_percent": pi.get("pChange"),
        "volume": ti.get("totalTradedVolume"),
        "source": "NSELive",
    }


# ---------------------------------------------------------------------------
# yfinance (fallback + historical)
# ---------------------------------------------------------------------------

def _yf_quote(yf_sym: str, instrument: str) -> dict:
    import yfinance as yf  # type: ignore[import]
    ticker = yf.Ticker(yf_sym)
    try:
        fi = ticker.fast_info
        return {
            "instrument": instrument,
            "last_price": getattr(fi, "last_price", None),
            "open": getattr(fi, "open", None),
            "high": getattr(fi, "day_high", None),
            "low": getattr(fi, "day_low", None),
            "close": None,
            "previous_close": getattr(fi, "previous_close", None),
            "change": None,
            "change_percent": None,
            "volume": getattr(fi, "last_volume", None),
            "source": "yfinance",
        }
    except (KeyError, Exception):
        # fast_info can fail when Yahoo Finance changes response schema;
        # fall back to history() which is more stable
        df = ticker.history(period="2d")
        if df.empty:
            return {"instrument": instrument, "last_price": None, "source": "yfinance"}
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None
        return {
            "instrument": instrument,
            "last_price": round(float(row["Close"]), 4),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "previous_close": round(float(prev["Close"]), 4) if prev is not None else None,
            "change": None,
            "change_percent": None,
            "volume": int(row["Volume"]),
            "source": "yfinance",
        }


def _serialize(obj: object) -> object:
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


# ---------------------------------------------------------------------------
# NSE instruments cache (equity list from public CSV)
# ---------------------------------------------------------------------------

_instruments: list[dict] = []
_instruments_lock = threading.Lock()
_NSE_EQUITY_CSV = (
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
)


def _load_nse_instruments() -> list[dict]:
    global _instruments
    with _instruments_lock:
        if _instruments:
            return _instruments
        try:
            import httpx  # type: ignore[import]
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.nseindia.com",
            }
            r = httpx.get(_NSE_EQUITY_CSV, headers=headers, timeout=15, follow_redirects=True)
            r.raise_for_status()
            import csv
            reader = csv.DictReader(io.StringIO(r.text))
            _instruments = [
                {
                    "tradingsymbol": row.get("SYMBOL", "").strip(),
                    "name": row.get("NAME OF COMPANY", "").strip(),
                    "exchange": "NSE",
                    "isin": row.get("ISIN NUMBER", "").strip(),
                    "series": row.get("SERIES", "").strip(),
                    "instrument_type": "EQ",
                }
                for row in reader
                if row.get("SYMBOL", "").strip()
            ]
            logger.info("Loaded %d NSE instruments", len(_instruments))
        except Exception as exc:
            logger.warning("Could not load NSE equity list: %s", exc)
    return _instruments


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------

class MarketService:
    """
    Unified market data. Tries NSELive first for live quotes;
    falls back to yfinance for BSE, indices, and historical data.
    """

    def get_quote(self, instrument: str) -> dict:
        if _is_nse_stock(instrument):
            _, sym = _parse(instrument)
            raw = _nse_quote_raw(sym)
            if raw:
                return _nse_to_normalized(raw, instrument)
        return _yf_quote(_to_yf(instrument), instrument)

    def get_ohlc(self, instrument: str) -> dict:
        q = self.get_quote(instrument)
        return {
            "instrument": instrument,
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "close": q["close"] or q["previous_close"],
            "last_price": q["last_price"],
            "source": q["source"],
        }

    def get_ltp(self, instrument: str) -> float:
        return self.get_quote(instrument)["last_price"]

    def get_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        interval: str,
    ) -> list[dict]:
        import yfinance as yf  # type: ignore[import]
        yf_sym = _to_yf(symbol)
        df = yf.download(
            yf_sym,
            start=from_date,
            end=to_date,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return []
        # yfinance 0.2.x returns MultiIndex columns when single ticker
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        records = []
        for ts, row in df.iterrows():
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
            if math.isnan(c) or math.isnan(o) or math.isnan(h) or math.isnan(l):
                continue
            vol_raw = float(row["Volume"])
            records.append({
                "date": ts.isoformat(),
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": int(vol_raw) if not math.isnan(vol_raw) else 0,
            })
        return records

    def search(self, query: str, exchange: str | None) -> list[dict]:
        q = query.lower()
        instruments = _load_nse_instruments()
        results = [
            inst for inst in instruments
            if q in inst["tradingsymbol"].lower() or q in inst["name"].lower()
            if exchange is None or inst["exchange"] == exchange.upper()
        ]
        return results[:50]

    def equity_list(self, exchange: str) -> list[dict]:
        exchange = exchange.upper()
        if exchange == "NSE":
            return _load_nse_instruments()
        raise ValueError(
            f"Free equity list is only available for NSE. "
            f"For {exchange}, use search() with exchange='{exchange}'."
        )

    def invalidate_instruments_cache(self) -> None:
        global _instruments
        with _instruments_lock:
            _instruments = []
