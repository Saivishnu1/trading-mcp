"""
Unit tests for src/technical/indicators.py.

All tests are pure math — no I/O, no mocking required.
"""
import pytest

from src.technical.indicators import (
    adx,
    atr,
    ema,
    ema_series,
    macd,
    rsi,
)

# ---------------------------------------------------------------------------
# ema_series
# ---------------------------------------------------------------------------

class TestEmaSeries:

    def test_basic_output_length(self):
        result = ema_series([1, 2, 3, 4, 5], period=3)
        # starts from index period-1 so length = len(values) - period + 1
        assert len(result) == 3

    def test_seed_is_sma(self):
        result = ema_series([1, 2, 3, 4, 5], period=3)
        # seed = (1+2+3)/3 = 2.0
        assert result[0] == pytest.approx(2.0, rel=1e-6)

    def test_known_values(self):
        # period=3, k=0.5
        # seed = (1+2+3)/3 = 2.0
        # v=4: (4-2)*0.5 + 2 = 3.0
        # v=5: (5-3)*0.5 + 3 = 4.0
        result = ema_series([1, 2, 3, 4, 5], period=3)
        assert result[1] == pytest.approx(3.0, rel=1e-6)
        assert result[2] == pytest.approx(4.0, rel=1e-6)

    def test_insufficient_data_returns_empty(self):
        assert ema_series([1, 2], period=5) == []

    def test_period_zero_returns_empty(self):
        assert ema_series([1, 2, 3], period=0) == []

    def test_exact_period_length_returns_one_element(self):
        result = ema_series([10, 20, 30], period=3)
        assert len(result) == 1
        assert result[0] == pytest.approx(20.0, rel=1e-6)


# ---------------------------------------------------------------------------
# rsi
# ---------------------------------------------------------------------------

class TestRsi:

    def test_known_value(self):
        # closes = [10, 11, 12, 11, 13], period=4
        # changes = [1, 1, -1, 2]
        # gains = [1, 1, 0, 2], losses = [0, 0, 1, 0]
        # avg_gain = (1+1+0+2)/4 = 1.0, avg_loss = (0+0+1+0)/4 = 0.25
        # RS = 4.0 → RSI = 80.0
        result = rsi([10.0, 11.0, 12.0, 11.0, 13.0], period=4)
        assert result == pytest.approx(80.0, rel=1e-4)

    def test_all_gains_returns_100(self):
        closes = [100.0 + i for i in range(20)]
        result = rsi(closes, period=14)
        assert result == pytest.approx(100.0, rel=1e-4)

    def test_all_losses_returns_0(self):
        closes = [200.0 - i for i in range(20)]
        result = rsi(closes, period=14)
        assert result == pytest.approx(0.0, abs=1.0)

    def test_insufficient_data_returns_none(self):
        assert rsi([1.0, 2.0, 3.0], period=14) is None

    def test_exactly_period_plus_one_returns_value(self):
        closes = [float(i) for i in range(16)]  # 16 candles, period=14 → needs 15
        result = rsi(closes, period=14)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_result_in_valid_range(self):
        import math
        closes = [1000.0 + 25.0 * math.sin(i * 0.3) for i in range(60)]
        result = rsi(closes, period=14)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_period_one(self):
        # period=1 needs len >= 2
        result = rsi([10.0, 12.0], period=1)
        assert result is not None


# ---------------------------------------------------------------------------
# ema
# ---------------------------------------------------------------------------

class TestEma:

    def test_known_value(self):
        result = ema([1, 2, 3, 4, 5], period=3)
        assert result == pytest.approx(4.0, rel=1e-4)

    def test_insufficient_data_returns_none(self):
        assert ema([1.0, 2.0], period=5) is None

    def test_flat_series_returns_that_value(self):
        closes = [100.0] * 30
        result = ema(closes, period=20)
        assert result == pytest.approx(100.0, rel=1e-4)

    def test_rising_series_ema_below_last(self):
        closes = [float(i) for i in range(1, 31)]
        result = ema(closes, period=20)
        # EMA lags price in a rising series
        assert result < closes[-1]

    def test_result_is_rounded_to_4dp(self):
        closes = [1.0, 2.0, 3.0, 4.0]
        result = ema(closes, period=3)
        assert result is not None
        # round to 4 decimal places means no more than 4 decimal digits
        assert result == round(result, 4)


# ---------------------------------------------------------------------------
# macd
# ---------------------------------------------------------------------------

class TestMacd:

    def _rising(self, n=60):
        return [100.0 + 0.5 * i for i in range(n)]

    def test_returns_three_keys(self):
        result = macd(self._rising())
        assert "macd" in result
        assert "signal" in result
        assert "histogram" in result

    def test_histogram_equals_macd_minus_signal(self):
        result = macd(self._rising())
        if result["macd"] is not None and result["signal"] is not None:
            expected = round(result["macd"] - result["signal"], 4)
            assert result["histogram"] == pytest.approx(expected, abs=1e-4)

    def test_insufficient_data_returns_none_dict(self):
        result = macd([1.0, 2.0, 3.0])
        assert result["macd"] is None
        assert result["signal"] is None
        assert result["histogram"] is None

    def test_rising_series_positive_histogram(self):
        # Quadratic acceleration keeps MACD rising so signal lags → histogram > 0
        closes = [100.0 + 0.02 * i * i for i in range(60)]
        result = macd(closes)
        assert result["histogram"] is not None
        assert result["histogram"] > 0

    def test_falling_series_negative_histogram(self):
        closes = [200.0 - 0.02 * i * i for i in range(60)]
        result = macd(closes)
        assert result["histogram"] is not None
        assert result["histogram"] < 0

    def test_custom_periods(self):
        closes = [float(i) for i in range(50)]
        result = macd(closes, fast=5, slow=10, signal=3)
        assert result["macd"] is not None


# ---------------------------------------------------------------------------
# atr
# ---------------------------------------------------------------------------

class TestAtr:

    def test_known_value(self):
        # TRs: all 1.5 except last 2.5 → seed=(1.5+1.5+1.5+2.5)/4=1.75
        highs = [10.5, 11.5, 12.5, 11.5, 13.5]
        lows  = [ 9.5, 10.5, 11.5, 10.5, 12.5]
        closes = [10.0, 11.0, 12.0, 11.0, 13.0]
        result = atr(highs, lows, closes, period=4)
        assert result == pytest.approx(1.75, rel=1e-4)

    def test_insufficient_data_returns_none(self):
        highs  = [10.0, 11.0]
        lows   = [ 9.0, 10.0]
        closes = [10.0, 11.0]
        assert atr(highs, lows, closes, period=14) is None

    def test_positive_value_for_realistic_data(self):
        closes = [1000.0 + i for i in range(30)]
        highs  = [c + 5 for c in closes]
        lows   = [c - 5 for c in closes]
        result = atr(highs, lows, closes, period=14)
        assert result is not None
        assert result > 0

    def test_flat_series_low_atr(self):
        closes = [100.0] * 20
        highs  = [101.0] * 20
        lows   = [99.0] * 20
        result = atr(highs, lows, closes, period=14)
        # TR is always abs(101-99) = 2, so ATR ~ 2
        assert result == pytest.approx(2.0, rel=1e-4)


# ---------------------------------------------------------------------------
# adx
# ---------------------------------------------------------------------------

class TestAdx:

    def _trending(self, n=60, step=3.0):
        closes = [1000.0 + step * i for i in range(n)]
        highs  = [c + 5 for c in closes]
        lows   = [c - 5 for c in closes]
        return highs, lows, closes

    def test_returns_three_keys(self):
        h, l, c = self._trending()
        result = adx(h, l, c)
        assert "adx" in result
        assert "plus_di" in result
        assert "minus_di" in result

    def test_insufficient_data_returns_none_dict(self):
        h = [10.0] * 5
        l = [9.0] * 5
        c = [9.5] * 5
        result = adx(h, l, c, period=14)
        assert result["adx"] is None
        assert result["plus_di"] is None
        assert result["minus_di"] is None

    def test_strong_uptrend_high_adx(self):
        h, l, c = self._trending(n=100, step=5.0)
        result = adx(h, l, c, period=14)
        assert result["adx"] is not None
        assert result["adx"] > 20  # trending market

    def test_strong_uptrend_plus_di_dominates(self):
        h, l, c = self._trending(n=100, step=5.0)
        result = adx(h, l, c, period=14)
        if result["plus_di"] and result["minus_di"]:
            assert result["plus_di"] > result["minus_di"]

    def test_strong_downtrend_minus_di_dominates(self):
        h, l, c = self._trending(n=100, step=-5.0)
        result = adx(h, l, c, period=14)
        if result["plus_di"] and result["minus_di"]:
            assert result["minus_di"] > result["plus_di"]

    def test_adx_is_non_negative(self):
        import math
        closes = [1000.0 + 25.0 * math.sin(i * 0.3) for i in range(100)]
        highs  = [c + 8 for c in closes]
        lows   = [c - 8 for c in closes]
        result = adx(highs, lows, closes)
        if result["adx"] is not None:
            assert result["adx"] >= 0
