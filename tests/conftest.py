"""
Shared fixtures for the Zerodha MCP test suite.

Available to all test files without explicit imports.
"""
import math
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _set_test_user():
    """Set current_user ContextVar so journal/recommendation queries return data in tests."""
    from src.broker import current_user
    token = current_user.set("TEST_USER")
    yield
    current_user.reset(token)


@pytest.fixture(autouse=True)
def _clear_analysis_cache():
    """Isolate the _analyze_technicals TTL cache (Phase 14.6 C1) between tests."""
    from src.analysis.regime import clear_analysis_cache
    clear_analysis_cache()
    yield
    clear_analysis_cache()


# ---------------------------------------------------------------------------
# Option chain constants
# ---------------------------------------------------------------------------

TEST_EXPIRY = "26-Jun-2025"
TEST_SPOT = 24000.0


def _option_row(strike, ce_oi, pe_oi, ce_ltp, pe_ltp, expiry=TEST_EXPIRY):
    return {
        "strikePrice": strike,
        "expiryDate": expiry,
        "CE": {
            "openInterest": ce_oi,
            "changeinOpenInterest": 100,
            "totalTradedVolume": max(1, ce_oi // 5),
            "impliedVolatility": 15.0,
            "lastPrice": ce_ltp,
        },
        "PE": {
            "openInterest": pe_oi,
            "changeinOpenInterest": -50,
            "totalTradedVolume": max(1, pe_oi // 5),
            "impliedVolatility": 16.0,
            "lastPrice": pe_ltp,
        },
    }


@pytest.fixture
def chain_data():
    """Mock NSE option chain: spot=24000, strikes 23000–25000 at 100-pt intervals.

    OI concentrated at major levels to produce realistic S/R:
      23000 → heavy put OI (support)
      25000 → heavy call OI (resistance)
    """
    oi_by_strike = {
        23000: (2000, 90000),
        23500: (8000, 40000),
        23900: (15000, 25000),
        24000: (55000, 55000),  # ATM balanced
        24100: (25000, 18000),
        24500: (40000, 8000),
        25000: (90000, 2000),
    }
    rows = []
    for strike in range(23000, 25100, 100):
        ce_oi, pe_oi = oi_by_strike.get(strike, (20000, 20000))
        ce_ltp = round(max(0.5, (25100 - strike) * 0.12 + 3.0), 2)
        pe_ltp = round(max(0.5, (strike - 22900) * 0.12 + 3.0), 2)
        rows.append(_option_row(strike, ce_oi, pe_oi, ce_ltp, pe_ltp))

    return {
        "records": {
            "data": rows,
            "expiryDates": [TEST_EXPIRY, "03-Jul-2025"],
            "underlyingValue": TEST_SPOT,
        }
    }


@pytest.fixture
def chain_expiry():
    return TEST_EXPIRY


@pytest.fixture
def chain_spot():
    return TEST_SPOT


# ---------------------------------------------------------------------------
# Synthetic OHLCV series (exported as helpers, not fixtures)
# ---------------------------------------------------------------------------

def make_bull_series(n: int = 200):
    """Steadily rising prices: ensures EMA20 > EMA50, ADX > 25."""
    closes = [1000.0 + 3.0 * i for i in range(n)]
    highs = [c + 5.0 for c in closes]
    lows = [c - 5.0 for c in closes]
    return closes, highs, lows


def make_bear_series(n: int = 200):
    """Steadily falling prices: ensures EMA20 < EMA50, ADX > 25."""
    closes = [2000.0 - 3.0 * i for i in range(n)]
    highs = [c + 5.0 for c in closes]
    lows = [c - 5.0 for c in closes]
    return closes, highs, lows


def make_range_series(n: int = 200):
    """Oscillating prices: ensures ADX < 20."""
    closes = [1000.0 + 25.0 * math.sin(i * math.pi / 5) for i in range(n)]
    highs = [c + 8.0 for c in closes]
    lows = [c - 8.0 for c in closes]
    return closes, highs, lows


# ---------------------------------------------------------------------------
# Mock _analyze_technicals snapshots (per regime)
# ---------------------------------------------------------------------------

def _tech(symbol, rsi, ema20, ema50, adx, price, atr=2.0,
          macd_val=0.5, macd_sig=0.3):
    """Build a deterministic mock for _analyze_technicals()."""
    return {
        "symbol": symbol.upper(),
        "last_close": price,
        "candles_used": 150,
        "rsi_14": rsi,
        "ema_20": ema20,
        "ema_50": ema50,
        "macd": {
            "macd": macd_val,
            "signal": macd_sig,
            "histogram": round(macd_val - macd_sig, 4),
        },
        "adx_14": {"adx": adx, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": atr,
    }


# Pre-built snapshots used across multiple test files

BULL_TREND_TECH = _tech(
    "NIFTY", rsi=65.0, ema20=100.0, ema50=90.0,
    adx=30.0, price=101.0, atr=2.0,
)
# ema20 > ema50, adx > 25  →  BULL_TREND

BEAR_TREND_TECH = _tech(
    "NIFTY", rsi=35.0, ema20=90.0, ema50=100.0,
    adx=28.0, price=89.0, atr=2.0,
    macd_val=-0.5, macd_sig=-0.3,
)
# ema20 < ema50, adx > 25  →  BEAR_TREND

RANGE_BOUND_TECH = _tech(
    "NIFTY", rsi=50.0, ema20=100.0, ema50=98.0,
    adx=15.0, price=100.5, atr=1.5,
    macd_val=0.1, macd_sig=0.0,
)
# adx < 20  →  RANGE_BOUND

BREAKOUT_TECH = _tech(
    "NIFTY", rsi=60.0, ema20=100.0, ema50=98.0,
    adx=22.0, price=101.0, atr=2.0,
)
# 20 <= adx <= 25, rsi > 55, price > ema20  →  BREAKOUT_POTENTIAL

# NEUTRAL_BULLISH (fallback): adx in [20,25], rsi neutral, price >= ema20
NEUTRAL_BULLISH_TECH = _tech(
    "NIFTY", rsi=50.0, ema20=100.0, ema50=99.0,
    adx=22.0, price=101.0, atr=1.8,
    macd_val=0.1, macd_sig=0.0,
)
# Conditions: 20<=adx<=25, rsi NOT >55, price>=ema20 → fallback NEUTRAL_BULLISH

# NEUTRAL_BEARISH (fallback): adx in [20,25], rsi neutral, price < ema20
NEUTRAL_BEARISH_TECH = _tech(
    "NIFTY", rsi=50.0, ema20=102.0, ema50=100.0,
    adx=22.0, price=99.0, atr=1.8,
    macd_val=-0.1, macd_sig=0.0,
)
# Conditions: 20<=adx<=25, rsi NOT <45, price<ema20 → fallback NEUTRAL_BEARISH

# BUY signal with RANGE_BOUND regime (the historical conflict bug)
RANGE_BUY_TECH = _tech(
    "NIFTY", rsi=65.0, ema20=100.0, ema50=99.0,
    adx=15.0, price=101.0, atr=2.0,
)
# adx=15 < 20  →  RANGE_BOUND
# bullish score: rsi>55(+20) + price>ema20(+15) + price>ema50(+15) + macd>sig(+20) = 70 → BUY

# SELL signal with RANGE_BOUND regime
RANGE_SELL_TECH = _tech(
    "NIFTY", rsi=35.0, ema20=102.0, ema50=100.0,
    adx=15.0, price=99.0, atr=2.0,
    macd_val=-0.5, macd_sig=-0.3,
)
# adx=15 < 20  →  RANGE_BOUND
# bearish score: rsi<45(+20) + price<ema20(+15) + price<ema50(+15) + macd<sig(+20) = 70 → SELL


@pytest.fixture
def patch_analyze(monkeypatch):
    """Return a callable that patches src.analysis.regime._analyze_technicals."""
    def _apply(tech_dict):
        monkeypatch.setattr(
            "src.analysis.regime._analyze_technicals",
            lambda symbol, lookback_days=150, interval="daily": tech_dict,
        )
    return _apply


@pytest.fixture(autouse=True)
def _mock_regime_alignment(monkeypatch):
    """Default: return STRONG alignment with no conflict — prevents live yfinance
    calls from the Phase 19 timeframe check inside recommend_trade.

    Override per-test by calling monkeypatch.setattr(eng, '_get_regime_alignment', ...)
    after this fixture has already run (last setattr wins).
    """
    import src.recommendations.engine as eng
    monkeypatch.setattr(eng, "_get_regime_alignment", lambda s: {
        "daily":   {"regime": "BULL_TREND", "confidence": 65},
        "weekly":  {"regime": "BULL_TREND", "confidence": 60},
        "monthly": {"regime": "BULL_TREND", "confidence": 63},
        "alignment": "STRONG",
        "summary": "All timeframes bullish — strong alignment",
    })


# ---------------------------------------------------------------------------
# Options service mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_options_svc(monkeypatch, chain_data):
    """Patch get_options_service in planner, builder and dashboard to return mock chain."""
    svc = MagicMock()
    svc.get_option_chain.return_value = chain_data
    for target in (
        "src.planner.trade_plan.get_options_service",
        "src.strategy.builder.get_options_service",
        "src.dashboard.service.get_options_service",
    ):
        monkeypatch.setattr(target, lambda _svc=svc: _svc)
    return svc
