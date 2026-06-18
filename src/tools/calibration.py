from mcp.server.fastmcp import FastMCP

from src.calibration.service import get_calibration_report as _get_calibration_report


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calibration_report(
        symbol: str = "",
        days: int = 365,
        min_sample: int = 5,
    ) -> dict:
        """Calibration quality of the model's confidence scores against actual trade outcomes.

        Returns a Brier score (lower is better: ≤0.15 excellent, ≤0.20 good, ≤0.25 fair),
        a per-bucket reliability curve (avg predicted probability vs actual win rate), and
        an overconfidence analysis showing whether the model systematically over- or
        under-estimates its accuracy. Only closed trades with a recorded confidence value
        in analysis_snapshot contribute to the Brier score.
        """
        return _get_calibration_report(
            symbol=symbol or None,
            days=days,
            min_sample=min_sample,
        )
