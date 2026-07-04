"""
Market structure detection for the chart engine.

Detects swing highs/lows and classifies the pattern as:
  HH-HL  (higher highs + higher lows → uptrend structure)
  LH-LL  (lower highs + lower lows  → downtrend structure)
  ranging (mixed / no clear pattern)

Also detects Break of Structure (BOS) and Change of Character (CHOCH).
"""
from __future__ import annotations

_MIN_CANDLES = 10
_SWING_LOOKBACK = 3  # bars on each side to qualify a swing point


def detect_structure(candles: list[dict]) -> dict:
    if len(candles) < _MIN_CANDLES:
        return _insufficient()

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    swing_highs = _swing_highs(highs, _SWING_LOOKBACK)
    swing_lows = _swing_lows(lows, _SWING_LOOKBACK)

    last_sh = swing_highs[-1] if swing_highs else None
    last_sl = swing_lows[-1] if swing_lows else None

    structure = _classify(swing_highs, swing_lows)
    bos = _detect_bos(highs, lows, swing_highs, swing_lows, structure)
    choch = _detect_choch(swing_highs, swing_lows, structure)

    observations = _observations(structure, bos, choch, last_sh, last_sl)

    return {
        "structure": structure,
        "last_swing_high": round(last_sh, 4) if last_sh is not None else None,
        "last_swing_low": round(last_sl, 4) if last_sl is not None else None,
        "bos": bos,
        "choch": choch,
        "observations": observations,
    }


def _swing_highs(highs: list[float], n: int) -> list[float]:
    result = []
    for i in range(n, len(highs) - n):
        window = highs[i - n: i + n + 1]
        if highs[i] == max(window):
            result.append(highs[i])
    return result


def _swing_lows(lows: list[float], n: int) -> list[float]:
    result = []
    for i in range(n, len(lows) - n):
        window = lows[i - n: i + n + 1]
        if lows[i] == min(window):
            result.append(lows[i])
    return result


def _classify(swing_highs: list[float], swing_lows: list[float]) -> str:
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "ranging"

    # Check last two swing highs and lows
    hh = swing_highs[-1] > swing_highs[-2]
    hl = swing_lows[-1] > swing_lows[-2]
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1] < swing_lows[-2]

    if hh and hl:
        return "HH-HL"
    if lh and ll:
        return "LH-LL"
    return "ranging"


def _detect_bos(
    highs: list[float],
    lows: list[float],
    swing_highs: list[float],
    swing_lows: list[float],
    structure: str,
) -> bool:
    """Break of Structure: latest close breaks through the last swing high/low."""
    if not highs or not lows:
        return False
    last_close = highs[-1]  # use last high as proxy; close is more accurate but not always present
    if structure == "LH-LL" and swing_highs:
        return last_close > swing_highs[-1]
    if structure == "HH-HL" and swing_lows:
        return lows[-1] < swing_lows[-1]
    return False


def _detect_choch(
    swing_highs: list[float],
    swing_lows: list[float],
    structure: str,
) -> bool:
    """Change of Character: structure has flipped direction in last two swings."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return False
    if structure == "ranging":
        # Check if previous was trending
        prev_hh = swing_highs[-2] > (swing_highs[-3] if len(swing_highs) > 2 else swing_highs[-2])
        prev_ll = swing_lows[-2] < (swing_lows[-3] if len(swing_lows) > 2 else swing_lows[-2])
        return prev_hh or prev_ll
    return False


def _observations(
    structure: str,
    bos: bool,
    choch: bool,
    last_sh: float | None,
    last_sl: float | None,
) -> list[str]:
    obs = []
    if structure == "HH-HL":
        obs.append("Market structure is bullish: higher highs and higher lows")
    elif structure == "LH-LL":
        obs.append("Market structure is bearish: lower highs and lower lows")
    else:
        obs.append("Market structure is ranging: no clear directional pattern")
    if last_sh is not None:
        obs.append(f"Last swing high at {last_sh:,.2f}")
    if last_sl is not None:
        obs.append(f"Last swing low at {last_sl:,.2f}")
    if bos:
        obs.append("Break of structure detected on latest bar")
    if choch:
        obs.append("Change of character detected — structure may be shifting")
    return obs


def _insufficient() -> dict:
    return {
        "structure": "ranging",
        "last_swing_high": None,
        "last_swing_low": None,
        "bos": False,
        "choch": False,
        "observations": ["Insufficient data for structure analysis"],
    }
