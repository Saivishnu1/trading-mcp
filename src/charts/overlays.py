from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.technical.indicators import _wilder_smooth, ema_series

# ---------------------------------------------------------------------------
# Indicator series helpers
# ---------------------------------------------------------------------------

def get_ema_series(closes: list[float], period: int) -> list[float | None]:
    series = ema_series(closes, period)
    if not series:
        return [None] * len(closes)
    return [None] * (period - 1) + series


def get_bollinger_bands(closes: list[float], period: int = 20, std_mult: float = 2.0) -> tuple[list[float | None], list[float | None], list[float | None]]:
    upper: list[float | None] = []
    lower: list[float | None] = []
    mid: list[float | None] = []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(None)
            lower.append(None)
            mid.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            m = sum(window) / period
            var = sum((x - m) ** 2 for x in window) / period
            std = var ** 0.5
            upper.append(m + std_mult * std)
            lower.append(m - std_mult * std)
            mid.append(m)
    return upper, lower, mid


def get_vwap_series(highs: list[float], lows: list[float], closes: list[float], volumes: list[float]) -> list[float | None]:
    if not volumes or sum(volumes) == 0:
        return [None] * len(closes)
    num = 0.0
    den = 0.0
    vwap = []
    for h, l, c, v in zip(highs, lows, closes, volumes):
        tp = (h + l + c) / 3.0
        num += tp * v
        den += v
        vwap.append(num / den if den > 0 else None)
    return vwap


def get_macd_series(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    fast_ema = ema_series(closes, fast)
    slow_ema = ema_series(closes, slow)
    if not fast_ema or not slow_ema:
        return [None] * len(closes), [None] * len(closes), [None] * len(closes)

    fast_aligned = [None] * (fast - 1) + fast_ema
    slow_aligned = [None] * (slow - 1) + slow_ema

    macd_line: list[float | None] = []
    for f, s in zip(fast_aligned, slow_aligned):
        if f is not None and s is not None:
            macd_line.append(f - s)
        else:
            macd_line.append(None)

    valid_macd = [x for x in macd_line if x is not None]
    sig_series = ema_series(valid_macd, signal) if len(valid_macd) >= signal else []

    sig_aligned = [None] * (slow - 1 + signal - 1) + sig_series
    if len(sig_aligned) < len(closes):
        sig_aligned += [None] * (len(closes) - len(sig_aligned))

    hist: list[float | None] = []
    for m, s in zip(macd_line, sig_aligned):
        if m is not None and s is not None:
            hist.append(m - s)
        else:
            hist.append(None)

    return macd_line, sig_aligned, hist


def get_rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    if len(closes) < period + 1:
        return [None] * len(closes)
    gains, losses = [], []
    for prev, cur in zip(closes, closes[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = _wilder_smooth(gains, period)
    avg_loss = _wilder_smooth(losses, period)

    rsi_line: list[float | None] = [None] * period
    for g, l in zip(avg_gain, avg_loss):
        if l == 0:
            rsi_line.append(100.0)
        else:
            rs = g / l
            rsi_line.append(100.0 - (100.0 / (1.0 + rs)))

    if len(rsi_line) < len(closes):
        rsi_line += [None] * (len(closes) - len(rsi_line))
    return rsi_line


def clean_series(series: list[float | None]) -> np.ndarray:
    """Helper to convert list with None values to numpy float array with np.nan."""
    return np.array([x if x is not None else np.nan for x in series], dtype=float)


# ---------------------------------------------------------------------------
# Overlay plotting methods
# ---------------------------------------------------------------------------

class ChartOverlays:

    @staticmethod
    def add_ema(ax: plt.Axes, df: pd.DataFrame, period: int, color: str, label: str) -> None:
        closes = df["close"].tolist()
        ema = clean_series(get_ema_series(closes, period))
        ax.plot(df.index, ema, color=color, label=label, linewidth=1.2)

    @staticmethod
    def add_vwap(ax: plt.Axes, df: pd.DataFrame, color: str, label: str) -> None:
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        closes = df["close"].tolist()
        volumes = df["volume"].tolist()
        vwap = clean_series(get_vwap_series(highs, lows, closes, volumes))
        if not np.all(np.isnan(vwap)):
            ax.plot(df.index, vwap, color=color, label=label, linewidth=1.2, linestyle="--")

    @staticmethod
    def add_bollinger(ax: plt.Axes, df: pd.DataFrame, color: str) -> None:
        closes = df["close"].tolist()
        upper, lower, mid = get_bollinger_bands(closes, 20, 2.0)
        upper_arr = clean_series(upper)
        lower_arr = clean_series(lower)
        mid_arr = clean_series(mid)

        ax.plot(df.index, upper_arr, color=color, alpha=0.5, linestyle=":", label="BB Upper")
        ax.plot(df.index, lower_arr, color=color, alpha=0.5, linestyle=":", label="BB Lower")
        ax.plot(df.index, mid_arr, color=color, alpha=0.3, linestyle="-.", label="BB Basis")
        # Shade Bollinger channel
        ax.fill_between(df.index, lower_arr, upper_arr, color=color, alpha=0.05)

    @staticmethod
    def add_support_resistance(ax: plt.Axes, levels: dict, color_up: str, color_down: str) -> None:
        supports = levels.get("supports", [])
        resistances = levels.get("resistances", [])
        for sup in supports:
            level = sup if isinstance(sup, (int, float)) else sup.get("level")
            ax.axhline(level, color=color_up, linestyle="--", alpha=0.4, linewidth=1.0)
        for res in resistances:
            level = res if isinstance(res, (int, float)) else res.get("level")
            ax.axhline(level, color=color_down, linestyle="--", alpha=0.4, linewidth=1.0)

    @staticmethod
    def add_pattern_zones(ax: plt.Axes, patterns: list, df: pd.DataFrame) -> None:
        for p in patterns:
            neckline = p.get("neckline")
            if neckline and neckline > 0:
                ax.axhline(neckline, color="#ab47bc", linestyle=":", alpha=0.6, label=f"Neckline: {p.get('pattern')}")

    @staticmethod
    def add_volume(ax: plt.Axes, df: pd.DataFrame, up_color: str, down_color: str) -> None:
        colors = [up_color if c >= o else down_color for c, o in zip(df["close"], df["open"])]
        ax.bar(df.index, df["volume"], color=colors, width=0.6, alpha=0.7)
        ax.set_ylabel("Volume", fontsize=9)

    @staticmethod
    def add_macd(ax: plt.Axes, df: pd.DataFrame, colors: dict) -> None:
        closes = df["close"].tolist()
        macd_line, sig_line, hist = get_macd_series(closes)
        macd_arr = clean_series(macd_line)
        sig_arr = clean_series(sig_line)
        hist_arr = clean_series(hist)

        ax.plot(df.index, macd_arr, color=colors["macd"], label="MACD", linewidth=1.2)
        ax.plot(df.index, sig_arr, color=colors["signal"], label="Signal", linewidth=1.2)

        hist_colors = []
        for h in hist:
            if h is None or (isinstance(h, float) and np.isnan(h)):
                hist_colors.append(colors["grid"])
            elif h >= 0:
                hist_colors.append(colors["histogram_pos"])
            else:
                hist_colors.append(colors["histogram_neg"])

        ax.bar(df.index, hist_arr, color=hist_colors, width=0.6, alpha=0.6, label="Histogram")

        ax.axhline(0, color=colors["grid"], linestyle="-", alpha=0.5, linewidth=0.8)
        ax.set_ylabel("MACD", fontsize=9)
        ax.legend(loc="upper left", frameon=False, fontsize=8)

    @staticmethod
    def add_rsi(ax: plt.Axes, df: pd.DataFrame, color: str, grid_color: str) -> None:
        closes = df["close"].tolist()
        rsi = clean_series(get_rsi_series(closes))

        ax.plot(df.index, rsi, color=color, label="RSI(14)", linewidth=1.2)

        ax.axhline(70, color="#ef5350", linestyle="--", alpha=0.5, linewidth=0.8)
        ax.axhline(30, color="#26a69a", linestyle="--", alpha=0.5, linewidth=0.8)
        ax.axhline(50, color=grid_color, linestyle=":", alpha=0.5, linewidth=0.8)

        ax.set_ylabel("RSI", fontsize=9)
        ax.set_ylim(10, 90)
        ax.legend(loc="upper left", frameon=False, fontsize=8)
