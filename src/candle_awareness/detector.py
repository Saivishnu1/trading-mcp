"""
Individual candlestick pattern detection functions.

All detectors work on raw OHLCV row/rows (pandas Series or dict-like).
Return a list of (name, pattern_type) tuples — empty if not detected.
"""
from __future__ import annotations

_DOJI_THRESHOLD = 0.001   # body ≤ 0.1% of range = doji
_SMALL_BODY = 0.3         # body ≤ 30% of range = small body
_LONG_WICK = 2.0          # wick ≥ 2× body = long wick
_ENGULF_BODY = 1.0        # engulfing body must fully cover prior body


def _ohlc(row) -> tuple[float, float, float, float]:
    return float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])


def _body(o, c) -> float:
    return abs(c - o)


def _range(h, l) -> float:
    return h - l if h > l else 1e-9


def _upper_wick(o, h, c) -> float:
    return h - max(o, c)


def _lower_wick(o, l, c) -> float:
    return min(o, c) - l


def _is_bullish(o, c) -> bool:
    return c > o


def _is_bearish(o, c) -> bool:
    return c < o


def _midpoint(o, c) -> float:
    return (o + c) / 2


class SingleCandleDetectors:

    def detect(self, row) -> list[tuple[str, str]]:
        o, h, l, c = _ohlc(row)
        rng = _range(h, l)
        body = _body(o, c)
        upper = _upper_wick(o, h, c)
        lower = _lower_wick(o, l, c)
        results = []

        # Doji — body ≤ 0.1% of range
        if body <= _DOJI_THRESHOLD * rng:
            if upper < rng * 0.05 and lower > rng * 0.6:
                results.append(("Dragonfly Doji", "bullish"))
            elif lower < rng * 0.05 and upper > rng * 0.6:
                results.append(("Gravestone Doji", "bearish"))
            else:
                results.append(("Doji", "neutral"))

        # Marubozu — body ≥ 90% of range, tiny wicks
        elif body >= rng * 0.9 and upper < rng * 0.05 and lower < rng * 0.05:
            if _is_bullish(o, c):
                results.append(("Bullish Marubozu", "bullish"))
            else:
                results.append(("Bearish Marubozu", "bearish"))

        # Spinning Top — small body ≤ 30% of range, roughly equal wicks
        elif body <= _SMALL_BODY * rng and upper > rng * 0.2 and lower > rng * 0.2:
            if abs(upper - lower) <= rng * 0.15:
                results.append(("Spinning Top", "neutral"))

        # Hammer — small body at top, long lower wick (≥2× body), small upper wick
        if (body <= _SMALL_BODY * rng and
                lower >= _LONG_WICK * max(body, 1e-9) and
                upper <= body * 0.5 and
                lower >= rng * 0.5):
            results.append(("Hammer", "bullish"))

        # Inverted Hammer — small body at bottom, long upper wick, small lower wick
        if (body <= _SMALL_BODY * rng and
                upper >= _LONG_WICK * max(body, 1e-9) and
                lower <= body * 0.5 and
                upper >= rng * 0.5):
            results.append(("Inverted Hammer", "bullish"))

        # Shooting Star — same shape as inverted hammer but bearish context
        # (detection is identical; context/strength classified later)
        if (body <= _SMALL_BODY * rng and
                upper >= _LONG_WICK * max(body, 1e-9) and
                lower <= body * 0.5 and
                upper >= rng * 0.5 and
                _is_bearish(o, c)):
            results.append(("Shooting Star", "bearish"))

        return results


class TwoCandleDetectors:

    def detect(self, prev, curr) -> list[tuple[str, str]]:
        po, ph, pl, pc = _ohlc(prev)
        co, ch, cl, cc = _ohlc(curr)
        prev_body = _body(po, pc)
        curr_body = _body(co, cc)
        results = []

        # Bullish Engulfing — prev bearish, curr bullish, curr body engulfs prev
        if (_is_bearish(po, pc) and _is_bullish(co, cc) and
                co <= pc and cc >= po and curr_body > prev_body):
            results.append(("Bullish Engulfing", "bullish"))

        # Bearish Engulfing — prev bullish, curr bearish, curr body engulfs prev
        if (_is_bullish(po, pc) and _is_bearish(co, cc) and
                co >= pc and cc <= po and curr_body > prev_body):
            results.append(("Bearish Engulfing", "bearish"))

        # Bullish Harami — large bearish prev, small bullish curr inside prev body
        if (_is_bearish(po, pc) and _is_bullish(co, cc) and
                prev_body > 0 and curr_body <= prev_body * 0.5 and
                co >= pc and cc <= po):
            results.append(("Bullish Harami", "bullish"))

        # Bearish Harami — large bullish prev, small bearish curr inside prev body
        if (_is_bullish(po, pc) and _is_bearish(co, cc) and
                prev_body > 0 and curr_body <= prev_body * 0.5 and
                co <= pc and cc >= po):
            results.append(("Bearish Harami", "bearish"))

        # Tweezer Bottom — both lows within 0.1% of each other
        if abs(pl - cl) <= 0.001 * max(pl, cl) and _is_bullish(co, cc):
            results.append(("Tweezer Bottom", "bullish"))

        # Tweezer Top — both highs within 0.1% of each other
        if abs(ph - ch) <= 0.001 * max(ph, ch) and _is_bearish(co, cc):
            results.append(("Tweezer Top", "bearish"))

        # Piercing Line — bearish prev, bullish curr opens below prev low,
        # closes above midpoint of prev body
        if (_is_bearish(po, pc) and _is_bullish(co, cc) and
                co < pl and cc > _midpoint(po, pc)):
            results.append(("Piercing Line", "bullish"))

        # Dark Cloud Cover — bullish prev, bearish curr opens above prev high,
        # closes below midpoint of prev body
        if (_is_bullish(po, pc) and _is_bearish(co, cc) and
                co > ph and cc < _midpoint(po, pc)):
            results.append(("Dark Cloud Cover", "bearish"))

        return results


class ThreeCandleDetectors:

    def detect(self, c1, c2, c3) -> list[tuple[str, str]]:
        o1, h1, l1, cl1 = _ohlc(c1)
        o2, h2, l2, cl2 = _ohlc(c2)
        o3, h3, l3, cl3 = _ohlc(c3)
        b1 = _body(o1, cl1)
        b2 = _body(o2, cl2)
        b3 = _body(o3, cl3)
        results = []

        # Morning Star — bearish, small/doji middle, bullish; cl3 > midpoint of c1
        if (_is_bearish(o1, cl1) and b1 > 0 and
                b2 <= b1 * 0.4 and
                _is_bullish(o3, cl3) and cl3 > _midpoint(o1, cl1)):
            results.append(("Morning Star", "bullish"))

        # Evening Star — bullish, small/doji middle, bearish; cl3 < midpoint of c1
        if (_is_bullish(o1, cl1) and b1 > 0 and
                b2 <= b1 * 0.4 and
                _is_bearish(o3, cl3) and cl3 < _midpoint(o1, cl1)):
            results.append(("Evening Star", "bearish"))

        # Three White Soldiers — three consecutive bullish candles, each closing higher
        if (_is_bullish(o1, cl1) and _is_bullish(o2, cl2) and _is_bullish(o3, cl3) and
                cl2 > cl1 and cl3 > cl2 and
                o2 >= o1 and o3 >= o2):
            results.append(("Three White Soldiers", "bullish"))

        # Three Black Crows — three consecutive bearish candles, each closing lower
        if (_is_bearish(o1, cl1) and _is_bearish(o2, cl2) and _is_bearish(o3, cl3) and
                cl2 < cl1 and cl3 < cl2 and
                o2 <= o1 and o3 <= o2):
            results.append(("Three Black Crows", "bearish"))

        # Three Inside Up — bullish harami (c1, c2) + bullish confirmation (c3)
        if (_is_bearish(o1, cl1) and _is_bullish(o2, cl2) and
                b2 <= b1 * 0.5 and o2 >= cl1 and cl2 <= o1 and
                _is_bullish(o3, cl3) and cl3 > cl2):
            results.append(("Three Inside Up", "bullish"))

        # Three Inside Down — bearish harami (c1, c2) + bearish confirmation (c3)
        if (_is_bullish(o1, cl1) and _is_bearish(o2, cl2) and
                b2 <= b1 * 0.5 and o2 <= cl1 and cl2 >= o1 and
                _is_bearish(o3, cl3) and cl3 < cl2):
            results.append(("Three Inside Down", "bearish"))

        return results
