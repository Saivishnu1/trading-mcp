"""matplotlib/mplfinance chart palettes for get_price_chart / get_indicator_chart /
get_option_chart (src/tools/charts.py).

These values MIRROR src/ui/shared/tokens.css's Apple-inspired design tokens —
the web UI and MCP-tool-generated PNG charts previously used two unrelated
palettes (this file's old values were stock TradingView colors, #26a69a/
#ef5350, that never matched the web app's --buy/--sell at all), so a chart
returned by an MCP tool and the web UI side by side looked like two
different products.

tests/test_design_tokens_sync.py asserts the color values below stay
identical to tokens.css's declarations, so the two can't drift again
silently -- there's no build step tying Python and CSS together, so this
coupling is enforced by a test instead of by discipline.
"""
from __future__ import annotations

DARK_THEME = {
    "background":    "#000000",  # --surface-0 (dark)
    "candle_up":     "#30d158",  # --buy (dark)
    "candle_down":   "#ff453a",  # --sell (dark)
    "ema20":         "#ff9f0a",  # --status-warning (dark)
    "ema50":         "#0a84ff",  # --accent (dark)
    "ema200":        "#bf5af2",  # --status-caution (dark) -- deliberately NOT --sell,
                                  # or a 200-EMA line would read as a bearish signal
    "vwap":          "#409cff",  # --accent-strong (dark)
    "volume_up":     "#30d15880",
    "volume_down":   "#ff453a80",
    "macd":          "#0a84ff",  # --accent (dark)
    "signal":        "#ff9f0a",  # --status-warning (dark)
    "histogram_pos": "#30d158",
    "histogram_neg": "#ff453a",
    "rsi":           "#0a84ff",  # --accent (dark) -- RSI is not a warning
    "grid":          "#2c2c2e",  # --surface-2 (dark), opaque equivalent of --border-subtle
    "text":          "#98989d",  # --content-secondary (dark)
    "support":       "#30d15840",
    "resistance":    "#ff453a40",
}

LIGHT_THEME = {
    "background":    "#ffffff",  # --surface-1 (light)
    "candle_up":     "#1a7f37",  # --buy (light)
    "candle_down":   "#d70015",  # --sell (light)
    "ema20":         "#b25000",  # --status-warning (light)
    "ema50":         "#0071e3",  # --accent (light)
    "ema200":        "#8944ab",  # --status-caution (light)
    "vwap":          "#0058b0",  # --accent-strong (light)
    "volume_up":     "#1a7f3760",
    "volume_down":   "#d7001560",
    "macd":          "#0071e3",  # --accent (light)
    "signal":        "#b25000",  # --status-warning (light)
    "histogram_pos": "#1a7f37",
    "histogram_neg": "#d70015",
    "rsi":           "#0071e3",  # --accent (light) -- RSI is not a warning
    "grid":          "#d2d2d7",  # --border-subtle (light)
    "text":          "#6e6e73",  # --content-secondary (light)
    "support":       "#1a7f3730",
    "resistance":    "#d7001530",
}


def get_theme(theme_name: str) -> dict:
    if str(theme_name).lower() == "light":
        return LIGHT_THEME
    return DARK_THEME


def apply_matplotlib_defaults(theme: dict) -> None:
    """Apply product typography + chrome to matplotlib's global rcParams.

    No rcParams were set anywhere in this module before this function
    existed, so charts rendered in matplotlib's default DejaVu Sans with
    default tick/grid/spine styling, matching neither theme's chrome nor
    typography. Inter isn't matplotlib-loadable without adding a .ttf font
    file to the repo (the web UI's variable .woff2 files aren't usable by
    matplotlib) -- deliberately not doing that; this fixes colors and
    chrome only, which is most of the visual gap at none of that risk.
    """
    import matplotlib

    matplotlib.rcParams.update({
        "font.family":       ["DejaVu Sans"],
        "font.size":         9,
        "axes.titlesize":    11,
        "axes.titleweight":  "bold",
        "axes.labelcolor":   theme["text"],
        "axes.edgecolor":    theme["grid"],
        "axes.facecolor":    theme["background"],
        "figure.facecolor":  theme["background"],
        "text.color":        theme["text"],
        "xtick.color":       theme["text"],
        "ytick.color":       theme["text"],
        "grid.color":        theme["grid"],
        "grid.linewidth":    0.5,
        "axes.spines.top":   False,
        "axes.spines.right": False,
        "savefig.facecolor": theme["background"],
    })
