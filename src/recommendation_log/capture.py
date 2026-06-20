"""
Phase 22 Commit 4 — Auto-capture trigger detection.

Scans Claude response text for recommendation trigger words.
Does NOT auto-log — only flags. User must call log_recommendation explicitly.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Trigger word map
# ---------------------------------------------------------------------------

_TRIGGERS: dict[str, list[str]] = {
    "ENTER": [
        "enter", "buy", "go long", "initiate a long", "start a position",
        "take a position", "open a trade",
    ],
    "EXIT": [
        "exit", "sell", "close the position", "close your position",
        "square off", "book the position", "get out",
    ],
    "HOLD": [
        "hold", "stay in", "don't exit", "keep the position", "maintain the position",
    ],
    "AVOID": [
        "avoid", "skip", "don't enter", "stay in cash", "don't trade",
        "sit out", "pass on this", "not worth entering",
    ],
    "STAY_CASH": [
        "stay in cash", "wait in cash", "preserve capital", "no trade today",
    ],
    "SIZE_REDUCE": [
        "reduce", "reduce size", "trim", "partial exit", "book partial",
    ],
    "TAKE_PROFIT": [
        "take profit", "book profit", "lock in gains", "trail stop",
    ],
    "TIGHTEN_STOP": [
        "tighten stop", "move stop", "trail stop", "raise stop",
    ],
    "OBSERVE": [
        "wait", "too risky", "not yet", "watch and wait", "monitor",
        "let it develop", "no action yet",
    ],
}

# Compiled pattern: (pattern, recommendation_type)
_COMPILED: list[tuple[re.Pattern, str]] = []
for _rtype, _phrases in _TRIGGERS.items():
    for _phrase in _phrases:
        _COMPILED.append((
            re.compile(r"\b" + re.escape(_phrase) + r"\b", re.IGNORECASE),
            _rtype,
        ))


def detect_recommendation(text: str) -> dict:
    """Scan text for recommendation triggers.

    Returns:
        {
            "detected": bool,
            "triggers_found": [{"phrase": str, "recommendation_type": str}],
            "dominant_type": str | None,   # highest-frequency type
            "capture_mode": "auto",
            "requires_logging": bool,
            "note": str
        }
    """
    if not text or not text.strip():
        return {
            "detected": False,
            "triggers_found": [],
            "dominant_type": None,
            "capture_mode": "auto",
            "requires_logging": False,
            "note": "No text provided.",
        }

    found: list[dict] = []
    seen_phrases: set[str] = set()

    for pattern, rtype in _COMPILED:
        for match in pattern.finditer(text):
            phrase = match.group(0).lower()
            if phrase not in seen_phrases:
                seen_phrases.add(phrase)
                found.append({"phrase": phrase, "recommendation_type": rtype})

    # Dominant type = most frequently triggered type
    if found:
        type_counts: dict[str, int] = {}
        for item in found:
            t = item["recommendation_type"]
            type_counts[t] = type_counts.get(t, 0) + 1
        dominant = max(type_counts, key=lambda k: type_counts[k])
    else:
        dominant = None

    detected = len(found) > 0

    return {
        "detected": detected,
        "triggers_found": found,
        "dominant_type": dominant,
        "capture_mode": "auto",
        "requires_logging": detected,
        "note": (
            "Recommendation detected. Call log_recommendation() to capture it."
            if detected
            else "No recommendation triggers found in this text."
        ),
    }
