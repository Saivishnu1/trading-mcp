"""
ChartPatternDetector — orchestrates all pattern sub-detectors.
"""
from __future__ import annotations

import pandas as pd

from .patterns.reversal import ReversalPatterns
from .patterns.continuation import ContinuationPatterns
from .patterns.breakout import BreakoutPatterns

# Minimum bars required per pattern family
_MIN_BARS = {
    "reversal": 10,
    "continuation": 10,
    "breakout": 10,
}


class ChartPatternDetector:

    def detect_all(self, df: pd.DataFrame, min_bars: int = 10) -> list[dict]:
        """Run all pattern detectors and return results sorted by recency (end_date desc)."""
        if df.empty or len(df) < min_bars:
            return []

        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.reset_index(drop=True)

        if len(df) < min_bars:
            return []

        results: list[dict] = []

        # Reversal patterns
        if len(df) >= _MIN_BARS["reversal"]:
            results.extend(ReversalPatterns.detect_double_top(df))
            results.extend(ReversalPatterns.detect_double_bottom(df))
            results.extend(ReversalPatterns.detect_head_and_shoulders(df))
            results.extend(ReversalPatterns.detect_inverse_head_and_shoulders(df))

        # Continuation patterns
        if len(df) >= _MIN_BARS["continuation"]:
            results.extend(ContinuationPatterns.detect_flag(df))
            results.extend(ContinuationPatterns.detect_pennant(df))
            results.extend(ContinuationPatterns.detect_rectangle(df))

        # Breakout patterns
        if len(df) >= _MIN_BARS["breakout"]:
            results.extend(BreakoutPatterns.detect_ascending_triangle(df))
            results.extend(BreakoutPatterns.detect_descending_triangle(df))
            results.extend(BreakoutPatterns.detect_symmetrical_triangle(df))
            results.extend(BreakoutPatterns.detect_wedge(df))
            results.extend(BreakoutPatterns.detect_cup_and_handle(df))
            results.extend(BreakoutPatterns.detect_rounding_bottom(df))

        # Sort by end_date descending (most recent first)
        results.sort(key=lambda x: x.get("end_date", ""), reverse=True)
        return results
