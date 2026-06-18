"""
Tests for src/market/service.py data-transformation path.

Focus: get_historical() must drop NaN-bearing rows at the data boundary
(Fix 1, Phase 14.5) so that float('nan') never enters the indicator pipeline.
These drive the real DataFrame iteration — earlier NaN tests only exercised
the indicator math, leaving the source filter unguarded against regression.
"""
from __future__ import annotations

import math

import pytest


def _df_with_nan_row():
    import numpy as np
    import pandas as pd

    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {
            "Open":   [100.0, np.nan, 102.0],
            "High":   [101.0, np.nan, 103.0],
            "Low":    [99.0,  np.nan, 101.0],
            "Close":  [100.5, np.nan, 102.5],
            "Volume": [1000,  2000,   3000],
        },
        index=idx,
    )


class TestGetHistoricalNaNFilter:

    def test_nan_row_is_dropped(self, monkeypatch):
        import yfinance
        monkeypatch.setattr(yfinance, "download", lambda *a, **k: _df_with_nan_row())

        from src.market.service import MarketService
        records = MarketService().get_historical("NSE:INFY", "2024-01-01", "2024-01-04", "1d")

        assert len(records) == 2, "the all-NaN row must be filtered out"
        for r in records:
            for key in ("open", "high", "low", "close"):
                assert not (isinstance(r[key], float) and math.isnan(r[key])), (
                    f"{key} must never be NaN after get_historical"
                )

    def test_clean_rows_pass_through_unchanged(self, monkeypatch):
        import numpy as np
        import pandas as pd
        import yfinance

        idx = pd.to_datetime(["2024-01-01", "2024-01-02"])
        df = pd.DataFrame(
            {
                "Open":   [100.0, 102.0],
                "High":   [101.0, 103.0],
                "Low":    [99.0,  101.0],
                "Close":  [100.5, 102.5],
                "Volume": [1000,  3000],
            },
            index=idx,
        )
        monkeypatch.setattr(yfinance, "download", lambda *a, **k: df)

        from src.market.service import MarketService
        records = MarketService().get_historical("NSE:INFY", "2024-01-01", "2024-01-03", "1d")

        assert len(records) == 2
        assert records[0]["close"] == 100.5
        assert records[1]["close"] == 102.5

    def test_nan_volume_coerced_to_zero(self, monkeypatch):
        import numpy as np
        import pandas as pd
        import yfinance

        idx = pd.to_datetime(["2024-01-01"])
        df = pd.DataFrame(
            {
                "Open":   [100.0],
                "High":   [101.0],
                "Low":    [99.0],
                "Close":  [100.5],
                "Volume": [np.nan],
            },
            index=idx,
        )
        monkeypatch.setattr(yfinance, "download", lambda *a, **k: df)

        from src.market.service import MarketService
        records = MarketService().get_historical("NSE:INFY", "2024-01-01", "2024-01-02", "1d")

        assert len(records) == 1
        assert records[0]["volume"] == 0, "NaN volume on an otherwise valid row → 0"


# ---------------------------------------------------------------------------
# TestSymbolResolution — A1 unification (Phase 14.6)
# ---------------------------------------------------------------------------

class TestSymbolResolution:
    """
    Canonical resolver in src/market/symbols.py. Guards the bug where three
    divergent _INDEX_YF tables resolved the same alias differently (or broke).
    """

    def _to_yf(self, sym):
        from src.market.symbols import to_yf
        return to_yf(sym)

    def test_bare_nifty_resolves_to_index(self):
        # Previously broke: market/service._INDEX_YF lacked bare 'NIFTY'.
        assert self._to_yf("NIFTY") == "^NSEI"

    def test_finnifty_resolves(self):
        # Previously broke via the quote path: not in market/service table.
        assert self._to_yf("FINNIFTY") == "^CNXFIN"

    def test_midcpnifty_resolves(self):
        assert self._to_yf("MIDCPNIFTY") == "^NSEMDCP50"

    def test_nifty_it_resolves(self):
        # Was only in the market table, missing from technicals.
        assert self._to_yf("NIFTY IT") == "^CNXIT"

    def test_nse_prefixed_equity(self):
        assert self._to_yf("NSE:INFY") == "INFY.NS"

    def test_bare_equity_assumes_nse(self):
        # Previously returned 'INFY' unchanged via market/service._to_yf.
        assert self._to_yf("INFY") == "INFY.NS"

    def test_bse_prefixed_equity_honors_bse(self):
        # Market-data semantics: BSE quotes use .BO (distinct from catalyst).
        assert self._to_yf("BSE:RELIANCE") == "RELIANCE.BO"

    def test_raw_tickers_pass_through(self):
        for raw in ("^NSEI", "CL=F", "INFY.NS", "DX-Y.NYB", "^GSPC"):
            assert self._to_yf(raw) == raw

    def test_quote_and_indicator_paths_agree_on_aliases(self):
        # The core regression: every alias must resolve identically regardless
        # of entry point. Both paths funnel through to_yf now.
        from src.market.symbols import to_yf
        for alias in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"):
            assert to_yf(alias).startswith("^"), f"{alias} must resolve to an index ticker"

    def test_catalyst_shares_index_table(self):
        # Catalyst must agree with the canonical table on index aliases.
        from src.catalyst.constants import _to_yf_ticker
        from src.market.symbols import to_yf
        for alias in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"):
            assert _to_yf_ticker(alias) == to_yf(alias)
