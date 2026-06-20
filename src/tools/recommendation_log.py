"""
Phase 22 — Recommendation logging and consolidated market context tools.

Four new MCP tools:
  log_recommendation              — record a Claude recommendation for later review
  update_recommendation_outcome   — fill in outcome/postmortem during weekly review
  get_recommendation_stats        — counts, readiness, partition status
  get_full_market_context         — single call replacing 6 separate data calls

Auto-capture detection:
  detect_recommendation           — flag when a response contains a recommendation trigger
"""
from mcp.server.fastmcp import FastMCP

from src.recommendation_log import service as _svc
from src.recommendation_log.capture import detect_recommendation as _detect
from src import meta as _meta

# Shared market context helpers (imported lazily so server startup stays fast)
def _market_context_data(symbol: str, include_options: bool) -> dict:
    from src.market import get_market
    from src.analysis import regime as _regime
    from src.intelligence.vix import get_india_vix
    from src.intelligence.events import get_upcoming_events

    ctx: dict = {}

    market = get_market()

    # Live quote
    try:
        ctx["quote"] = market.get_quote(symbol)
    except Exception as exc:
        ctx["quote"] = {"error": str(exc)}

    # OHLCV (today)
    try:
        ctx["ohlc"] = market.get_ohlc(symbol)
    except Exception as exc:
        ctx["ohlc"] = {"error": str(exc)}

    # Technical indicators (150-day strategy-grade lookback)
    try:
        from datetime import date, timedelta
        from src.technical import indicators as _ind
        today = date.today()
        start = (today - timedelta(days=150)).isoformat()
        end = (today + timedelta(days=1)).isoformat()
        candles = market.get_historical(symbol, start, end, "1d") or []
        if candles:
            closes = [c["close"] for c in candles]
            highs = [c["high"] for c in candles]
            lows = [c["low"] for c in candles]
            ctx["technicals"] = {
                "candles_used": len(closes),
                "last_close": round(closes[-1], 4),
                "rsi_14": _ind.rsi(closes, 14),
                "ema_20": _ind.ema(closes, 20),
                "ema_50": _ind.ema(closes, 50),
                "macd": _ind.macd(closes),
                "adx_14": _ind.adx(highs, lows, closes, 14),
                "atr_14": _ind.atr(highs, lows, closes, 14),
            }
        else:
            ctx["technicals"] = {"error": "no candle data"}
    except Exception as exc:
        ctx["technicals"] = {"error": str(exc)}

    # Market regime (uses cached technicals internally)
    try:
        ctx["regime"] = _regime.detect_market_regime(symbol)
    except Exception as exc:
        ctx["regime"] = {"error": str(exc)}

    # VIX
    try:
        ctx["vix"] = get_india_vix()
    except Exception as exc:
        ctx["vix"] = {"error": str(exc)}

    # Upcoming events (next 14 days)
    try:
        ctx["upcoming_events"] = get_upcoming_events(days_ahead=14)
    except Exception as exc:
        ctx["upcoming_events"] = {"error": str(exc)}

    # OI support/resistance (options — optional, only for index/F&O symbols)
    if include_options:
        try:
            from src.options import get_options_service
            from src.options.analytics import identify_support_resistance_from_oi
            svc = get_options_service()
            chain = svc.get_option_chain(symbol)
            spot = chain.get("records", {}).get("underlyingValue", 0)
            ctx["oi_levels"] = identify_support_resistance_from_oi(chain, spot)
        except Exception as exc:
            ctx["oi_levels"] = {"error": str(exc)}

    return ctx


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def log_recommendation(
        symbol: str | None,
        user_question: str,
        market_snapshot: dict | None,
        mcp_facts: dict | None,
        claude_reasoning_summary: str,
        recommendation_type: str,
        uncertainty_level: str,
        baseline_no_mcp: bool = False,
    ) -> dict:
        """Log a Claude recommendation for later decision-quality review.

        Call this AFTER giving a recommendation — not before.
        All outcome fields are NULL at creation; fill them during weekly review.

        Args:
            symbol: NSE symbol (e.g. 'INFY') or None for macro recommendations.
            user_question: What the user asked, verbatim or summarised.
            market_snapshot: Dict of current market data used (price, regime, VIX etc.).
            mcp_facts: Dict of raw MCP tool outputs that informed the recommendation.
            claude_reasoning_summary: 2-3 sentence summary of why this recommendation
                was given. Focus on what data drove the conclusion.
            recommendation_type: One of ENTER|EXIT|HOLD|AVOID|OBSERVE|STAY_CASH|
                SIZE_REDUCE|TAKE_PROFIT|TIGHTEN_STOP|NONE
            uncertainty_level: LOW|MEDIUM|HIGH — how certain was the recommendation.
            baseline_no_mcp: Set True when logging an unassisted decision (no MCP
                consulted). Used to build the control group for the 2x2 analysis.

        Returns record with id (format: REC-xxxxxxxx). Store it for weekly review.
        """
        data = _svc.log_recommendation(
            symbol=symbol,
            user_question=user_question,
            market_snapshot=market_snapshot,
            mcp_facts=mcp_facts,
            claude_reasoning_summary=claude_reasoning_summary,
            recommendation_type=recommendation_type,
            uncertainty_level=uncertainty_level,
            baseline_no_mcp=baseline_no_mcp,
        )
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_INVALID if "error" in data else _meta.DQ_VALID,
            source="internal_journal",
            account_type="PAPER_JOURNAL",
            bootstrap_period=True,
            warning=(
                "Record flagged bootstrap_period=1 and bias_contaminated=1. "
                "Will not count toward clean analysis until manually cleared."
            ),
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def update_recommendation_outcome(
        id: str,
        user_action: str | None = None,
        mcp_changed_decision: bool | None = None,
        would_have_acted_without_mcp: bool | None = None,
        decision_quality: dict | None = None,
        outcome_1d: float | None = None,
        outcome_5d: float | None = None,
        outcome_20d: float | None = None,
        postmortem_helpful: bool | None = None,
        postmortem_why: str | None = None,
        postmortem_review_questions: dict | None = None,
    ) -> dict:
        """Fill in outcome and postmortem fields during the weekly blind review.

        Call AFTER reading market_snapshot + mcp_facts and answering the 6
        postmortem questions BEFORE reading claude_reasoning_summary.

        decision_quality dict fields:
          process_followed        — bool: did you follow your trading rules?
          risk_defined            — bool: was max loss defined before entry?
          position_sized_correctly — bool: was size within your risk limit?
          exit_plan_defined       — bool: was exit plan stated before entry?

        postmortem_review_questions dict fields:
          facts_accurate                  — bool
          uncertainty_communicated        — bool
          risk_defined                    — bool
          disciplined_behavior_encouraged — bool
          changed_decision                — bool
          market_outcome                  — str description

        Args:
            id: Record id returned by log_recommendation (format: REC-xxxxxxxx).
        """
        data = _svc.update_recommendation_outcome(
            id=id,
            user_action=user_action,
            mcp_changed_decision=mcp_changed_decision,
            would_have_acted_without_mcp=would_have_acted_without_mcp,
            decision_quality=decision_quality,
            outcome_1d=outcome_1d,
            outcome_5d=outcome_5d,
            outcome_20d=outcome_20d,
            postmortem_helpful=postmortem_helpful,
            postmortem_why=postmortem_why,
            postmortem_review_questions=postmortem_review_questions,
        )
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_INVALID if "error" in data else _meta.DQ_VALID,
            source="internal_journal",
            account_type="PAPER_JOURNAL",
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def get_recommendation_stats() -> dict:
        """Return partition counts and analysis readiness for the recommendation log.

        Partitions:
          bootstrap_records  — first 50 records; high observer-effect bias
          baseline_records   — unassisted decisions (no MCP); control group
          clean_records      — post-bootstrap, post-bias; used for analysis

        analysis_ready is True only when:
          clean_records >= 100 AND baseline_records >= 10

        Stats are null until analysis_ready — drawing conclusions before 100 clean
        records is the primary risk to avoid.
        """
        data = _svc.get_recommendation_stats(clean_only=True)
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="internal_journal",
            account_type="PAPER_JOURNAL",
            warning=(
                None if data.get("analysis_ready")
                else (
                    f"NOT analysis-ready. "
                    f"{data.get('records_until_clean_analysis', '?')} more clean records needed "
                    f"(currently {data.get('clean_records', 0)}/{data.get('thresholds', {}).get('min_clean_records_for_analysis', 100)}). "
                    "Do not draw conclusions from bootstrap data."
                )
            ),
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def get_full_market_context(
        symbol: str,
        include_options: bool = False,
    ) -> dict:
        """Consolidated single-call market context — replaces 6 separate tool calls.

        Reduces context-window pressure by bundling: live quote, OHLCV,
        technical indicators (RSI/EMA/MACD/ADX/ATR), market regime descriptor,
        India VIX, and upcoming events into one response.

        Use this at the START of a session to build the market_snapshot dict
        before calling log_recommendation.

        Args:
            symbol: NSE symbol, index name, or yfinance ticker.
                    Examples: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', 'INFY.NS'
            include_options: Set True for NIFTY/BANKNIFTY to include OI
                support/resistance levels. Adds 1-2 seconds for chain fetch.

        Returns:
            { quote, ohlc, technicals, regime, vix, upcoming_events }
            Each sub-dict has its own data and NaN detection.
            include_options=True also returns oi_levels.
        """
        data = _market_context_data(symbol, include_options)

        # Aggregate data quality from sub-components
        has_error = any(
            isinstance(v, dict) and "error" in v for v in data.values()
        )
        dq = _meta.DQ_PARTIAL if has_error else _meta.DQ_VALID

        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=dq,
            source="yfinance",
            account_type="MARKET_DATA_ONLY",
            warning=(
                None if _meta.is_market_hours()
                else "Outside NSE session. Quotes reflect last traded price."
            ),
            limitations=[
                "Technicals from EOD-adjusted yfinance candles.",
                "Regime is INTERPRETATION — not a directional prediction.",
            ],
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def detect_recommendation(text: str) -> dict:
        """Detect whether a piece of text contains a recommendation that should be logged.

        Scans for Phase 22 trigger words (enter, buy, exit, hold, avoid, etc.).
        Returns detected triggers and whether logging is recommended.

        Does NOT auto-log. User must call log_recommendation explicitly.

        Args:
            text: Claude's response text to scan.
        """
        result = _detect(text)
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_COMPUTED,
            data_quality=_meta.DQ_VALID,
            source="internal_journal",
            account_type="PAPER_JOURNAL",
        )
        return _meta.wrap(result, m)
