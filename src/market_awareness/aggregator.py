from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pandas as pd

from src.candle_awareness.classifier import build_context, classify_strength
from src.candle_awareness.patterns import PatternDetector
from src.chart_awareness import indicators as _ind
from src.chart_awareness.data_fetcher import fetch_candles
from src.chart_awareness.engine import ChartEngine
from src.chart_awareness.levels import detect_levels
from src.intelligence.global_pulse import get_global_pulse
from src.intelligence.vix import get_india_vix
from src.market.calendar import get_market_calendar
from src.options_awareness.engine import OptionsAwarenessEngine
from src.pattern_awareness.detector import ChartPatternDetector


class MarketAggregator:

    async def collect(
        self,
        symbol: str,
        interval: str = "day",
        days: int = 90,
        include_options: bool = True,
        include_global: bool = True,
        include_patterns: bool = True,
    ) -> dict:
        tasks = []
        task_names = []

        # 1. Chart engine analysis
        tasks.append(self._get_chart(symbol, interval, days))
        task_names.append("chart")

        # 2 & 3. Patterns (Candlestick + Chart patterns)
        if include_patterns:
            tasks.append(self._get_candles(symbol, interval, days=30))
            task_names.append("candlestick")
            tasks.append(self._get_chart_patterns(symbol, interval, days=180))
            task_names.append("chart_patterns")

        # 4. Options
        if include_options:
            tasks.append(self._get_options(symbol))
            task_names.append("options")

        # 5 & 6. Global pulse + VIX
        if include_global:
            tasks.append(self._get_global())
            task_names.append("global")
            tasks.append(self._get_vix())
            task_names.append("vix")

        # 7. Calendar
        tasks.append(self._get_calendar())
        task_names.append("calendar")

        # Execute concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data = {}
        missing_data = []

        for name, res in zip(task_names, results):
            if isinstance(res, Exception) or (isinstance(res, dict) and "error" in res):
                missing_data.append(name)
                # Ensure we store an empty structure rather than None or Exception
                data[name] = {"error": str(res)} if isinstance(res, Exception) else res
            else:
                data[name] = res

        data["missing_data"] = missing_data
        return data

    async def _get_chart(self, symbol: str, interval: str, days: int) -> dict:
        engine = ChartEngine()
        return await engine.analyze(symbol, interval, days)

    async def _get_candles(self, symbol: str, interval: str, days: int) -> dict:
        today = date.today()
        fetch_days = max(days + 30, 60)
        from_date = (today - timedelta(days=fetch_days)).isoformat()
        to_date = (today + timedelta(days=1)).isoformat()

        candles, data_source = await fetch_candles(symbol, interval, from_date, to_date)
        if not candles:
            return {
                "patterns": [],
                "summary": {"dominant_bias": "neutral"},
                "observations": [],
            }

        df = pd.DataFrame(candles)
        df.columns = [c.lower() for c in df.columns]
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)

        cutoff = (today - timedelta(days=days)).isoformat()
        df_full = df.copy()
        df_window = df[df["datetime"].astype(str) >= cutoff].copy()
        if df_window.empty:
            df_window = df.copy()

        indics = _ind.compute(candles)
        adx = indics.get("adx")
        rsi = indics.get("rsi")
        levels = detect_levels(df_window.to_dict("records"))

        detector = PatternDetector()
        avg_vol_df = df_full["volume"].replace(0, float("nan")).mean() or 1.0
        patterns_raw = detector.detect_all(df_window.reset_index(drop=True))

        patterns_out = []
        for p in patterns_raw:
            p.volume_ratio = round(p.volume / avg_vol_df, 2) if avg_vol_df > 0 else 0.0
            p.strength = classify_strength(p, adx, rsi, levels)
            p.context = build_context(p, levels)
            patterns_out.append(p)

        _STRENGTH_RANK = {"weak": 0, "moderate": 1, "strong": 2}
        patterns_out.sort(key=lambda x: (x.location, -_STRENGTH_RANK.get(x.strength, 0)))

        def _location_label(loc: int) -> str:
            if loc == 0:
                return "latest bar"
            if loc == 1:
                return "1 bar ago"
            return f"{loc} bars ago"

        serialised = [
            {
                "name": p.name,
                "type": p.pattern_type,
                "strength": p.strength,
                "location": _location_label(p.location),
                "bar_date": p.bar_date,
                "open": round(p.open, 2),
                "high": round(p.high, 2),
                "low": round(p.low, 2),
                "close": round(p.close, 2),
                "volume_ratio": p.volume_ratio,
                "context": p.context,
            }
            for p in patterns_out
        ]

        bullish = sum(1 for p in patterns_out if p.pattern_type == "bullish")
        bearish = sum(1 for p in patterns_out if p.pattern_type == "bearish")
        neutral = sum(1 for p in patterns_out if p.pattern_type == "neutral")
        total = len(patterns_out)

        if total == 0:
            bias = "neutral"
        elif bullish > bearish and bullish > neutral:
            bias = "bullish"
        elif bearish > bullish and bearish > neutral:
            bias = "bearish"
        elif bullish == bearish and bullish > 0:
            bias = "mixed"
        else:
            bias = "neutral"

        obs = []
        seen = set()
        for p in patterns_out:
            key = f"{p.name}|{p.bar_date}"
            if key in seen:
                continue
            seen.add(key)
            loc = "latest bar" if p.location == 0 else f"{p.location} bar{'s' if p.location > 1 else ''} ago"
            ctx = f" — {p.context}" if p.context else ""
            vol_note = ""
            if p.volume_ratio >= 1.5:
                vol_note = " with high volume"
            elif p.volume_ratio < 0.8:
                vol_note = " on low volume"
            obs.append(f"{p.name} on {loc}{vol_note}{ctx}")

        return {
            "patterns": serialised,
            "summary": {
                "total_patterns": total,
                "bullish_count": bullish,
                "bearish_count": bearish,
                "neutral_count": neutral,
                "dominant_bias": bias,
            },
            "observations": obs,
        }

    async def _get_chart_patterns(self, symbol: str, interval: str, days: int) -> dict:
        today = date.today()
        from_date = (today - timedelta(days=days)).isoformat()
        to_date = (today + timedelta(days=1)).isoformat()

        candles, data_source = await fetch_candles(symbol, interval, from_date, to_date)
        if not candles:
            return {
                "patterns": [],
                "summary": {"dominant_bias": "neutral"},
                "observations": [],
            }

        df = pd.DataFrame(candles)
        df.columns = [c.lower() for c in df.columns]
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)

        detector = ChartPatternDetector()
        patterns = detector.detect_all(df, min_bars=20)

        bullish = sum(1 for p in patterns if p["direction"] == "bullish")
        bearish = sum(1 for p in patterns if p["direction"] == "bearish")
        neutral = sum(1 for p in patterns if p["direction"] == "neutral")
        total = len(patterns)

        if total == 0:
            bias = "neutral"
        elif bullish > bearish and bullish > neutral:
            bias = "bullish"
        elif bearish > bullish and bearish > neutral:
            bias = "bearish"
        elif bullish == bearish and bullish > 0:
            bias = "mixed"
        else:
            bias = "neutral"

        obs = []
        for p in patterns:
            name = p["pattern"]
            status = p["status"]
            neckline = p.get("neckline")
            support = p.get("support")
            resistance = p.get("resistance")
            end_date = p.get("end_date", "")

            parts = [f"{name} ({status})"]
            if neckline and neckline > 0:
                parts.append(f"neckline at {neckline:,.2f}")
            if support and support > 0 and support != neckline:
                parts.append(f"support at {support:,.2f}")
            if resistance and resistance > 0 and resistance != neckline:
                parts.append(f"resistance at {resistance:,.2f}")
            if end_date:
                parts.append(f"as of {end_date}")
            obs.append(" — ".join(parts))

        return {
            "patterns": patterns,
            "summary": {
                "total_patterns": total,
                "bullish_count": bullish,
                "bearish_count": bearish,
                "neutral_count": neutral,
                "dominant_bias": bias,
            },
            "observations": obs,
        }

    async def _get_options(self, symbol: str) -> dict:
        # OptionsAwarenessEngine().analyze is sync, run in thread executor if needed
        # but since it's fast enough we can run it directly or in run_in_executor.
        loop = asyncio.get_running_loop()
        engine = OptionsAwarenessEngine()
        return await loop.run_in_executor(None, engine.analyze, symbol)

    async def _get_global(self) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, get_global_pulse)

    async def _get_vix(self) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, get_india_vix)

    async def _get_calendar(self) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, get_market_calendar)
