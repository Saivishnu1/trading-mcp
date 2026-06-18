"""Phase 17 — Calibration Engine.

Measures how well the model's stated confidence predicts actual trade outcomes
using proper scoring rules (Brier score) and reliability curve analysis.

Private helpers (_calculate_brier_score, _build_reliability_curve, _calibration_gap)
are designed for reuse by Phase 18 (Recommendation Feedback Loop).
"""
from __future__ import annotations

from datetime import date, timedelta

from src.journal import db as _db
from src.journal.service import _confidence_of, _row_to_dict

# Max confidence value in this system — used to convert confidence → probability.
_CONFIDENCE_SCALE = 85.0

# Brier score rating thresholds (lower is better).
_BRIER_RATINGS = [
    (0.15, "EXCELLENT"),
    (0.20, "GOOD"),
    (0.25, "FAIR"),
]

# Confidence bucket definitions: (label, low_inclusive, high_inclusive)
_BUCKET_DEFS = [
    ("high",     75.0, 85.0),
    ("moderate", 60.0, 74.9),
    ("low",       0.0, 59.9),
]


def _bucket_name(confidence: float | None) -> str:
    if confidence is None:
        return "unknown"
    if confidence >= 75.0:
        return "high"
    if confidence >= 60.0:
        return "moderate"
    return "low"


def _calibration_gap(actual_win_rate: float, avg_predicted_probability: float) -> float:
    """calibration_gap = actual_win_rate − avg_predicted_probability.

    Positive → underconfident (model undersells its own accuracy).
    Negative → overconfident (model oversells its own accuracy).
    """
    return round(actual_win_rate - avg_predicted_probability, 4)


def _calculate_brier_score(trades: list[dict]) -> dict:
    """Brier score = mean((predicted_prob − actual_outcome)²).

    Only trades with a recorded confidence in analysis_snapshot are scored.
    Returns {"brier_score": float|None, "calibration_rating": str|None, "scored_count": int}.
    """
    errors: list[float] = []
    for t in trades:
        conf = _confidence_of(t)
        if conf is None:
            continue
        predicted = conf / _CONFIDENCE_SCALE
        outcome = 1.0 if (t.get("pnl") or 0) > 0 else 0.0
        errors.append((predicted - outcome) ** 2)

    if not errors:
        return {"brier_score": None, "calibration_rating": None, "scored_count": 0}

    brier = round(sum(errors) / len(errors), 4)
    rating = "POOR"
    for threshold, label in _BRIER_RATINGS:
        if brier <= threshold:
            rating = label
            break

    return {"brier_score": brier, "calibration_rating": rating, "scored_count": len(errors)}


def _build_reliability_curve(trades: list[dict], min_sample: int = 5) -> list[dict]:
    """Per-bucket predicted probability vs actual win rate.

    Returns one entry per non-empty bucket ordered high→moderate→low→unknown.
    Buckets below min_sample are flagged low_sample.
    """
    buckets: dict[str, list[dict]] = {
        "high": [], "moderate": [], "low": [], "unknown": []
    }

    for t in trades:
        conf = _confidence_of(t)
        bucket = _bucket_name(conf)
        predicted = (conf / _CONFIDENCE_SCALE) if conf is not None else None
        outcome = 1.0 if (t.get("pnl") or 0) > 0 else 0.0
        buckets[bucket].append({"predicted": predicted, "outcome": outcome})

    result: list[dict] = []
    for bucket in ("high", "moderate", "low", "unknown"):
        rows = buckets[bucket]
        if not rows:
            continue

        count = len(rows)
        with_conf = [r for r in rows if r["predicted"] is not None]
        avg_predicted = (
            round(sum(r["predicted"] for r in with_conf) / len(with_conf), 4)
            if with_conf else None
        )
        actual_win_rate = round(sum(r["outcome"] for r in rows) / count, 4)
        gap = (
            _calibration_gap(actual_win_rate, avg_predicted)
            if avg_predicted is not None else None
        )

        result.append({
            "bucket": bucket,
            "trade_count": count,
            "avg_predicted_probability": avg_predicted,
            "actual_win_rate": actual_win_rate,
            "calibration_gap": gap,
            "low_sample": count < min_sample,
        })

    return result


def _build_overconfidence_analysis(curve: list[dict]) -> dict | None:
    """Aggregate directional bias across non-low-sample buckets.

    overconfidence_score  = mean(|negative calibration gaps|)
    underconfidence_score = mean(positive calibration gaps)
    """
    gaps = [
        b["calibration_gap"]
        for b in curve
        if b.get("calibration_gap") is not None and not b["low_sample"]
    ]
    if not gaps:
        return None

    neg_abs = [abs(g) for g in gaps if g < 0]
    pos = [g for g in gaps if g > 0]

    over = round(sum(neg_abs) / len(neg_abs), 4) if neg_abs else 0.0
    under = round(sum(pos) / len(pos), 4) if pos else 0.0

    if over > under:
        bias = "OVERCONFIDENT"
    elif under > over:
        bias = "UNDERCONFIDENT"
    else:
        bias = "BALANCED"

    return {
        "overconfidence_score": over,
        "underconfidence_score": under,
        "dominant_bias": bias,
    }


def get_calibration_report(
    symbol: str | None = None,
    days: int = 365,
    min_sample: int = 5,
) -> dict:
    """Full calibration report over CLOSED trades.

    Returns Brier score, reliability curve, and overconfidence analysis.
    Only trades with analysis_snapshot.confidence contribute to the Brier score.
    """
    try:
        cutoff = (date.today() - timedelta(days=max(days, 0))).isoformat()
        conditions = ["status = 'CLOSED'", "entry_date >= ?"]
        params: list = [cutoff]
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper().strip())
        where = " AND ".join(conditions)

        conn = _db._get_connection()
        rows = conn.execute(
            f"SELECT * FROM trades WHERE {where} ORDER BY entry_date DESC",
            params,
        ).fetchall()
        closed = [_row_to_dict(r) for r in rows]

        if not closed:
            return {
                "brier_score": None,
                "calibration_rating": None,
                "brier_scored_trades": 0,
                "reliability_curve": [],
                "overconfidence_analysis": None,
                "trade_count": 0,
                "filters": {
                    "symbol": symbol.upper().strip() if symbol else None,
                    "days": days,
                    "min_sample": min_sample,
                },
                "notes": ["No closed trades found in the specified period."],
            }

        brier = _calculate_brier_score(closed)
        curve = _build_reliability_curve(closed, min_sample=min_sample)
        overconf = _build_overconfidence_analysis(curve)
        notes = _calibration_notes(closed, brier, curve, min_sample)

        return {
            "brier_score": brier["brier_score"],
            "calibration_rating": brier["calibration_rating"],
            "brier_scored_trades": brier["scored_count"],
            "reliability_curve": curve,
            "overconfidence_analysis": overconf,
            "trade_count": len(closed),
            "filters": {
                "symbol": symbol.upper().strip() if symbol else None,
                "days": days,
                "min_sample": min_sample,
            },
            "notes": notes,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _calibration_notes(
    closed: list[dict],
    brier: dict,
    curve: list[dict],
    min_sample: int,
) -> list[str]:
    notes: list[str] = []

    if brier["brier_score"] is None:
        notes.append(
            "No trades have confidence scores — log trades with analysis_snapshot.confidence to enable Brier scoring."
        )
        return notes

    if brier["calibration_rating"] in ("FAIR", "POOR"):
        notes.append(
            f"Calibration is {brier['calibration_rating']} (Brier={brier['brier_score']}) — "
            "confidence values do not reliably predict outcomes."
        )

    unknown = next((b for b in curve if b["bucket"] == "unknown"), None)
    if unknown:
        pct = round(unknown["trade_count"] / len(closed) * 100)
        if pct > 0:
            notes.append(
                f"{pct}% of trades have no confidence score (logged without analysis_snapshot.confidence)."
            )

    low_sample_buckets = [b["bucket"] for b in curve if b["low_sample"] and b["bucket"] != "unknown"]
    if low_sample_buckets:
        notes.append(
            f"Buckets below {min_sample} trades (flagged low_sample): {', '.join(low_sample_buckets)}. "
            "Win rates in these buckets are noise."
        )

    if len(closed) < min_sample:
        notes.append(
            f"Only {len(closed)} closed trades total — calibration results are low-confidence. "
            "Log more trades for meaningful analysis."
        )

    return notes
