"""
Regression tests — each test is named after the historical bug it protects.

These tests must NEVER be removed without a conscious, documented decision.
They exist because the bugs they cover either caused silent failures in
production or were hard to catch via normal unit tests.
"""
import pytest

from src.analysis.regime import (
    generate_trade_setup,
)
from src.options.service import OptionsService
from src.planner.trade_plan import _trade_quality, create_trade_plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tech(rsi=65.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0,
          atr=2.0, macd_val=0.5, macd_sig=0.3):
    return {
        "symbol": "NIFTY", "last_close": price, "candles_used": 150,
        "rsi_14": rsi, "ema_20": ema20, "ema_50": ema50,
        "macd": {"macd": macd_val, "signal": macd_sig,
                 "histogram": round(macd_val - macd_sig, 4)},
        "adx_14": {"adx": adx, "plus_di": 28.0, "minus_di": 12.0},
        "atr_14": atr,
    }


def _silence_options(monkeypatch):
    class _Svc:
        def get_option_chain(self, *a, **kw):
            raise RuntimeError("NSE unavailable")
    monkeypatch.setattr("src.planner.trade_plan.get_options_service", lambda: _Svc())


# ---------------------------------------------------------------------------
# Regression 1 — Phase 8: symbol normalisation (NSE:RELIANCE → RELIANCE)
# ---------------------------------------------------------------------------

class TestReg1SymbolNormalization:
    """
    Bug: OptionsService passed "NSE:RELIANCE" verbatim to jugaad
    equities_option_chain(), which expects a bare symbol.
    Result: 0 rows → RuntimeError → premium_data_available=False.
    Fix: _strip_exchange_prefix() static method.
    """

    def test_strip_nse_prefix(self):
        assert OptionsService._strip_exchange_prefix("NSE:RELIANCE") == "RELIANCE"

    def test_strip_bse_prefix(self):
        assert OptionsService._strip_exchange_prefix("BSE:INFY") == "INFY"

    def test_bare_symbol_unchanged(self):
        assert OptionsService._strip_exchange_prefix("RELIANCE") == "RELIANCE"

    def test_nifty_unchanged(self):
        assert OptionsService._strip_exchange_prefix("NIFTY") == "NIFTY"

    def test_index_symbols_not_stripped(self):
        """Index symbols have no prefix — must pass through unchanged."""
        for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
            assert OptionsService._strip_exchange_prefix(sym) == sym

    def test_equity_fetch_uses_bare_symbol(self, monkeypatch):
        """
        Verify _fetch_via_jugaad calls equities_option_chain with bare symbol,
        not the prefixed one.
        """
        calls = []

        class FakeNSELive:
            def equities_option_chain(self, symbol, expiry=None):
                calls.append(symbol)
                return {"records": {"data": []}}  # empty but not None

        svc = OptionsService.__new__(OptionsService)
        svc._nse_live = FakeNSELive()
        svc._fetch_via_jugaad("NSE:RELIANCE", expiry=None)
        assert calls == ["RELIANCE"], (
            f"Expected bare 'RELIANCE', got {calls}"
        )


# ---------------------------------------------------------------------------
# Regression 4 — Phase 3 schema: legacy fields always present
# ---------------------------------------------------------------------------

class TestReg4LegacySchema:
    """
    Bug: generate_trade_setup() removed legacy scalar fields (entry/stoploss/target)
    in favour of zone fields. This broke Dashboard, Planner, Alerts, and Journal.
    Fix: Both schemas always returned; legacy fields derived from zone fields.
    """

    SIGNALS = ["BUY", "SELL", "NEUTRAL", "NEUTRAL_BULLISH", "NEUTRAL_BEARISH"]

    TECHS = {
        "BUY": _tech(rsi=65.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0),
        "SELL": _tech(rsi=35.0, ema20=90.0, ema50=100.0, adx=28.0, price=89.0,
                      macd_val=-0.5, macd_sig=-0.3),
        "NEUTRAL": _tech(rsi=50.0, ema20=100.0, ema50=100.0, adx=15.0, price=100.0,
                         macd_val=0.1, macd_sig=0.1),
        "NEUTRAL_BULLISH": _tech(rsi=50.0, ema20=100.0, ema50=98.0, adx=15.0,
                                  price=100.5, macd_val=0.1, macd_sig=0.0),
        "NEUTRAL_BEARISH": _tech(rsi=50.0, ema20=102.0, ema50=100.0, adx=15.0,
                                  price=99.0, macd_val=-0.1, macd_sig=0.0),
    }

    @pytest.mark.parametrize("signal_key", SIGNALS)
    def test_legacy_fields_always_in_setup(self, monkeypatch, signal_key):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: self.TECHS[signal_key])
        r = generate_trade_setup("NIFTY")
        if "error" in r:
            pytest.skip(f"generate_trade_setup returned error: {r['error']}")
        for field in ("entry", "stoploss", "target"):
            assert field in r, (
                f"Missing legacy field '{field}' for signal={r.get('signal')}"
            )
        # Values must be numeric, not None
        assert r["entry"] is not None
        assert r["stoploss"] is not None
        assert r["target"] is not None


# ---------------------------------------------------------------------------
# Regression 5 — Phase 3 schema: zone fields always present
# ---------------------------------------------------------------------------

class TestReg5ZoneSchema:
    """
    Counterpart to Regression 4: zone fields must also always be present.
    """

    @pytest.mark.parametrize("signal_key", TestReg4LegacySchema.SIGNALS)
    def test_zone_fields_always_in_setup(self, monkeypatch, signal_key):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: TestReg4LegacySchema.TECHS[signal_key])
        r = generate_trade_setup("NIFTY")
        if "error" in r:
            pytest.skip(f"generate_trade_setup returned error: {r['error']}")
        for field in ("entry_above", "entry_below", "bull_target", "bear_target"):
            assert field in r, (
                f"Missing zone field '{field}' for signal={r.get('signal')}"
            )


# ---------------------------------------------------------------------------
# Regression 6 — Phase 5.1: RR < 1 sets trade_allowed=False
# ---------------------------------------------------------------------------

class TestReg6TradeQualityFilter:
    """
    Bug: create_trade_plan() returned trade_allowed=True regardless of RR quality.
    Fix: _trade_quality() classifies RR and LOW_QUALITY sets trade_allowed=False.
    """

    def test_rr_below_1_is_low_quality(self):
        assert _trade_quality(0.5) == "LOW_QUALITY"
        assert _trade_quality(0.99) == "LOW_QUALITY"

    def test_rr_exactly_1_is_moderate(self):
        assert _trade_quality(1.0) == "MODERATE"

    def test_none_rr_is_low_quality(self):
        assert _trade_quality(None) == "LOW_QUALITY"

    def test_low_quality_plan_not_allowed(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: _tech())
        _silence_options(monkeypatch)
        # Force LOW_QUALITY by patching _trade_quality
        monkeypatch.setattr("src.planner.trade_plan._trade_quality",
                            lambda rr: "LOW_QUALITY")
        r = create_trade_plan("NIFTY")
        if r.get("signal") == "NEUTRAL":
            pytest.skip("Signal is NEUTRAL — trade_allowed=False for a different reason")
        assert r["trade_quality"] == "LOW_QUALITY"
        assert r["trade_allowed"] is False

    def test_high_quality_plan_is_allowed(self, monkeypatch):
        monkeypatch.setattr("src.analysis.regime._analyze_technicals",
                            lambda s, lookback_days=150: _tech())
        _silence_options(monkeypatch)
        monkeypatch.setattr("src.planner.trade_plan._trade_quality",
                            lambda rr: "HIGH_QUALITY")
        r = create_trade_plan("NIFTY")
        if r.get("signal") == "NEUTRAL":
            pytest.skip("Signal is NEUTRAL")
        assert r["trade_quality"] == "HIGH_QUALITY"
        assert r["trade_allowed"] is True


# ---------------------------------------------------------------------------
# Regression 7 — Phase 8: equity option chain no longer degrades
# ---------------------------------------------------------------------------

class TestReg7EquityOptionChain:
    """
    Bug: build_option_strategy("NSE:RELIANCE") returned premium_data_available=False
    because the service passed the full "NSE:RELIANCE" prefix to jugaad, which
    returned 0 rows.
    Fix: _strip_exchange_prefix() applied before jugaad call.
    """

    def test_strip_prefix_ensures_bare_symbol_used(self):
        """Unit verification that the strip method exists and works."""
        assert OptionsService._strip_exchange_prefix("NSE:RELIANCE") == "RELIANCE"
        assert OptionsService._strip_exchange_prefix("BSE:INFY") == "INFY"

    def test_equity_chain_fetch_uses_bare_symbol(self, monkeypatch):
        """
        Integration: calling get_option_chain("NSE:RELIANCE") should forward
        "RELIANCE" (not "NSE:RELIANCE") to the jugaad backend.
        """
        received = []

        class FakeNSELive:
            def equities_option_chain(self, symbol, expiry=None):
                received.append(symbol)
                # Return minimal valid chain so no RuntimeError is raised
                return {
                    "records": {
                        "data": [{
                            "strikePrice": 1000,
                            "expiryDates": "26-Jun-2025",
                            "CE": {"openInterest": 1000, "lastPrice": 50.0},
                            "PE": {"openInterest": 1000, "lastPrice": 40.0},
                        }],
                        "expiryDates": ["26-Jun-2025"],
                        "underlyingValue": 1000.0,
                    }
                }

        svc = OptionsService.__new__(OptionsService)
        svc._nse_live = FakeNSELive()
        svc._fetch_via_jugaad("NSE:RELIANCE", expiry=None)
        assert "NSE:RELIANCE" not in received, (
            "Prefixed symbol was forwarded to jugaad — strip fix is broken"
        )
        assert "RELIANCE" in received, (
            f"Expected 'RELIANCE' to be passed to jugaad, got {received}"
        )


# ---------------------------------------------------------------------------
# Regression RH-1 — Phase 14.5: NaN indicators → error, not signal
# ---------------------------------------------------------------------------

class TestRH1NaNDoesNotProduceBuySignal:
    """
    Bug: float('nan') from yfinance NaN rows bypassed the None-membership
    guard (NaN ≠ None in Python), producing directional signals with NaN
    confidence on sparse/halted stocks such as IDEA.
    Fix 1 (service.py): NaN rows filtered at source.
    Fix 2 (regime.py): _is_invalid() catches both None and float('nan').
    """

    def test_nan_data_produces_error_not_signal(self, monkeypatch):
        nan_tech = {
            "symbol": "IDEA",
            "last_close": 12.5,
            "candles_used": 100,
            "rsi_14": float("nan"),
            "ema_20": float("nan"),
            "ema_50": float("nan"),
            "macd": {
                "macd": float("nan"),
                "signal": float("nan"),
                "histogram": float("nan"),
            },
            "adx_14": {
                "adx": float("nan"),
                "plus_di": float("nan"),
                "minus_di": float("nan"),
            },
            "atr_14": float("nan"),
        }
        monkeypatch.setattr(
            "src.analysis.regime._analyze_technicals",
            lambda s, lookback_days=150: nan_tech,
        )
        r = generate_trade_setup("IDEA")
        assert "error" in r, (
            f"NaN indicators must produce an error response, not a signal. Got: {r}"
        )
        assert "signal" not in r


# ---------------------------------------------------------------------------
# Regression RH-2 — Phase 14.5: Confidence capped at 85
# ---------------------------------------------------------------------------

class TestRH2ConfidenceNeverExceeds85:
    """
    Bug: max-alignment indicators (RSI 65, BULL_TREND, ADX 35) could score
    20+15+15+20+20+10 = 100 confidence. No technical indicator model warrants
    100% confidence.
    Fix 5 (regime.py): min(85, confidence).
    """

    def test_max_alignment_confidence_at_most_85(self, monkeypatch):
        max_bull = _tech(rsi=65.0, ema20=100.0, ema50=90.0, adx=35.0, price=101.0)
        monkeypatch.setattr(
            "src.analysis.regime._analyze_technicals",
            lambda s, lookback_days=150: max_bull,
        )
        r = generate_trade_setup("NIFTY")
        assert "error" not in r
        assert r["signal"] == "BUY"
        assert r["confidence"] <= 85, (
            f"Confidence must never exceed 85; got {r['confidence']}"
        )


# ---------------------------------------------------------------------------
# Regression RH-3 — Phase 14.5: RSI overbought reduces confidence
# ---------------------------------------------------------------------------

class TestRH3RSIOverboughtReducesConfidence:
    """
    Bug: RSI 74 scored +20 bullish (identical to RSI 56), producing 100%
    BUY confidence for stocks like YES BANK. Overbought RSI signals elevated
    mean-reversion risk, not bullish momentum.
    Fix 4 (regime.py): RSI > 70 → bearish +10 instead of bullish +20.
    """

    def test_overbought_confidence_lower_than_normal_bullish(self, monkeypatch):
        normal_rsi = _tech(rsi=65.0, ema20=100.0, ema50=90.0, adx=30.0, price=101.0)
        overbought = {**normal_rsi, "rsi_14": 74.0}

        monkeypatch.setattr(
            "src.analysis.regime._analyze_technicals",
            lambda s, lookback_days=150: normal_rsi,
        )
        r_normal = generate_trade_setup("NIFTY")

        monkeypatch.setattr(
            "src.analysis.regime._analyze_technicals",
            lambda s, lookback_days=150: overbought,
        )
        r_overbought = generate_trade_setup("NIFTY")

        assert "error" not in r_overbought
        assert r_overbought["confidence"] < r_normal["confidence"], (
            f"Overbought RSI must reduce confidence vs normal bullish RSI. "
            f"overbought={r_overbought['confidence']}, normal={r_normal['confidence']}"
        )
        reasoning = " ".join(r_overbought["reasoning"])
        assert "overbought" in reasoning.lower()
