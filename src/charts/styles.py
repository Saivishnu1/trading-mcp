from __future__ import annotations

DARK_THEME = {
    "background":   "#0d1117",
    "candle_up":    "#26a69a",
    "candle_down":  "#ef5350",
    "ema20":        "#f6c90e",
    "ema50":        "#2196f3",
    "ema200":       "#ff6b6b",
    "vwap":         "#ab47bc",
    "volume_up":    "#26a69a80",
    "volume_down":  "#ef535080",
    "macd":         "#2196f3",
    "signal":       "#ff9800",
    "histogram_pos":"#26a69a",
    "histogram_neg":"#ef5350",
    "rsi":          "#f6c90e",
    "grid":         "#21262d",
    "text":         "#c9d1d9",
    "support":      "#26a69a40",
    "resistance":   "#ef535040",
}

LIGHT_THEME = {
    "background":   "#ffffff",
    "candle_up":    "#26a69a",
    "candle_down":  "#ef5350",
    "ema20":        "#fbc02d",
    "ema50":        "#1976d2",
    "ema200":       "#d32f2f",
    "vwap":         "#7b1fa2",
    "volume_up":    "#26a69a60",
    "volume_down":  "#ef535060",
    "macd":         "#1976d2",
    "signal":       "#f57c00",
    "histogram_pos":"#26a69a",
    "histogram_neg":"#ef5350",
    "rsi":          "#fbc02d",
    "grid":         "#e0e0e0",
    "text":         "#212121",
    "support":      "#26a69a30",
    "resistance":   "#ef535030",
}

def get_theme(theme_name: str) -> dict:
    if str(theme_name).lower() == "light":
        return LIGHT_THEME
    return DARK_THEME
