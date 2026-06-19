"""
Cross-Sectional Signal Screen — Phase 21 (cheap screen, pre Audit V2)

A deliberately crude, fast, falsifiable screen. It does NOT do confidence
intervals, bootstrap, Newey-West, or hypothesis testing. It asks one question:

    "Does a simple cross-sectional signal produce a LARGE forward excess return
     spread (top quintile minus bottom quintile) across Nifty 50 — large enough
     to matter to a retail trader after costs?"

Signals tested (ranked cross-sectionally each date, into quintiles):
  * RS_6m    — trailing 126-day return        (headline momentum)
  * RS_12m1  — 252-day return skipping last 21 (classic 12-1 momentum; robustness)
  * Vol_63   — 63-day realized volatility      (low-volatility anomaly)

Outcome measured: forward EXCESS return vs NIFTY (^NSEI), date-aligned.

Ranking note: trailing RAW return and trailing EXCESS return give identical
cross-sectional order (same benchmark window is a constant shift), so we rank on
raw trailing return and apply "excess" only to the forward outcome.

Decision thresholds (10d Q5-Q1 spread, in %):
  < 0.3%             -> below costs; KILL the signal
  0.3% - 0.8%        -> marginal-but-real; NOW Audit V2 rigor is justified
  > 0.8% (monotone)  -> large; justifies production work (paper-trade first)
  > 1.5%             -> SUSPECT a bug (lookahead / survivorship) before believing

Kill the directional-prediction roadmap if BOTH momentum signals show < 0.3%
and non-monotone quintiles. (Volatility is judged separately — it informs
strategy selection, not directional return prediction.)

Caveat: uses today's Nifty 50 constituents -> survivorship bias inflates edge.
Acceptable for a crude "is there a large effect" screen; documented, not hidden.

Usage:
    uv run python scripts/cross_sectional_screen.py
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# Allow running as a top-level script from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market import get_market

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOWNLOAD_START = "2020-06-01"   # >= 273 trading days of warmup before SCREEN_FROM
DOWNLOAD_END   = "2026-01-01"
SCREEN_FROM    = "2022-01-01"   # first date eligible to enter the panel
TAIL_EXCLUSION = 20             # final N trading days excluded (forward window safety)

MIN_NAMES      = 20             # min symbols on a date to form quintiles
TURNOVER_STEP  = 10             # rebalance horizon (trading days) for Q5 turnover

BENCHMARK = "NIFTY"             # resolves to ^NSEI via src/market/symbols.py

SIGNAL_KEYS = ["rs_6m", "rs_12m1", "vol_63"]
HORIZONS    = [5, 10, 20]

# Decision thresholds (percent, 10d Q5-Q1 spread).
KILL_THRESHOLD = 0.3
MARGINAL_HIGH  = 0.8
SUSPECT_LARGE  = 1.5

# Nifty 50 constituents (yfinance .NS tickers). Today's snapshot — survivorship
# bias acknowledged in the module docstring.
NIFTY_50: list[str] = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "BAJFINANCE.NS",
    "KOTAKBANK.NS", "LT.NS", "HCLTECH.NS", "AXISBANK.NS", "MARUTI.NS",
    "ASIANPAINT.NS", "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "NESTLEIND.NS",
    "WIPRO.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "M&M.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "ADANIENT.NS", "ADANIPORTS.NS",
    "COALINDIA.NS", "BAJAJFINSV.NS", "HDFCLIFE.NS", "SBILIFE.NS", "BPCL.NS",
    "GRASIM.NS", "BRITANNIA.NS", "EICHERMOT.NS", "CIPLA.NS", "DRREDDY.NS",
    "HEROMOTOCO.NS", "HINDALCO.NS", "INDUSINDBK.NS", "TECHM.NS", "APOLLOHOSP.NS",
    "BAJAJ-AUTO.NS", "TATACONSUM.NS", "LTIM.NS", "SHRIRAMFIN.NS", "DIVISLAB.NS",
]

CACHE_DIR = Path(__file__).resolve().parent / ".cache_screen"


# ---------------------------------------------------------------------------
# Pure signal / outcome functions (unit-tested; no I/O)
# ---------------------------------------------------------------------------

def trailing_return(closes: list[float], i: int, lookback: int, skip: int = 0) -> float | None:
    """close[i-skip] / close[i-skip-lookback] - 1, or None if out of range.

    Uses only data at or before index i (no lookahead).
    """
    a = i - skip
    b = a - lookback
    if b < 0 or a < 0 or a >= len(closes):
        return None
    if closes[b] <= 0:
        return None
    return closes[a] / closes[b] - 1.0


def realized_vol(closes: list[float], i: int, window: int = 63) -> float | None:
    """Stdev of the last `window` daily log returns ending at index i, or None.

    Uses only data at or before index i (no lookahead). Annualisation omitted —
    it is a monotone constant and does not change cross-sectional ranks.
    """
    if i - window < 0:
        return None
    rets: list[float] = []
    for k in range(i - window + 1, i + 1):
        p0, p1 = closes[k - 1], closes[k]
        if p0 <= 0 or p1 <= 0:
            return None
        rets.append(math.log(p1 / p0))
    if len(rets) < 2:
        return None
    return statistics.stdev(rets)


def forward_excess(
    stock_closes: list[float],
    stock_dates: list[str],
    bench_by_date: dict[str, float],
    i: int,
    offset: int,
) -> float | None:
    """Forward excess return = stock fwd return - benchmark fwd return.

    Benchmark return is taken over the SAME two calendar dates (date[i] and
    date[i+offset]) by date lookup, so holidays/missing days cannot desync the
    two series. Returns None if either benchmark date is missing.
    Uses only data strictly after index i for the forward leg.
    """
    j = i + offset
    if j >= len(stock_closes):
        return None
    c0, c1 = stock_closes[i], stock_closes[j]
    if c0 <= 0:
        return None
    stock_ret = c1 / c0 - 1.0

    b0 = bench_by_date.get(stock_dates[i])
    b1 = bench_by_date.get(stock_dates[j])
    if b0 is None or b1 is None or b0 <= 0:
        return None
    bench_ret = b1 / b0 - 1.0
    return stock_ret - bench_ret


def quintile_index(rank: int, n: int) -> int:
    """Map a 0-based ascending rank among n items to a quintile 0..4 (Q1..Q5)."""
    return min(4, rank * 5 // n)


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------

def build_symbol_panel(
    symbol: str,
    candles: list[dict],
    bench_by_date: dict[str, float],
) -> list[dict]:
    """Emit one panel row per eligible date for a single symbol.

    No live I/O. Signals use only past data; forward excess uses only future
    data. Rows before SCREEN_FROM (warmup) and inside the tail-exclusion window
    are skipped.
    """
    closes = [c["close"] for c in candles]
    dates  = [c["date"][:10] for c in candles]
    n      = len(candles)
    max_i  = n - 1 - TAIL_EXCLUSION

    rows: list[dict] = []
    for i in range(n):
        d = dates[i]
        if d < SCREEN_FROM:
            continue
        if i > max_i:
            break
        rows.append({
            "date":    d,
            "symbol":  symbol,
            "rs_6m":   trailing_return(closes, i, 126, 0),
            "rs_12m1": trailing_return(closes, i, 252, 21),
            "vol_63":  realized_vol(closes, i, 63),
            "exc_5":   forward_excess(closes, dates, bench_by_date, i, 5),
            "exc_10":  forward_excess(closes, dates, bench_by_date, i, 10),
            "exc_20":  forward_excess(closes, dates, bench_by_date, i, 20),
        })
    return rows


# ---------------------------------------------------------------------------
# Cross-sectional aggregation
# ---------------------------------------------------------------------------

def aggregate(panel: list[dict], min_names: int = MIN_NAMES) -> dict:
    """Rank each date cross-sectionally and bucket forward excess by quintile.

    Returns:
      {
        "buckets":     {signal: {horizon: [ [Q1 excess...], ..., [Q5 excess...] ]}},
        "q5_dates":    {signal: {date: set(symbols in Q5 by 10d ranking)}},
        "n_dates":     {signal: {horizon: int}},
      }
    """
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in panel:
        by_date[r["date"]].append(r)

    buckets = {s: {h: [[] for _ in range(5)] for h in HORIZONS} for s in SIGNAL_KEYS}
    q5_dates: dict[str, dict[str, set]] = {s: {} for s in SIGNAL_KEYS}
    n_dates  = {s: {h: 0 for h in HORIZONS} for s in SIGNAL_KEYS}

    for date in sorted(by_date):
        rows = by_date[date]
        for s in SIGNAL_KEYS:
            for h in HORIZONS:
                exc_key = f"exc_{h}"
                members = [
                    (r["symbol"], r[s], r[exc_key])
                    for r in rows
                    if r[s] is not None and r[exc_key] is not None
                ]
                if len(members) < min_names:
                    continue
                members.sort(key=lambda x: x[1])
                n = len(members)
                n_dates[s][h] += 1
                q5set: set = set()
                for rank, (sym, _sig, exc) in enumerate(members):
                    q = quintile_index(rank, n)
                    buckets[s][h][q].append(exc)
                    if h == 10 and q == 4:
                        q5set.add(sym)
                if h == 10:
                    q5_dates[s][date] = q5set

    return {"buckets": buckets, "q5_dates": q5_dates, "n_dates": n_dates}


def bucket_means(bucket_lists: list[list[float]]) -> list[float | None]:
    """Mean forward excess (%) per quintile; None for an empty bucket."""
    out: list[float | None] = []
    for q in range(5):
        lst = bucket_lists[q]
        out.append(round(100.0 * sum(lst) / len(lst), 3) if lst else None)
    return out


def is_monotone(means: list[float | None]) -> bool:
    """True if quintile means are non-decreasing Q1->Q5 (ignoring None)."""
    valid = [m for m in means if m is not None]
    return len(valid) >= 2 and all(valid[k] <= valid[k + 1] for k in range(len(valid) - 1))


def hit_rate(bucket_list: list[float]) -> float | None:
    """Percent of observations in a bucket with positive forward excess."""
    if not bucket_list:
        return None
    return round(100.0 * sum(1 for v in bucket_list if v > 0) / len(bucket_list), 1)


def q5_turnover(q5_dates: dict[str, set], step: int = TURNOVER_STEP) -> float | None:
    """Average % of Q5 names that LEAVE Q5 over `step` trading days."""
    dates = sorted(q5_dates)
    if len(dates) <= step:
        return None
    fracs: list[float] = []
    for k in range(len(dates) - step):
        cur = q5_dates[dates[k]]
        nxt = q5_dates[dates[k + step]]
        if not cur:
            continue
        fracs.append(len(cur - nxt) / len(cur))
    return round(100.0 * sum(fracs) / len(fracs), 1) if fracs else None


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def momentum_verdict(spreads: dict[str, float | None], monos: dict[str, bool]) -> str:
    """Map the two momentum 10d spreads to a roadmap verdict string."""
    mom = [s for k in ("rs_6m", "rs_12m1") if (s := spreads.get(k)) is not None]
    if not mom:
        return "INSUFFICIENT DATA — momentum spreads could not be computed."

    best = max(mom)
    best_key = max(("rs_6m", "rs_12m1"), key=lambda k: spreads.get(k) or -999)
    best_mono = monos.get(best_key, False)

    if best > SUSPECT_LARGE:
        return (f"SUSPICIOUSLY LARGE ({best:+.2f}% on {best_key}). A crude screen "
                "showing this is more likely a bug (lookahead/survivorship/ticker "
                "misalignment) than alpha. Audit the pipeline BEFORE believing it.")
    if best >= MARGINAL_HIGH and best_mono:
        return (f"LARGE EFFECT ({best:+.2f}% on {best_key}, monotone). Justifies "
                "production work — build the strategy, sub-period check, then "
                "PAPER-TRADE before real money.")
    if best >= KILL_THRESHOLD and best_mono:
        return (f"MARGINAL EFFECT ({best:+.2f}% on {best_key}, monotone). Real but "
                "near costs. THIS is what now justifies Audit V2 rigor to resolve.")
    both_dead = all((spreads.get(k) or 0) < KILL_THRESHOLD for k in ("rs_6m", "rs_12m1"))
    any_mono  = monos.get("rs_6m", False) or monos.get("rs_12m1", False)
    if both_dead and not any_mono:
        return ("DIRECTIONAL PREDICTION LOOKS DEAD on this universe. Both momentum "
                "signals < 0.3% and non-monotone. Stop building prediction infra; "
                "pivot to risk / process / options-structure.")
    return (f"WEAK / NOISY (best {best:+.2f}% on {best_key}). No large effect; not "
            "clearly dead either. Do not invest further engineering yet.")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_SIGNAL_TITLE = {
    "rs_6m":   "RS_6m   — rank by trailing 126d return (momentum); outcome = fwd EXCESS vs NIFTY",
    "rs_12m1": "RS_12m1 — rank by 252d return skip-21 (12-1 momentum); outcome = fwd EXCESS vs NIFTY",
    "vol_63":  "Vol_63  — rank by 63d realized vol (Q5=highest vol); low-vol anomaly => watch Q1>Q5",
}


def print_signal_block(signal: str, result: dict) -> dict:
    """Print one signal's quintile table; return its 10d spread + monotonicity."""
    buckets = result["buckets"][signal]
    n_dates = result["n_dates"][signal]

    print()
    print(f"  {_SIGNAL_TITLE[signal]}")
    print(f"  {'Horizon':<8} {'Q1':>8} {'Q2':>8} {'Q3':>8} {'Q4':>8} {'Q5':>8} "
          f"{'Q5-Q1':>8} {'mono':>5} {'hit%Q5':>7} {'n_obs':>7} {'n_dates':>8}")
    print("  " + "-" * 92)

    spread_10d: float | None = None
    mono_10d = False

    for h in HORIZONS:
        means = bucket_means(buckets[h])
        mono  = is_monotone(means)
        q1, q5 = means[0], means[4]
        spread = round(q5 - q1, 3) if (q1 is not None and q5 is not None) else None
        hr    = hit_rate(buckets[h][4])
        n_obs = sum(len(buckets[h][q]) for q in range(5))

        def _c(v: float | None) -> str:
            return "--" if v is None else f"{v:+.3f}"

        print(f"  {str(h) + 'd':<8} {_c(means[0]):>8} {_c(means[1]):>8} {_c(means[2]):>8} "
              f"{_c(means[3]):>8} {_c(means[4]):>8} {_c(spread):>8} "
              f"{('yes' if mono else 'no'):>5} {('--' if hr is None else f'{hr:.1f}'):>7} "
              f"{n_obs:>7} {n_dates[h]:>8}")

        if h == 10:
            spread_10d, mono_10d = spread, mono

    turnover = q5_turnover(result["q5_dates"][signal])
    print(f"  {TURNOVER_STEP}-step Q5 turnover: "
          f"{'--' if turnover is None else f'{turnover:.1f}%'} "
          f"(higher = more rebalancing = more cost drag)")

    return {"spread_10d": spread_10d, "mono_10d": mono_10d}


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------

def _cache_path(symbol: str) -> Path:
    safe = symbol.replace(".", "_").replace("&", "and").replace("-", "_")
    return CACHE_DIR / f"{safe}_{DOWNLOAD_START}_{DOWNLOAD_END}.json"


def load_candles_cached(symbol: str, retries: int = 1) -> list[dict]:
    """Load candles from local JSON cache, else download once and cache.

    Returns [] on failure (caller decides). One retry on transient download
    errors (yfinance/Yahoo hiccups, e.g. the intermittent 'possibly delisted').
    """
    path = _cache_path(symbol)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass  # fall through to re-download

    for attempt in range(retries + 1):
        try:
            candles = get_market().get_historical(symbol, DOWNLOAD_START, DOWNLOAD_END, "1d")
        except Exception as exc:  # noqa: BLE001 — screen must tolerate any vendor error
            candles = []
            if attempt == retries:
                print(f"    {symbol}: download error: {exc}")
        if candles:
            CACHE_DIR.mkdir(exist_ok=True)
            try:
                path.write_text(json.dumps(candles))
            except OSError:
                pass
            return candles
    return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("Cross-Sectional Signal Screen — cheap, crude, falsifiable")
    print(f"Universe: Nifty 50 ({len(NIFTY_50)} names)  |  Window: {SCREEN_FROM} -> {DOWNLOAD_END}")

    print(f"\nLoading benchmark ({BENCHMARK})...")
    bench = load_candles_cached(BENCHMARK)
    if not bench:
        print("  FATAL: benchmark download failed — cannot compute excess returns.")
        return
    bench_by_date = {c["date"][:10]: c["close"] for c in bench}
    print(f"  {len(bench)} benchmark candles.")

    panel: list[dict] = []
    loaded = 0
    failed: list[str] = []
    for sym in NIFTY_50:
        candles = load_candles_cached(sym)
        if not candles:
            failed.append(sym)
            continue
        loaded += 1
        panel.extend(build_symbol_panel(sym, candles, bench_by_date))

    coverage = loaded / len(NIFTY_50)
    print(f"\nCoverage: {loaded}/{len(NIFTY_50)} symbols ({coverage:.0%}).")
    if failed:
        print(f"  Failed: {', '.join(failed)}")
    if coverage < 0.90:
        print("  WARNING: coverage < 90% — results may be unreliable (treat as INVALID).")

    print(f"  Panel rows: {len(panel)}")

    result = aggregate(panel)

    print("\n" + "=" * 96)
    print("  QUINTILE FORWARD-EXCESS-RETURN SPREADS  (Q5 = highest signal)")
    print("=" * 96)

    spreads: dict[str, float | None] = {}
    monos:   dict[str, bool] = {}
    for signal in SIGNAL_KEYS:
        summ = print_signal_block(signal, result)
        spreads[signal] = summ["spread_10d"]
        monos[signal]   = summ["mono_10d"]

    print("\n" + "=" * 96)
    print("  VERDICT")
    print("=" * 96)
    print("\n  Momentum (directional prediction):")
    print(f"    {momentum_verdict(spreads, monos)}")

    vol_spread = spreads.get("vol_63")
    print("\n  Volatility (strategy selection, NOT a directional kill):")
    if vol_spread is None:
        print("    Insufficient data.")
    else:
        low_minus_high = -vol_spread  # Q1 - Q5
        if low_minus_high > 0:
            print(f"    Low-minus-high-vol 10d excess: {low_minus_high:+.3f}% — low-vol names "
                  "earned more raw excess (consistent with the low-vol anomaly). Confirm "
                  "risk-adjusted before acting.")
        else:
            print(f"    Low-minus-high-vol 10d excess: {low_minus_high:+.3f}% — HIGH-vol names "
                  "earned more RAW excess. This is almost certainly beta in a rising market "
                  "(plus survivorship), NOT alpha — the screen measures raw, not risk-adjusted, "
                  "excess. Not tradeable as-is.")

    print("\n  Reminder: today's-constituents universe => survivorship inflates edge.")
    print("  A backtest edge is not an executable edge — paper-trade before real money.")


if __name__ == "__main__":
    main()
