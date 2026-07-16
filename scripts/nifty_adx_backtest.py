#!/usr/bin/env python3
"""
NIFTY 15-minute ADX/DI options backtest (simulated CE/PE long trades).
=======================================================================

STRATEGY
--------
On 15-minute candles of the NIFTY 50 index:
  * Compute ADX(14), +DI(14), -DI(14) with standard Wilder smoothing.
  * Enter a simulated LONG CALL (CE) when  ADX >= 25 AND +DI > -DI.
  * Enter a simulated LONG PUT  (PE) when  ADX >= 25 AND -DI > +DI.
  * All days eligible, including expiry day. No weekday filter.
  * Only one open trade at a time.
  * Exit: stop loss at 30% adverse move, target at 50% favourable move,
    on the OPTION PREMIUM, whichever hits first.

CRITICAL DATA LIMITATION (read this before trusting any number below)
---------------------------------------------------------------------
This backtest does NOT use real historical option premiums, because no
free/available source provides intraday NIFTY options premium history:

  * yfinance:            no historical intraday options chain at all.
  * INDmoney/INDstocks:  option chain + Greeks endpoints are hard
                         "coming soon" stubs (verified in this repo at
                         src/brokers/indmoney.py::get_option_chain /
                         get_greeks — both return {"status":
                         "not_available"}). It exposes UNDERLYING
                         historical OHLC only, and even that is capped at
                         ~7 days per request for 15-minute candles.

Therefore option P&L is APPROXIMATED from the underlying's point move:

    premium_move ≈ underlying_point_move * DELTA   (DELTA assumed 0.5)

For a CE, a +X point move in NIFTY approximates a +0.5*X premium move.
For a PE, a -X point move in NIFTY approximates a +0.5*X premium move.
The 30% SL / 50% target are then applied to a nominal starting premium.

This is a SIMPLIFICATION and will NOT match live results. It ignores:
theta decay, IV changes (vega), gamma (delta is not constant — an ATM
option's delta drifts far from 0.5 as it moves ITM/OTM), the bid/ask
spread, and strike selection. Treat the output as a signal-quality
sanity check on the ADX/DI entry rule, NOT as a tradeable P&L estimate.

DATA SOURCE RECOMMENDATION
--------------------------
For the UNDERLYING signal: use yfinance (^NSEI). It needs no auth, and
returns roughly the last 60 days of 15-minute candles in one call.
INDmoney would require a token, chunked 7-day requests, and has a
repo-documented parsing bug (2026-07-16) on its historical endpoint.
Neither source gives you real options premiums — that gap is the same
either way, so pick the underlying source that's simplest: yfinance.

UPSTOX (--source upstox) — REAL option premium history, WITH A CATCH
----------------------------------------------------------------------
Upstox's expired-instruments API can supply genuine historical premium
candles for a specific expired option contract:

  1. GET /v2/expired-instruments/option/contract
     ?instrument_key={underlying}&expiry_date={YYYY-MM-DD}
     -> resolves the contract's own instrument_key + strike/CE/PE for a
        given underlying + expiry (confirmed via Upstox's public docs,
        2026-07-17).
  2. GET /v2/expired-instruments/historical-candle/
     {expired_instrument_key}/{interval}/{to_date}/{from_date}
     -> real OHLCV(+OI) candles for that exact option contract.
     Path order is instrument_key, interval, to_date, from_date (NOT
     from/to — confirmed from Upstox's own example URL).
     Candle array order: [timestamp, open, high, low, close, volume,
     open_interest].

THE CATCH (confirmed on Upstox's own docs page, 2026-07-17):
  "This API is available exclusively with an Upstox Plus plan
  subscription." A free/standard Upstox API key will likely get a 401/
  403 on step 2 regardless of how correct this code is. This script
  cannot tell you whether your account has Plus until you actually run
  it — see the reported HTTP status if it fails.

Even with Plus access, this only replaces the delta approximation for
whichever SPECIFIC strike+expiry is resolved at each entry signal (the
nearest-ITM/ATM strike, current-week expiry, at signal time) — it is
real traded premium for that one contract, not a full option chain.

USAGE
-----
    pip install yfinance pandas
    python nifty_adx_backtest.py                     # yfinance (default)
    python nifty_adx_backtest.py --source indmoney    # needs INDSTOCKS_TOKEN
    export UPSTOX_ACCESS_TOKEN='...'                  # set in YOUR shell, never in code
    python nifty_adx_backtest.py --source upstox --from-date 2024-11-01 --to-date 2024-11-27

The INDmoney path is included to answer "can it be done", is honest about
its limits, and is clearly flagged where it is unverified.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from dataclasses import dataclass, field

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required:  pip install pandas")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ADX_PERIOD = 14
ADX_THRESHOLD = 25.0
STOP_LOSS_PCT = 0.30          # 30% adverse move on premium -> exit
TARGET_PCT = 0.50             # 50% favourable move on premium -> exit
ASSUMED_DELTA = 0.5           # SIMPLIFICATION — see module docstring
NOMINAL_ENTRY_PREMIUM = 100.0  # arbitrary premium base for % SL/target math
NIFTY_LOT_SIZE = 65           # rupees P&L = premium_points * lot_size

UPSTOX_BASE = "https://api.upstox.com/v2"
UPSTOX_NIFTY_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"
UPSTOX_STRIKE_STEP = 50   # NIFTY strikes are in steps of 50


# ---------------------------------------------------------------------------
# Indicators — Wilder's ADX / +DI / -DI
# ---------------------------------------------------------------------------

def wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (RMA): alpha = 1/period, seeded on the first
    full window. This is the smoothing ADX is canonically defined with —
    NOT a simple or standard EMA."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    """Add adx, plus_di, minus_di columns using standard Wilder method.

    Expects columns: high, low, close. Returns a copy.
    """
    out = df.copy()
    high, low, close = out["high"], out["low"], out["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move.clip(lower=0)

    atr = wilder_rma(tr, period)
    plus_di = 100.0 * wilder_rma(plus_dm, period) / atr
    minus_di = 100.0 * wilder_rma(minus_dm, period) / atr

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = wilder_rma(dx, period)

    out["plus_di"] = plus_di
    out["minus_di"] = minus_di
    out["adx"] = adx
    return out


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_yfinance() -> pd.DataFrame:
    """~60 days of 15m ^NSEI candles. No auth. The practical default.

    yfinance intraday history limits: 15m data is only available for
    roughly the last 60 days, and only in <=60-day request windows. You
    cannot backtest years of intraday data this way — that's a hard
    Yahoo limitation, not a code choice.
    """
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance is required for the default source:  pip install yfinance")

    raw = yf.download(
        "^NSEI", period="60d", interval="15m",
        auto_adjust=False, progress=False,
    )
    if raw is None or raw.empty:
        sys.exit("yfinance returned no data for ^NSEI (rate limited, or "
                 "market-data outage). Retry, or use --source indmoney.")

    # yfinance may return a MultiIndex column frame for a single ticker.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.rename(columns=str.lower)[["open", "high", "low", "close"]].copy()
    df.index.name = "datetime"
    return df.dropna()


def load_indmoney() -> pd.DataFrame:
    """INDmoney/INDstocks 15m candles for the underlying NIFTY index.

    HONEST STATUS (verified against this repo's own client,
    src/brokers/indmoney.py):
      * Endpoint:  GET https://api.indstocks.com/market/historical/15minute
                   ?scrip-codes=<TOKEN>&start_time=<ms>&end_time=<ms>
      * Auth:      Authorization: Bearer <INDSTOCKS_TOKEN> header.
      * Limit:     ~7 days per request for 15m — long ranges need chunking
                   (this demo fetches a single recent 7-day window only).
      * Response shape is UNCONFIRMED against a real body; the repo assumes
                   [ts_ms, open, high, low, close, volume] rows and has a
                   logged parsing bug (2026-07-16). If parsing yields zero
                   rows, that's the known issue — fall back to yfinance.
      * Options:   NO historical option premium/chain data exists here
                   (get_option_chain/get_greeks are "coming soon" stubs),
                   so this only feeds the underlying signal, never P&L.
    """
    import time
    try:
        import httpx
    except ImportError:
        sys.exit("httpx is required for --source indmoney:  pip install httpx")

    token = os.environ.get("INDSTOCKS_TOKEN")
    if not token:
        sys.exit("Set INDSTOCKS_TOKEN to use --source indmoney. (And note: "
                 "even with it, only ~7 days of 15m underlying data is "
                 "fetched here, and options premium history is unavailable.)")

    # NIFTY 50 index scrip token in INDstocks SEGMENT_TOKEN form. This is a
    # PLACEHOLDER — resolve the real token from GET /market/instruments
    # ?source=index before relying on it. Left explicit so it fails loudly
    # rather than silently backtesting the wrong instrument.
    nifty_token = os.environ.get("INDSTOCKS_NIFTY_TOKEN", "NSE_NIFTY_50")

    now_ms = int(time.time() * 1000)
    seven_days_ms = 7 * 24 * 60 * 60 * 1000
    params = {
        "scrip-codes": nifty_token,
        "start_time": now_ms - seven_days_ms,
        "end_time": now_ms,
    }
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://api.indstocks.com/market/historical/15minute"

    with httpx.Client(timeout=15) as client:
        r = client.get(url, headers=headers, params=params)
    if r.status_code != 200:
        sys.exit(f"INDmoney historical returned HTTP {r.status_code}: "
                 f"{r.text[:200]}")

    raw = r.json()
    rows = raw if isinstance(raw, list) else raw.get("data", [])
    records = []
    for c in rows:
        if isinstance(c, list) and len(c) >= 5:
            records.append({
                "datetime": pd.to_datetime(c[0], unit="ms"),
                "open": c[1], "high": c[2], "low": c[3], "close": c[4],
            })
    if not records:
        sys.exit("INDmoney returned a body but zero candles parsed — this is "
                 "the known unconfirmed-shape / 2026-07-16 parsing bug. Use "
                 "the yfinance source instead.")

    df = pd.DataFrame(records).set_index("datetime").sort_index()
    return df[["open", "high", "low", "close"]].dropna()


# ---------------------------------------------------------------------------
# Upstox — real historical option premium (expired-instruments API)
# ---------------------------------------------------------------------------

class UpstoxDataSource:
    """Resolves an expired option contract's instrument_key and fetches
    REAL historical premium candles for it.

    API contract confirmed against Upstox's public developer docs
    (upstox.com/developer/api-documentation, fetched 2026-07-17):

      1. GET /v2/expired-instruments/option/contract
         ?instrument_key={underlying}&expiry_date={YYYY-MM-DD}
         -> {"status": "...", "data": [{instrument_key, strike_price,
             instrument_type ("CE"/"PE"), expiry, ...}, ...]}

      2. GET /v2/expired-instruments/historical-candle/
         {expired_instrument_key}/{interval}/{to_date}/{from_date}
         -> {"status": "...", "data": {"candles": [[timestamp, open,
             high, low, close, volume, open_interest], ...]}}
         interval in {1minute, 3minute, 5minute, 15minute, 30minute, day}.

    UNCONFIRMED / NOT INDEPENDENTLY VERIFIED: this class's request shapes
    match Upstox's documentation pages exactly, but have NOT been tested
    against a live Upstox account by this codebase before now — the docs
    could be stale or the real response could differ. Treat the first
    real run as the actual verification, not this code.

    CONFIRMED PAYWALL (from the same docs page): "This API is available
    exclusively with an Upstox Plus plan subscription." A non-Plus token
    will likely fail step 2 with 401/403 regardless of correctness here.
    """

    def __init__(self) -> None:
        token = os.environ.get("UPSTOX_ACCESS_TOKEN")
        if not token:
            sys.exit(
                "UPSTOX_ACCESS_TOKEN is not set. Set it in YOUR shell "
                "(never pass it to an assistant or hardcode it):\n"
                "  export UPSTOX_ACCESS_TOKEN='...'\n"
                "then re-run with --source upstox."
            )
        self._token = token

        try:
            import httpx
        except ImportError:
            sys.exit("httpx is required for --source upstox:  pip install httpx")
        self._httpx = httpx

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    def _get(self, url: str, params: dict | None = None):
        with self._httpx.Client(timeout=20) as client:
            r = client.get(url, headers=self._headers(), params=params)
        return r

    def get_expired_option_contracts(self, expiry_date: str) -> list[dict]:
        """Step 1: resolve every strike/CE-PE instrument_key for one expiry.

        expiry_date: "YYYY-MM-DD". Returns the raw list of contract dicts
        from Upstox's `data` field (each has instrument_key, strike_price,
        instrument_type, expiry, ...).
        """
        url = f"{UPSTOX_BASE}/expired-instruments/option/contract"
        r = self._get(url, params={
            "instrument_key": UPSTOX_NIFTY_INSTRUMENT_KEY,
            "expiry_date": expiry_date,
        })
        if r.status_code == 401 or r.status_code == 403:
            sys.exit(
                f"Upstox contract lookup returned HTTP {r.status_code} for "
                f"expiry {expiry_date}. This endpoint requires an Upstox "
                f"Plus plan subscription — if your account doesn't have "
                f"one, this is expected, not a bug in this script. "
                f"Body: {r.text[:300]}"
            )
        if r.status_code != 200:
            sys.exit(f"Upstox contract lookup HTTP {r.status_code} for "
                     f"expiry {expiry_date}: {r.text[:300]}")
        body = r.json()
        data = body.get("data", [])
        if not data:
            sys.exit(f"Upstox returned zero contracts for expiry "
                     f"{expiry_date} — either no expiry existed on that "
                     f"date, or the instrument_key/date format is wrong.")
        return data

    def pick_contract(self, contracts: list[dict], spot: float,
                      side: str) -> dict:
        """Pick the nearest-ATM strike of the requested side (CE/PE) from
        an already-fetched contract list for one expiry."""
        candidates = [c for c in contracts if c.get("instrument_type") == side]
        if not candidates:
            sys.exit(f"No {side} contracts found in the fetched expiry "
                     f"list — check the expiry_date used for lookup.")
        return min(candidates, key=lambda c: abs(float(c["strike_price"]) - spot))

    def get_historical_candles(self, expired_instrument_key: str,
                               from_date: str, to_date: str,
                               interval: str = "15minute") -> pd.DataFrame:
        """Step 2: real OHLCV(+OI) candles for one resolved option contract.

        Path order is instrument_key, interval, to_date, from_date — this
        matches Upstox's own documented example URL exactly; it is NOT
        from_date-then-to_date, which is easy to get backwards.
        """
        key_enc = urllib.parse.quote(expired_instrument_key, safe="")
        url = (f"{UPSTOX_BASE}/expired-instruments/historical-candle/"
               f"{key_enc}/{interval}/{to_date}/{from_date}")
        r = self._get(url)
        if r.status_code in (401, 403):
            sys.exit(
                f"Upstox historical-candle returned HTTP {r.status_code} "
                f"for {expired_instrument_key}. Per Upstox's docs, this "
                f"endpoint requires an Upstox Plus plan subscription — "
                f"if your account is on the free/standard tier, this "
                f"confirms the delta-approximation cannot be eliminated "
                f"without upgrading. Body: {r.text[:300]}"
            )
        if r.status_code != 200:
            sys.exit(f"Upstox historical-candle HTTP {r.status_code} for "
                     f"{expired_instrument_key}: {r.text[:300]}")

        body = r.json()
        candles = body.get("data", {}).get("candles", [])
        if not candles:
            return pd.DataFrame(columns=["open", "high", "low", "close",
                                         "volume", "oi"])

        records = []
        for c in candles:
            if len(c) >= 5:
                records.append({
                    "datetime": pd.to_datetime(c[0]),
                    "open": float(c[1]), "high": float(c[2]),
                    "low": float(c[3]), "close": float(c[4]),
                    "volume": float(c[5]) if len(c) > 5 else 0.0,
                    "oi": float(c[6]) if len(c) > 6 else 0.0,
                })
        df = pd.DataFrame(records).set_index("datetime").sort_index()
        return df


def load_yfinance_underlying_for_upstox() -> pd.DataFrame:
    """The upstox path still needs the NIFTY underlying to compute the
    ADX/DI entry signal and to pick the nearest-ATM strike — reuses the
    plain yfinance loader rather than duplicating it."""
    return load_yfinance()


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    entry_time: object
    side: str            # "CE" or "PE"
    entry_underlying: float
    exit_time: object = None
    exit_underlying: float = None
    exit_reason: str = ""
    premium_pnl_points: float = 0.0   # in premium points (approx, or REAL for --source upstox)
    contract: str = ""   # populated only by run_backtest_upstox; empty means delta-approximated


@dataclass
class Result:
    trades: list = field(default_factory=list)

    def add(self, t: Trade) -> None:
        self.trades.append(t)


def run_backtest(df: pd.DataFrame) -> Result:
    """One-position-at-a-time simulation.

    Option premium is modelled as: an entry premium of NOMINAL_ENTRY_PREMIUM,
    moving by (underlying_move * ASSUMED_DELTA) in the option's favour. We
    exit when that modelled premium hits +TARGET_PCT or -STOP_LOSS_PCT of
    the entry premium. This is the delta-0.5 simplification, flagged loudly
    in the module docstring — it is NOT real premium data.
    """
    res = Result()
    df = compute_adx(df)

    open_trade: Trade | None = None
    entry_prem = NOMINAL_ENTRY_PREMIUM
    target_prem = entry_prem * (1 + TARGET_PCT)
    stop_prem = entry_prem * (1 - STOP_LOSS_PCT)

    for ts, row in df.iterrows():
        if pd.isna(row["adx"]):
            continue  # warm-up period, indicators not yet valid

        if open_trade is None:
            # Look for an entry signal.
            if row["adx"] >= ADX_THRESHOLD:
                if row["plus_di"] > row["minus_di"]:
                    open_trade = Trade(ts, "CE", row["close"])
                elif row["minus_di"] > row["plus_di"]:
                    open_trade = Trade(ts, "PE", row["close"])
            continue

        # Manage the open trade against this candle's move.
        move = row["close"] - open_trade.entry_underlying
        signed = move if open_trade.side == "CE" else -move  # favourable dir
        modelled_prem = entry_prem + signed * ASSUMED_DELTA

        exit_reason = None
        if modelled_prem >= target_prem:
            exit_reason = "TARGET"
        elif modelled_prem <= stop_prem:
            exit_reason = "STOP"

        if exit_reason:
            open_trade.exit_time = ts
            open_trade.exit_underlying = row["close"]
            open_trade.exit_reason = exit_reason
            open_trade.premium_pnl_points = modelled_prem - entry_prem
            res.add(open_trade)
            open_trade = None

    # Close any still-open trade at the last candle (mark-to-market).
    if open_trade is not None:
        last = df.iloc[-1]
        move = last["close"] - open_trade.entry_underlying
        signed = move if open_trade.side == "CE" else -move
        open_trade.exit_time = df.index[-1]
        open_trade.exit_underlying = last["close"]
        open_trade.exit_reason = "EOD_CLOSE"
        open_trade.premium_pnl_points = signed * ASSUMED_DELTA
        res.add(open_trade)

    return res


def _nearest_weekly_expiry(ts, expiries: list[str]) -> str | None:
    """Pick the nearest expiry on/after ts from a list of 'YYYY-MM-DD'
    strings. Returns None if every expiry in the list is before ts."""
    ts_date = pd.Timestamp(ts).normalize()
    candidates = [e for e in expiries if pd.Timestamp(e) >= ts_date]
    if not candidates:
        return None
    return min(candidates, key=lambda e: pd.Timestamp(e))


def run_backtest_upstox(underlying_df: pd.DataFrame, expiries: list[str],
                        upstox: "UpstoxDataSource") -> Result:
    """Same ADX/DI entry rule as run_backtest(), but exits are evaluated
    against REAL historical option premium fetched from Upstox for the
    specific nearest-ATM contract of the nearest expiry at signal time —
    NOT the delta-0.5 approximation.

    Caveats, so the numbers are read correctly:
      * One Upstox contract-list + candle fetch per trade (not batched),
        since the strike/expiry picked depends on the underlying price
        AT the moment of each signal — this is slower and makes more API
        calls than the yfinance/indmoney paths, by design.
      * If Upstox has no candle data at the exact entry timestamp (e.g.
        a gap, or the option barely traded), the entry falls back to the
        nearest available candle at-or-after entry; if none exists in
        the fetched window at all, that signal is skipped (logged, not
        silently dropped).
      * `expiries` must be pre-fetched expiry dates to search from (this
        script does not auto-discover the expiry calendar — see
        --from-date/--to-date and the printed expiry list at startup).
    """
    res = Result()
    df = compute_adx(underlying_df)

    open_trade: Trade | None = None
    entry_prem = None
    contract_df: pd.DataFrame | None = None
    contract_key = ""

    skipped_no_expiry = 0
    skipped_no_data = 0

    for ts, row in df.iterrows():
        if pd.isna(row["adx"]):
            continue

        if open_trade is None:
            side = None
            if row["adx"] >= ADX_THRESHOLD:
                if row["plus_di"] > row["minus_di"]:
                    side = "CE"
                elif row["minus_di"] > row["plus_di"]:
                    side = "PE"
            if side is None:
                continue

            expiry = _nearest_weekly_expiry(ts, expiries)
            if expiry is None:
                skipped_no_expiry += 1
                continue

            contracts = upstox.get_expired_option_contracts(expiry)
            picked = upstox.pick_contract(contracts, row["close"], side)
            contract_key = picked["instrument_key"]

            # Fetch this contract's own candles for its whole trading life
            # up to the underlying data's end — one fetch per trade.
            from_date = df.index[0].strftime("%Y-%m-%d")
            to_date = expiry
            contract_df = upstox.get_historical_candles(
                contract_key, from_date=from_date, to_date=to_date,
                interval="15minute",
            )
            if contract_df.empty:
                skipped_no_data += 1
                contract_df = None
                continue

            at_or_after = contract_df.loc[contract_df.index >= ts]
            if at_or_after.empty:
                skipped_no_data += 1
                contract_df = None
                continue

            entry_row = at_or_after.iloc[0]
            entry_prem = float(entry_row["close"])
            open_trade = Trade(entry_row.name, side, row["close"],
                              contract=contract_key)
            continue

        # Manage the open trade against this contract's OWN real candles.
        if contract_df is None:
            continue
        window = contract_df.loc[contract_df.index >= open_trade.entry_time]
        window = window.loc[window.index <= ts]
        if window.empty:
            continue
        last_prem = float(window.iloc[-1]["close"])

        target_prem = entry_prem * (1 + TARGET_PCT)
        stop_prem = entry_prem * (1 - STOP_LOSS_PCT)

        exit_reason = None
        if last_prem >= target_prem:
            exit_reason = "TARGET"
        elif last_prem <= stop_prem:
            exit_reason = "STOP"

        if exit_reason:
            open_trade.exit_time = window.index[-1]
            open_trade.exit_underlying = row["close"]
            open_trade.exit_reason = exit_reason
            open_trade.premium_pnl_points = last_prem - entry_prem
            res.add(open_trade)
            open_trade, entry_prem, contract_df = None, None, None

    if open_trade is not None and contract_df is not None and not contract_df.empty:
        last_prem = float(contract_df.iloc[-1]["close"])
        open_trade.exit_time = contract_df.index[-1]
        open_trade.exit_underlying = df.iloc[-1]["close"]
        open_trade.exit_reason = "EOD_CLOSE"
        open_trade.premium_pnl_points = last_prem - entry_prem
        res.add(open_trade)

    if skipped_no_expiry or skipped_no_data:
        print(f"(upstox: skipped {skipped_no_expiry} signal(s) with no "
              f"expiry in range, {skipped_no_data} signal(s) with no "
              f"contract candle data available)")

    return res


# ---------------------------------------------------------------------------
# Metrics + reporting
# ---------------------------------------------------------------------------

def report(res: Result, real_premium: bool = False) -> None:
    trades = res.trades
    if not trades:
        print("No trades generated. (ADX never crossed the threshold in the "
              "available window, or the data window was too short after the "
              "indicator warm-up period.)")
        return

    pnl = [t.premium_pnl_points for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]

    total_points = sum(pnl)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss else float("inf")

    # Max drawdown on the cumulative premium-points equity curve.
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnl:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    print("=" * 68)
    print("NIFTY 15m ADX/DI OPTIONS BACKTEST — RESULTS")
    print("=" * 68)
    if real_premium:
        print("Option P&L uses REAL historical premium candles from Upstox")
        print("for the specific nearest-ATM contract resolved at each entry.")
    else:
        print("!! Option P&L is a delta-0.5 APPROXIMATION from the underlying,")
        print("!! not real premium data. See the script's module docstring.")
    print("-" * 68)
    print(f"Total trades      : {len(trades)}")
    print(f"Wins / Losses     : {len(wins)} / {len(losses)}")
    print(f"Win rate          : {100.0 * len(wins) / len(trades):.1f}%")
    tag = "" if real_premium else " (approx)"
    print(f"Total P&L (points): {total_points:+.1f} premium points{tag}")
    print(f"Total P&L (approx): Rs {total_points * NIFTY_LOT_SIZE:+,.0f} "
          f"(x{NIFTY_LOT_SIZE} lot, 1 lot, before costs)")
    print(f"Max drawdown      : {max_dd:.1f} premium points "
          f"(Rs {max_dd * NIFTY_LOT_SIZE:,.0f})")
    print(f"Profit factor     : {profit_factor:.2f}")
    print("-" * 68)
    print("TRADE LOG")
    print("-" * 68)
    if real_premium:
        hdr = (f"{'Entry':<20}{'Side':<5}{'Exit':<20}{'Reason':<10}"
               f"{'P&L pts':>9}  {'Contract'}")
    else:
        hdr = f"{'Entry':<20}{'Side':<5}{'Exit':<20}{'Reason':<10}{'P&L pts':>9}"
    print(hdr)
    for t in trades:
        et = str(t.entry_time)[:19]
        xt = str(t.exit_time)[:19]
        line = (f"{et:<20}{t.side:<5}{xt:<20}{t.exit_reason:<10}"
               f"{t.premium_pnl_points:>+9.1f}")
        if real_premium:
            line += f"  {t.contract}"
        print(line)
    print("=" * 68)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["yfinance", "indmoney", "upstox"],
                    default="yfinance",
                    help="Underlying data source (default: yfinance). "
                         "indmoney needs INDSTOCKS_TOKEN and gives only ~7 "
                         "days of 15m data with no options premium history. "
                         "upstox needs UPSTOX_ACCESS_TOKEN + an Upstox Plus "
                         "plan, and replaces the delta-approx P&L with real "
                         "historical option premiums.")
    ap.add_argument("--expiries", type=str, default="",
                    help="Comma-separated list of NIFTY weekly/monthly "
                         "expiry dates (YYYY-MM-DD) to search for contracts "
                         "during the backtest window. Required for "
                         "--source upstox — this script does not "
                         "auto-discover the expiry calendar. Example: "
                         "2024-11-07,2024-11-14,2024-11-21,2024-11-28")
    args = ap.parse_args()

    if args.source == "upstox":
        if not args.expiries:
            sys.exit("--source upstox requires --expiries "
                     "(comma-separated YYYY-MM-DD list).")
        expiries = [e.strip() for e in args.expiries.split(",") if e.strip()]

        print("Loading NIFTY 15m underlying candles from yfinance "
              "(needed for the ADX/DI signal and strike selection)...")
        underlying_df = load_yfinance_underlying_for_upstox()
        print(f"Loaded {len(underlying_df)} underlying candles "
              f"({underlying_df.index[0]} -> {underlying_df.index[-1]}).\n")

        print("Connecting to Upstox for real option premium data...")
        upstox = UpstoxDataSource()

        print(f"Running backtest with REAL Upstox premiums across "
              f"{len(expiries)} candidate expiry date(s): {expiries}\n")
        res = run_backtest_upstox(underlying_df, expiries, upstox)
        report(res, real_premium=True)
        return

    print(f"Loading NIFTY 15m candles from: {args.source} ...")
    df = load_indmoney() if args.source == "indmoney" else load_yfinance()
    print(f"Loaded {len(df)} candles "
          f"({df.index[0]} -> {df.index[-1]}).\n")

    res = run_backtest(df)
    report(res)


if __name__ == "__main__":
    main()
