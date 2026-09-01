"""Enforces that src/charts/styles.py's DARK_THEME/LIGHT_THEME palettes
stay identical to src/ui/shared/tokens.css's --buy/--sell/--accent/
--surface-0/--content-secondary declarations.

There is deliberately no build step tying the web UI's CSS to the
matplotlib chart palette (see src/charts/styles.py's module docstring)
-- Python holds a verified copy of a handful of key colors instead of
parsing CSS at runtime. This test is what makes that safe: if someone
changes tokens.css without updating styles.py (or vice versa), this
fails instead of the PNG charts silently drifting from the web UI again,
which is the exact bug this coupling was introduced to fix.

Only checks the small set of colors that are shared/mapped between the
two systems (see the plan's mapping table in charts/styles.py's inline
comments) -- not every token, since several chart-only colors
(ema20/ema50/vwap/macd/etc.) are deliberately mapped to a *different*
semantic token than their CSS name suggests (e.g. chart "macd" uses
--accent, not a --macd token that doesn't exist).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

TOKENS_CSS = Path(__file__).parents[1] / "src" / "ui" / "shared" / "tokens.css"


def _extract_theme_block(css_text: str, theme: str) -> str:
    """Return the raw CSS text of the LIGHT THEME or DARK THEME selector
    block (the actual token declarations, not any prose mention of the
    phrase e.g. in the file's header comment)."""
    marker = "LIGHT THEME — default." if theme == "light" else "DARK THEME — fully realized"
    idx = css_text.index(marker)
    # Block runs from the marker to the next "}" that closes the selector
    # (first unindented "}" after the opening "{").
    open_brace = css_text.index("{", idx)
    close_brace = css_text.index("\n}", open_brace)
    return css_text[open_brace:close_brace]


def _token(block: str, name: str) -> str:
    m = re.search(rf"--{re.escape(name)}:\s*([^;]+);", block)
    assert m, f"--{name} not found in CSS block"
    return m.group(1).strip()


@pytest.fixture(scope="module")
def css_text() -> str:
    assert TOKENS_CSS.exists(), f"tokens.css not found at {TOKENS_CSS}"
    return TOKENS_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def light_block(css_text: str) -> str:
    return _extract_theme_block(css_text, "light")


@pytest.fixture(scope="module")
def dark_block(css_text: str) -> str:
    return _extract_theme_block(css_text, "dark")


class TestLightThemeSync:
    def test_buy_matches(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["candle_up"] == _token(light_block, "buy")

    def test_sell_matches(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["candle_down"] == _token(light_block, "sell")

    def test_accent_matches(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["ema50"] == _token(light_block, "accent")
        assert LIGHT_THEME["macd"] == _token(light_block, "accent")
        assert LIGHT_THEME["rsi"] == _token(light_block, "accent")

    def test_accent_strong_matches(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["vwap"] == _token(light_block, "accent-strong")

    def test_background_matches_surface_1(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["background"] == _token(light_block, "surface-1")

    def test_text_matches_content_secondary(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["text"] == _token(light_block, "content-secondary")

    def test_grid_matches_border_subtle(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["grid"] == _token(light_block, "border-subtle")

    def test_status_warning_matches(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["ema20"] == _token(light_block, "status-warning")
        assert LIGHT_THEME["signal"] == _token(light_block, "status-warning")

    def test_status_caution_matches(self, light_block):
        from src.charts.styles import LIGHT_THEME
        assert LIGHT_THEME["ema200"] == _token(light_block, "status-caution")


class TestDarkThemeSync:
    def test_buy_matches(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["candle_up"] == _token(dark_block, "buy")

    def test_sell_matches(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["candle_down"] == _token(dark_block, "sell")

    def test_accent_matches(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["ema50"] == _token(dark_block, "accent")
        assert DARK_THEME["macd"] == _token(dark_block, "accent")
        assert DARK_THEME["rsi"] == _token(dark_block, "accent")

    def test_accent_strong_matches(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["vwap"] == _token(dark_block, "accent-strong")

    def test_background_matches_surface_0(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["background"] == _token(dark_block, "surface-0")

    def test_text_matches_content_secondary(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["text"] == _token(dark_block, "content-secondary")

    def test_grid_matches_surface_2(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["grid"] == _token(dark_block, "surface-2")

    def test_status_warning_matches(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["ema20"] == _token(dark_block, "status-warning")
        assert DARK_THEME["signal"] == _token(dark_block, "status-warning")

    def test_status_caution_matches(self, dark_block):
        from src.charts.styles import DARK_THEME
        assert DARK_THEME["ema200"] == _token(dark_block, "status-caution")


class TestRsiOverlayDefaultsMatchLightTheme:
    """add_rsi's overbought/oversold default parameters are the light-theme
    sell/buy colors (callers in renderer.py always pass explicit colors, so
    these defaults only matter for direct/test callers) -- keep them
    honest rather than stale."""

    def test_defaults_match_light_theme(self, light_block):
        import inspect

        from src.charts.overlays import ChartOverlays

        sig = inspect.signature(ChartOverlays.add_rsi)
        assert sig.parameters["overbought_color"].default == _token(light_block, "sell")
        assert sig.parameters["oversold_color"].default == _token(light_block, "buy")
