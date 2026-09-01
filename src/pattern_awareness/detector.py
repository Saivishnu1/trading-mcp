"""
ChartPatternDetector — orchestrates all pattern sub-detectors.
"""
from __future__ import annotations

import pandas as pd

from .patterns.breakout import BreakoutPatterns
from .patterns.continuation import ContinuationPatterns
from .patterns.reversal import ReversalPatterns

# Minimum bars required per pattern family
_MIN_BARS = {
    "reversal": 10,
    "continuation": 10,
    "breakout": 10,
}

# Pattern names whose detectors run a nested loop over all peak/trough pairs,
# which can emit multiple entries sharing the same neckline (e.g. peaks
# A-B, A-C, and B-C all resolving to a similar valley). Only the most
# recent occurrence per neckline is kept.
_DEDUPE_BY_NECKLINE = {"Double Top", "Double Bottom"}


def _dedupe_by_neckline(results: list[dict]) -> list[dict]:
    """Collapse repeated Double Top/Bottom entries that share a neckline,
    keeping only the one with the most recent end_date."""
    best: dict[tuple[str, float], dict] = {}
    passthrough: list[dict] = []

    for r in results:
        neckline = r.get("neckline")
        if r.get("pattern") in _DEDUPE_BY_NECKLINE and neckline is not None:
            key = (r["pattern"], neckline)
            existing = best.get(key)
            if existing is None or r.get("end_date", "") > existing.get("end_date", ""):
                best[key] = r
        else:
            passthrough.append(r)

    return passthrough + list(best.values())


class ChartPatternDetector:

    def detect_all(
        self,
        df: pd.DataFrame,
        min_bars: int = 10,
        max_patterns: int = 10,
    ) -> list[dict]:
        """Run all pattern detectors and return results sorted by recency (end_date desc).

        Double Top/Bottom entries sharing an identical neckline are deduped to
        their most recent occurrence, then the list is capped at `max_patterns`
        (set to 0 or a negative value for no cap).
        """
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

        # Dedupe repeated Double Top/Bottom entries, then sort by end_date
        # descending (most recent first), then cap the total count.
        results = _dedupe_by_neckline(results)
        results.sort(key=lambda x: x.get("end_date", ""), reverse=True)
        if max_patterns > 0:
            results = results[:max_patterns]
        return results
