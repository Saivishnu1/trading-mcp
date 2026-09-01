from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.charts.config import CHART_SPECS
from src.charts.overlays import ChartOverlays
from src.charts.styles import get_theme
from src.charts.utils import fig_to_base64
from src.options.analytics import calculate_max_pain
from src.options_awareness.oi_analyzer import OIAnalyzer


class ChartRenderer:

    def render_price_chart(
        self,
        df: pd.DataFrame,
        symbol: str,
        indicators: dict,
        levels: dict,
        patterns: list,
        theme: str = "dark",
        show_volume: bool = True,
        show_ema: bool = True,
        show_vwap: bool = False,
        show_bb: bool = False,
    ) -> str:
        colors = get_theme(theme)
        spec = CHART_SPECS["price"]

        if show_volume:
            fig, (ax1, ax2) = plt.subplots(
                2, 1, figsize=spec["figsize"], dpi=spec["dpi"], sharex=True,
                gridspec_kw={"height_ratios": spec["panel_ratios"]}
            )
        else:
            fig, ax1 = plt.subplots(1, 1, figsize=(spec["figsize"][0], 6), dpi=spec["dpi"])
            ax2 = None

        try:
            fig.patch.set_facecolor(colors["background"])
            ax1.set_facecolor(colors["background"])
            if ax2:
                ax2.set_facecolor(colors["background"])

            # Draw Candlesticks
            for i in range(len(df)):
                o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
                color = colors["candle_up"] if c >= o else colors["candle_down"]
                # Wick
                ax1.plot([i, i], [l, h], color=color, linewidth=1.2)
                # Body
                ax1.bar(i, c - o, bottom=o, color=color, width=0.6)

            # Plot overlays
            if show_ema:
                ChartOverlays.add_ema(ax1, df, 20, colors["ema20"], "EMA 20")
                ChartOverlays.add_ema(ax1, df, 50, colors["ema50"], "EMA 50")
                ChartOverlays.add_ema(ax1, df, 200, colors["ema200"], "EMA 200")

            if show_vwap:
                ChartOverlays.add_vwap(ax1, df, colors["vwap"], "VWAP")

            if show_bb:
                ChartOverlays.add_bollinger(ax1, df, colors["ema50"])

            ChartOverlays.add_support_resistance(ax1, levels, colors["candle_up"], colors["candle_down"])
            ChartOverlays.add_pattern_zones(ax1, patterns, df)

            # Volume Panel
            if show_volume and ax2:
                ChartOverlays.add_volume(ax2, df, colors["volume_up"], colors["volume_down"])

            # Format axes
            ax1.tick_params(colors=colors["text"], labelsize=9)
            ax1.yaxis.label.set_color(colors["text"])
            ax1.grid(True, color=colors["grid"], linestyle=":", alpha=0.5)
            ax1.legend(loc="upper left", facecolor=colors["background"], edgecolor=colors["grid"], labelcolor=colors["text"], fontsize=8)
            ax1.set_title(f"{symbol} - Price Chart", color=colors["text"], fontsize=12, fontweight="bold")

            active_ax = ax2 if (show_volume and ax2) else ax1
            active_ax.tick_params(colors=colors["text"], labelsize=9)
            active_ax.grid(True, color=colors["grid"], linestyle=":", alpha=0.5)

            # Set date tick labels
            step = max(1, len(df) // 10)
            active_ax.set_xticks(range(0, len(df), step))
            if "datetime" in df.columns:
                date_labels = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d").tolist()
            elif "date" in df.columns:
                date_labels = df["date"].tolist()
            else:
                date_labels = [str(x) for x in df.index]

            active_ax.set_xticklabels([date_labels[j] for j in range(0, len(df), step)], rotation=30, ha="right", color=colors["text"])

            fig.tight_layout()
            return fig_to_base64(fig)
        finally:
            plt.close(fig)

    def render_indicator_chart(
        self,
        df: pd.DataFrame,
        symbol: str,
        indicators: dict,
        theme: str = "dark",
    ) -> str:
        colors = get_theme(theme)
        spec = CHART_SPECS["indicator"]

        fig, (ax1, ax2, ax3) = plt.subplots(
            3, 1, figsize=spec["figsize"], dpi=spec["dpi"], sharex=True,
            gridspec_kw={"height_ratios": spec["panel_ratios"]}
        )

        try:
            fig.patch.set_facecolor(colors["background"])
            for ax in (ax1, ax2, ax3):
                ax.set_facecolor(colors["background"])
                ax.tick_params(colors=colors["text"], labelsize=9)
                ax.grid(True, color=colors["grid"], linestyle=":", alpha=0.5)

            # Candlesticks
            for i in range(len(df)):
                o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
                color = colors["candle_up"] if c >= o else colors["candle_down"]
                ax1.plot([i, i], [l, h], color=color, linewidth=1.2)
                ax1.bar(i, c - o, bottom=o, color=color, width=0.6)

            ax1.set_title(f"{symbol} - Technical Indicators", color=colors["text"], fontsize=12, fontweight="bold")

            # MACD on ax2
            ChartOverlays.add_macd(ax2, df, colors)

            # RSI on ax3
            ChartOverlays.add_rsi(ax3, df, colors["rsi"], colors["grid"])

            # Set date tick labels on bottom plot
            step = max(1, len(df) // 10)
            ax3.set_xticks(range(0, len(df), step))
            if "datetime" in df.columns:
                date_labels = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d").tolist()
            elif "date" in df.columns:
                date_labels = df["date"].tolist()
            else:
                date_labels = [str(x) for x in df.index]

            ax3.set_xticklabels([date_labels[j] for j in range(0, len(df), step)], rotation=30, ha="right", color=colors["text"])

            fig.tight_layout()
            return fig_to_base64(fig)
        finally:
            plt.close(fig)

    def render_option_chart(
        self,
        chain: dict,
        symbol: str,
        spot: float,
        theme: str = "dark",
    ) -> str:
        colors = get_theme(theme)
        spec = CHART_SPECS["option"]

        from src.options.analytics import _strikes_for_expiry
        rows = _strikes_for_expiry(chain, None)

        oi_data = []
        for r in rows:
            sp = r.get("strikePrice")
            ce_oi = r.get("CE", {}).get("openInterest", 0) or 0
            pe_oi = r.get("PE", {}).get("openInterest", 0) or 0
            if sp is not None:
                oi_data.append((sp, ce_oi, pe_oi))

        oi_data.sort(key=lambda x: x[0])

        fig, ax = plt.subplots(1, 1, figsize=spec["figsize"], dpi=spec["dpi"])

        try:
            fig.patch.set_facecolor(colors["background"])
            ax.set_facecolor(colors["background"])
            ax.tick_params(colors=colors["text"], labelsize=9)
            ax.grid(True, color=colors["grid"], linestyle=":", alpha=0.5)

            if not oi_data:
                ax.text(0.5, 0.5, "No Options Data Available", color=colors["text"], ha="center", va="center")
                return fig_to_base64(fig)

            # Filter strikes window around spot price
            strikes = np.array([x[0] for x in oi_data])
            if spot:
                idx = np.argmin(np.abs(strikes - spot))
                start_idx = max(0, idx - 15)
                end_idx = min(len(oi_data), idx + 16)
                window_data = oi_data[start_idx:end_idx]
            else:
                window_data = oi_data

            strikes_win = np.array([x[0] for x in window_data])
            calls_oi = np.array([x[1] for x in window_data])
            puts_oi = np.array([x[2] for x in window_data])

            # Side-by-side bars
            strike_step = (strikes_win[1] - strikes_win[0]) if len(strikes_win) > 1 else 100
            width = strike_step * 0.35

            ax.bar(strikes_win - width/2, calls_oi, width=width, color=colors["candle_down"], label="Call OI", alpha=0.8)
            ax.bar(strikes_win + width/2, puts_oi, width=width, color=colors["candle_up"], label="Put OI", alpha=0.8)

            # Spot and indicators lines
            if spot:
                ax.axvline(spot, color=colors["text"], linestyle="-", linewidth=1.5, label=f"Spot: {spot:,.1f}")

            walls = OIAnalyzer.detect_walls(chain)
            call_wall = walls.get("call_wall")
            put_wall = walls.get("put_wall")

            mp_res = calculate_max_pain(chain, None)
            max_pain = mp_res.get("max_pain")

            if max_pain:
                ax.axvline(max_pain, color=colors["ema20"], linestyle="--", linewidth=1.2, label=f"Max Pain: {max_pain:,.1f}")
            if call_wall:
                ax.axvline(call_wall, color="#ab47bc", linestyle="-.", linewidth=1.2, label=f"Call Wall: {call_wall:,.1f}")
            if put_wall:
                ax.axvline(put_wall, color="#ff6b6b", linestyle="-.", linewidth=1.2, label=f"Put Wall: {put_wall:,.1f}")

            ax.set_title(f"{symbol} Options Open Interest by Strike", color=colors["text"], fontsize=12, fontweight="bold")
            ax.set_xlabel("Strike Price", color=colors["text"], fontsize=10)
            ax.set_ylabel("Open Interest", color=colors["text"], fontsize=10)
            ax.legend(loc="upper left", facecolor=colors["background"], edgecolor=colors["grid"], labelcolor=colors["text"], fontsize=8)

            fig.tight_layout()
            return fig_to_base64(fig)
        finally:
            plt.close(fig)

    def render_combined_chart(
        self,
        df: pd.DataFrame,
        symbol: str,
        indicators: dict,
        levels: dict,
        chain: dict,
        theme: str = "dark",
    ) -> str:
        colors = get_theme(theme)
        spec = CHART_SPECS["combined"]

        fig, (ax1, ax2, ax3, ax4) = plt.subplots(
            4, 1, figsize=spec["figsize"], dpi=spec["dpi"], sharex=True,
            gridspec_kw={"height_ratios": spec["panel_ratios"]}
        )

        try:
            fig.patch.set_facecolor(colors["background"])
            for ax in (ax1, ax2, ax3, ax4):
                ax.set_facecolor(colors["background"])
                ax.tick_params(colors=colors["text"], labelsize=9)
                ax.grid(True, color=colors["grid"], linestyle=":", alpha=0.5)

            # Candlesticks
            for i in range(len(df)):
                o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
                color = colors["candle_up"] if c >= o else colors["candle_down"]
                ax1.plot([i, i], [l, h], color=color, linewidth=1.2)
                ax1.bar(i, c - o, bottom=o, color=color, width=0.6)

            # EMA Overlays
            ChartOverlays.add_ema(ax1, df, 20, colors["ema20"], "EMA 20")
            ChartOverlays.add_ema(ax1, df, 50, colors["ema50"], "EMA 50")
            ChartOverlays.add_ema(ax1, df, 200, colors["ema200"], "EMA 200")
            ChartOverlays.add_support_resistance(ax1, levels, colors["candle_up"], colors["candle_down"])

            ax1.set_title(f"{symbol} - Full Combined Analysis", color=colors["text"], fontsize=12, fontweight="bold")
            ax1.legend(loc="upper left", facecolor=colors["background"], edgecolor=colors["grid"], labelcolor=colors["text"], fontsize=8)

            # Volume on ax2
            ChartOverlays.add_volume(ax2, df, colors["volume_up"], colors["volume_down"])

            # MACD on ax3
            ChartOverlays.add_macd(ax3, df, colors)

            # RSI on ax4
            ChartOverlays.add_rsi(ax4, df, colors["rsi"], colors["grid"])

            # Set date tick labels on bottom plot
            step = max(1, len(df) // 10)
            ax4.set_xticks(range(0, len(df), step))
            if "datetime" in df.columns:
                date_labels = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d").tolist()
            elif "date" in df.columns:
                date_labels = df["date"].tolist()
            else:
                date_labels = [str(x) for x in df.index]

            ax4.set_xticklabels([date_labels[j] for j in range(0, len(df), step)], rotation=30, ha="right", color=colors["text"])

            fig.tight_layout()
            return fig_to_base64(fig)
        finally:
            plt.close(fig)
