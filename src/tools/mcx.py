from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.mcx.benchmark import check_benchmark_divergence as _check_benchmark_divergence


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def check_benchmark_divergence(
        symbol: str, mcx_change_pct: float, threshold_pct: float = 3.0,
    ) -> dict:
        """Compare an MCX commodity's move against its international benchmark.

        Only covers CRUDEOIL/CRUDEOILM (vs. WTI) and NATURALGAS/NATGASMINI
        (vs. Henry Hub) — see docs/research/mcx_scope_20260711.md for why
        other MCX commodities and MCX-side price fetching aren't supported.

        You must supply mcx_change_pct yourself (the contract's own % move
        today) — there is no working MCX price data source in this platform
        to fetch it automatically. This tool fetches the real international
        benchmark price via OilPriceAPI and flags a meaningful divergence.

        Args:
            symbol: CRUDEOIL, CRUDEOILM, NATURALGAS, or NATGASMINI.
            mcx_change_pct: The MCX contract's own % change today (you supply this).
            threshold_pct: Minimum divergence (percentage points) to raise a flag.
        """
        data = _check_benchmark_divergence(symbol, mcx_change_pct, threshold_pct)
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_INVALID if "error" in data else _meta.DQ_VALID,
            source="oilpriceapi",
            account_type="MARKET_DATA_ONLY",
            stale_threshold_seconds=900,
            from_cache=data.get("from_cache", False),
            limitations=[
                "Benchmark side only — MCX-side % change is caller-supplied, "
                "not fetched (no working MCX price source in this platform).",
            ],
        )
        return _meta.wrap(data, m)
