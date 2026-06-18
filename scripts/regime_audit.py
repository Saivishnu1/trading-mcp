"""
Regime Predictiveness Audit — Phase 20A

Walk-forward audit of the regime classification engine against pre-downloaded
historical OHLCV data.  Answers the question:

    "Does _classify_regime() have directional predictive value across both
     index (Nifty 50) and individual NSE equity symbols?"

Hard constraints enforced throughout:
  * Data downloaded ONCE via get_market().get_historical() — before the loop.
  * No live network calls inside run_symbol_audit().
  * detect_market_regime() is never called.  _classify_regime() is used directly.
  * Classifications start from CLASSIFY_FROM (2022-01-01).  2021 is warmup only.
  * Final TAIL_EXCLUSION trading days excluded so all forward windows are complete.

Usage:
    uv run python scripts/regime_audit.py
"""
from __future__ import annotations

import sys
from itertools import groupby
from pathlib import Path
from typing import NamedTuple

# Allow running as a top-level script from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market import get_market
from src.technical import indicators
# Import only _classify_regime — detect_market_regime() must NOT appear here.
from src.analysis.regime import _classify_regime

# ---------------------------------------------------------------------------
# Audit configuration
# ---------------------------------------------------------------------------

SYMBOLS: dict[str, str] = {
    "NIFTY50":    "NIFTY",         # resolves to ^NSEI via src/market/symbols.py
    "INFY":       "INFY.NS",
    "HDFCBANK":   "HDFCBANK.NS",
    "RELIANCE":   "RELIANCE.NS",
    "TATAMOTORS": "TATAMOTORS.NS",
}

DOWNLOAD_START = "2021-01-01"
DOWNLOAD_END   = "2026-01-01"
CLASSIFY_FROM  = "2022-01-01"   # first date eligible for classification (post-warmup)
LOOKBACK       = 150            # sliding window — mirrors _analyze_technicals default
TAIL_EXCLUSION = 20             # final N trading days excluded (forward window safety)

_BULLISH = frozenset({"BULL_TREND", "NEUTRAL_BULLISH", "BREAKOUT_POTENTIAL"})
_BEARISH = frozenset({"BEAR_TREND", "NEUTRAL_BEARISH"})

REGIME_ORDER = [
    "BULL_TREND",
    "NEUTRAL_BULLISH",
    "BREAKOUT_POTENTIAL",
    "RANGE_BOUND",
    "NEUTRAL_BEARISH",
    "BEAR_TREND",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class ClassificationRow(NamedTuple):
    date:       str
    regime:     str
    confidence: int
    ret_5d:     float | None
    ret_10d:    float | None
    ret_20d:    float | None


# ---------------------------------------------------------------------------
# Core audit functions
# ---------------------------------------------------------------------------

def _build_technicals(symbol: str, candles: list[dict]) -> dict:
    """Reconstruct the exact technicals dict that _analyze_technicals() produces.

    Pure function — no I/O.  Must remain an exact structural mirror of
    _analyze_technicals() in src/analysis/regime.py so that _classify_regime()
    receives identical input to what it sees in production.
    """
    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    return {
        "symbol":           symbol.upper(),
        "last_close":       round(closes[-1], 4),
        "candles_used":     len(closes),
        "data_source":      "yfinance_eod_adjusted",
        "last_candle_date": candles[-1]["date"],
        "rsi_14":           indicators.rsi(closes, 14),
        "ema_20":           indicators.ema(closes, 20),
        "ema_50":           indicators.ema(closes, 50),
        "macd":             indicators.macd(closes),        # computed but not used by _classify_regime
        "adx_14":           indicators.adx(highs, lows, closes, 14),
        "atr_14":           indicators.atr(highs, lows, closes, 14),
    }


def run_symbol_audit(
    label: str,
    symbol: str,
    all_candles: list[dict],
) -> list[ClassificationRow]:
    """Walk-forward regime classification audit for one symbol.

    all_candles: full pre-downloaded candle array.  No live fetches here.
    Returns one ClassificationRow per valid classification date.
    """
    n_total          = len(all_candles)
    max_classify_idx = n_total - 1 - TAIL_EXCLUSION  # last index with complete forward windows

    rows: list[ClassificationRow] = []

    for i in range(n_total):
        date_str = all_candles[i]["date"][:10]

        # 2021 is warmup only.
        if date_str < CLASSIFY_FROM:
            continue

        # Require a full LOOKBACK window before classifying.
        if i < LOOKBACK - 1:
            continue

        # Exclude final TAIL_EXCLUSION days so all forward windows are computable.
        if i > max_classify_idx:
            break

        candles_slice = all_candles[i - LOOKBACK + 1 : i + 1]   # exactly LOOKBACK candles
        technicals    = _build_technicals(symbol, candles_slice)
        result        = _classify_regime(symbol, technicals)

        if "error" in result:
            continue

        close_t = all_candles[i]["close"]

        def _fwd(offset: int, _i: int = i, _ct: float = close_t) -> float | None:
            j = _i + offset
            if j >= n_total:
                return None
            return round((all_candles[j]["close"] - _ct) / _ct, 6)

        rows.append(ClassificationRow(
            date=date_str,
            regime=result["regime"],
            confidence=result["confidence"],
            ret_5d=_fwd(5),
            ret_10d=_fwd(10),
            ret_20d=_fwd(20),
        ))

    return rows


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _pct_avg(values: list[float]) -> float | None:
    """Return average as a percentage (×100), rounded to 3dp, or None."""
    return round(100.0 * sum(values) / len(values), 3) if values else None


def _runs_stats(seq: list[str], target: str) -> tuple[int, float]:
    """(number of distinct consecutive runs, average run length) for target."""
    lengths = [sum(1 for _ in g) for k, g in groupby(seq) if k == target]
    n       = len(lengths)
    return n, round(sum(lengths) / n, 1) if n else 0.0


def compute_metrics(rows: list[ClassificationRow]) -> dict:
    """Compute all audit metrics from a flat list of ClassificationRow objects."""
    if not rows:
        return {"total_classifications": 0, "regimes": {}}

    total      = len(rows)
    regime_seq = [r.regime for r in rows]

    # Unconditional baseline over the same date range.
    all_r10 = [r.ret_10d for r in rows if r.ret_10d is not None]
    n_valid  = len(all_r10)
    base_pos = round(100.0 * sum(1 for v in all_r10 if v > 0) / n_valid, 1) if n_valid else None
    base_neg = round(100.0 - base_pos, 1) if base_pos is not None else None
    base_avg = _pct_avg(all_r10)

    regime_metrics: dict[str, dict] = {}

    for regime in REGIME_ORDER:
        subset = [r for r in rows if r.regime == regime]
        n = len(subset)
        if n == 0:
            regime_metrics[regime] = {"n": 0}
            continue

        v5  = [r.ret_5d  for r in subset if r.ret_5d  is not None]
        v10 = [r.ret_10d for r in subset if r.ret_10d is not None]
        v20 = [r.ret_20d for r in subset if r.ret_20d is not None]

        if regime in _BULLISH:
            hits     = sum(1 for v in v10 if v > 0)
            base_da  = base_pos
        elif regime in _BEARISH:
            hits     = sum(1 for v in v10 if v < 0)
            base_da  = base_neg
        else:
            hits     = None   # RANGE_BOUND — not a directional prediction
            base_da  = None

        da        = round(100.0 * hits / len(v10), 1) if (hits is not None and v10) else None
        excess_da = round(da - base_da, 1) if (da is not None and base_da is not None) else None

        n_runs, avg_run = _runs_stats(regime_seq, regime)

        regime_metrics[regime] = {
            "n":                 n,
            "runs":              n_runs,
            "avg_run_length":    avg_run,
            "avg_confidence":    round(sum(r.confidence for r in subset) / n, 1),
            "pct_time":          round(100.0 * n / total, 1),
            "da_pct":            da,
            "baseline_da_pct":   base_da,
            "excess_da_pct":     excess_da,
            "avg_ret_5d_pct":    _pct_avg(v5),
            "avg_ret_10d_pct":   _pct_avg(v10),
            "avg_ret_20d_pct":   _pct_avg(v20),
        }

    return {
        "total_classifications":     total,
        "baseline_positive_10d_pct": base_pos,
        "baseline_negative_10d_pct": base_neg,
        "baseline_avg_ret_10d_pct":  base_avg,
        "regimes":                   regime_metrics,
    }


def run_start_vs_continuation(rows: list[ClassificationRow], regime: str) -> dict:
    """Split regime rows into run-starts vs continuations and compare 10d forward returns.

    Distinguishes between two failure modes:
      - Mature-trend effect: engine detects entries correctly but long continuation
        runs on exhausted trends drag the aggregate average negative.
      - Inception failure: the classification is wrong even at the moment of entry
        (run-start returns are also negative).
    """
    starts: list[float | None] = []
    continuations: list[float | None] = []

    for key, group in groupby(rows, key=lambda r: r.regime):
        members = list(group)
        if key != regime:
            continue
        starts.append(members[0].ret_10d)
        continuations.extend(r.ret_10d for r in members[1:])

    def _avg(lst: list[float | None]) -> float | None:
        clean = [v for v in lst if v is not None]
        return round(100.0 * sum(clean) / len(clean), 3) if clean else None

    start_avg = _avg(starts)
    cont_avg  = _avg(continuations)

    if start_avg is not None and cont_avg is not None:
        if start_avg > 0.1 and cont_avg < -0.1:
            interpretation = "MATURE_TREND_EFFECT"
        elif start_avg < -0.1 and cont_avg < -0.1:
            interpretation = "INCEPTION_FAILURE"
        elif abs(start_avg) <= 0.1 and cont_avg < -0.1:
            interpretation = "NO_ENTRY_EDGE"
        elif start_avg > 0.1 and cont_avg > 0.1:
            interpretation = "WINDOW_BIAS"
        else:
            interpretation = "AMBIGUOUS"
    else:
        interpretation = "INSUFFICIENT_DATA"

    return {
        "regime":              regime,
        "n_starts":            len(starts),
        "n_continuations":     len(continuations),
        "avg_10d_starts":      start_avg,
        "avg_10d_continuations": cont_avg,
        "interpretation":      interpretation,
    }


def monotonicity_check(metrics: dict) -> dict:
    """Check whether 10d average returns decrease monotonically from BULL to BEAR."""
    chain   = ["BULL_TREND", "NEUTRAL_BULLISH", "RANGE_BOUND", "NEUTRAL_BEARISH", "BEAR_TREND"]
    returns = [(r, metrics["regimes"].get(r, {}).get("avg_ret_10d_pct")) for r in chain]
    valid   = [(r, v) for r, v in returns if v is not None]
    ordered = all(valid[i][1] >= valid[i + 1][1] for i in range(len(valid) - 1))

    bull_ret = metrics["regimes"].get("BULL_TREND", {}).get("avg_ret_10d_pct")
    bear_ret = metrics["regimes"].get("BEAR_TREND", {}).get("avg_ret_10d_pct")

    return {
        "monotonicity_holds":          ordered,
        "bull_above_bear":             (bull_ret is not None and bear_ret is not None and bull_ret > bear_ret),
        "bear_trend_return_negative":  (bear_ret is not None and bear_ret < 0),
        "return_by_regime":            dict(valid),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_INTERPRETATION_LABELS = {
    "MATURE_TREND_EFFECT": "Mature-trend effect — starts positive, continuations negative. "
                           "Engine detects entries; long runs on exhausted trends drag the average.",
    "INCEPTION_FAILURE":   "Inception failure — starts AND continuations negative. "
                           "Classification is wrong even at the moment of entry.",
    "NO_ENTRY_EDGE":       "No entry edge — starts near zero, continuations negative. "
                           "Engine has no directional signal at run start.",
    "WINDOW_BIAS":         "Both positive — 2022 window bias likely; re-run excluding Jan-Jun 2022.",
    "AMBIGUOUS":           "Ambiguous — results do not fit a clean pattern.",
    "INSUFFICIENT_DATA":   "Insufficient data to compute run-start split.",
}


def print_run_diagnostic(rows: list[ClassificationRow]) -> None:
    """Print run-start vs continuation split for BULL_TREND and BEAR_TREND."""
    print()
    print("  Run-start vs continuation (10d forward return):")
    print(f"  {'Regime':<22} {'n_starts':>9} {'start_10d%':>11} {'n_cont':>7} {'cont_10d%':>10}  Interpretation")
    print("  " + "-" * 90)

    for regime in ("BULL_TREND", "BEAR_TREND"):
        d = run_start_vs_continuation(rows, regime)
        s = d["avg_10d_starts"]
        c = d["avg_10d_continuations"]
        s_str = f"{s:+.3f}" if s is not None else "--"
        c_str = f"{c:+.3f}" if c is not None else "--"
        print(
            f"  {regime:<22} {d['n_starts']:>9} {s_str:>11} "
            f"{d['n_continuations']:>7} {c_str:>10}  {d['interpretation']}"
        )
        print(f"  {'':22}   => {_INTERPRETATION_LABELS.get(d['interpretation'], '')}")


def print_report(label: str, metrics: dict) -> None:
    """Print a formatted audit table for one symbol or the aggregate."""
    SEP = "=" * 82
    print(f"\n{SEP}")
    print(f"  {label}")
    print(f"{SEP}")
    print(f"  Total classifications      : {metrics['total_classifications']}")
    print(f"  Baseline 10d positive rate : {metrics.get('baseline_positive_10d_pct')}%")
    print(f"  Baseline 10d avg return    : {metrics.get('baseline_avg_ret_10d_pct')}%")
    print()

    W = 22
    print(
        f"  {'Regime':<{W}} {'n':>5} {'runs':>5} {'avgRun':>7} "
        f"{'conf':>5} {'time%':>6} {'DA%':>6} {'baseDA':>7} "
        f"{'exDA':>6} {'r5d%':>7} {'r10d%':>7} {'r20d%':>7}"
    )
    print("  " + "-" * 80)

    def _f(v: float | None, d: int = 1) -> str:
        return "--" if v is None else f"{v:.{d}f}"

    def _ex(v: float | None) -> str:
        if v is None:
            return "--"
        return ("+" if v >= 0 else "") + f"{v:.1f}"

    for regime in REGIME_ORDER:
        m = metrics["regimes"].get(regime, {})
        if not m or m["n"] == 0:
            print(f"  {regime:<{W}} {'--':>5}")
            continue
        print(
            f"  {regime:<{W}}"
            f" {m['n']:>5}"
            f" {m['runs']:>5}"
            f" {m['avg_run_length']:>7.1f}"
            f" {m['avg_confidence']:>5.1f}"
            f" {m['pct_time']:>6.1f}"
            f" {_f(m['da_pct']):>6}"
            f" {_f(m['baseline_da_pct']):>7}"
            f" {_ex(m['excess_da_pct']):>6}"
            f" {_f(m['avg_ret_5d_pct'],  3):>7}"
            f" {_f(m['avg_ret_10d_pct'], 3):>7}"
            f" {_f(m['avg_ret_20d_pct'], 3):>7}"
        )

    mono = monotonicity_check(metrics)
    print()
    print(f"  Monotonicity (BULL→BEAR 10d return order) : "
          f"{'HOLDS' if mono['monotonicity_holds'] else 'VIOLATED'}")
    print(f"  BEAR_TREND avg 10d return sign            : "
          f"{'negative' if mono['bear_trend_return_negative'] else 'positive'}")
    print(f"  BULL_TREND outperforms BEAR_TREND         : "
          f"{'yes' if mono['bull_above_bear'] else 'no'}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    all_rows: dict[str, list[ClassificationRow]] = {}

    for label, symbol in SYMBOLS.items():
        print(f"\nDownloading {label} ({symbol}) ...")
        candles = get_market().get_historical(symbol, DOWNLOAD_START, DOWNLOAD_END, "1d")
        if not candles:
            print(f"  WARNING: no data returned for {label} — skipping.")
            continue
        print(f"  {len(candles)} candles downloaded.")

        rows = run_symbol_audit(label, symbol, candles)
        print(f"  {len(rows)} classifications generated.")

        metrics = compute_metrics(rows)
        print_report(label, metrics)
        print_run_diagnostic(rows)
        all_rows[label] = rows

    if len(all_rows) > 1:
        combined = [r for rows_list in all_rows.values() for r in rows_list]
        print_report("AGGREGATE (all symbols — index + 4 equities)", compute_metrics(combined))
        print_run_diagnostic(combined)
        print()
        print("  Note: aggregate mixes Nifty 50 (index) with individual equities.")
        print("  Per-symbol tables are the primary signal; aggregate shows cross-instrument consistency.")


if __name__ == "__main__":
    main()
