"""Pure (Telegram-free) parser for /buy and /sell command arguments.

Kept separate from handlers.py so it is unit-testable without a Telegram
Update/Context. Produces a partially-populated OrderRequest (security_id is
resolved later, asynchronously, in the handler) or an error string.

Grammar:
    /buy  SYMBOL QTY [MARKET | LIMIT <price>] [CNC | INTRADAY | MARGIN] [NSE | BSE]
    /sell SYMBOL QTY [MARKET | LIMIT <price>] [CNC | INTRADAY | MARGIN] [NSE | BSE]

Examples:
    /buy RELIANCE 1                      → MARKET, INTRADAY, NSE
    /buy RELIANCE 1 LIMIT 2870           → LIMIT @ 2870
    /sell TCS 5 LIMIT 3900 CNC BSE
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.brokers.models import OrderRequest

# Option symbols: a strike (digits, optional decimal) immediately before CE/PE,
# e.g. NIFTY24200CE, BANKNIFTY52000PE, NIFTY24500.5CE. Futures end in FUT.
_OPTION_RE = re.compile(r"\d(\.\d+)?(CE|PE)$")


def _is_derivative_symbol(symbol: str) -> bool:
    return bool(_OPTION_RE.search(symbol)) or symbol.endswith("FUT")

_ORDER_TYPES = {"MARKET", "LIMIT"}
_PRODUCTS = {"CNC", "INTRADAY", "MARGIN"}
_EXCHANGES = {"NSE", "BSE"}


@dataclass
class ParseError:
    message: str


def parse_order_args(args: list[str], side: str) -> OrderRequest | ParseError:
    """Parse raw command tokens into an OrderRequest.

    Args:
        args: context.args from python-telegram-bot (already whitespace-split).
        side: "BUY" or "SELL".

    Returns the OrderRequest with security_id left blank (resolved later), or a
    ParseError with a human-readable message.
    """
    usage = (
        f"Usage: /{side.lower()} SYMBOL QTY [MARKET | LIMIT <price>] "
        f"[CNC | INTRADAY | MARGIN] [NSE | BSE]\n"
        f"e.g. /{side.lower()} RELIANCE 1 LIMIT 2870"
    )
    if len(args) < 2:
        return ParseError(usage)

    symbol = args[0].upper()

    try:
        qty = int(args[1])
    except ValueError:
        return ParseError(f"Quantity must be a whole number, got '{args[1]}'.\n\n{usage}")
    if qty <= 0:
        return ParseError("Quantity must be positive.")

    order_type = "MARKET"
    limit_price = 0.0
    product = "INTRADAY"
    exchange = "NSE"

    rest = [a.upper() for a in args[2:]]
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in _ORDER_TYPES:
            order_type = tok
            if tok == "LIMIT":
                if i + 1 >= len(rest):
                    return ParseError("LIMIT requires a price, e.g. LIMIT 2870.")
                try:
                    limit_price = float(rest[i + 1])
                except ValueError:
                    return ParseError(f"Invalid LIMIT price '{rest[i + 1]}'.")
                if limit_price <= 0:
                    return ParseError("LIMIT price must be positive.")
                i += 2
                continue
        elif tok in _PRODUCTS:
            product = tok
        elif tok in _EXCHANGES:
            exchange = tok
        else:
            return ParseError(f"Unrecognized token '{tok}'.\n\n{usage}")
        i += 1

    # Options symbols end in a strike price immediately followed by CE/PE
    # (e.g. NIFTY24200CE) — require a digit before the suffix so equities that
    # merely end in "CE"/"PE" (RELIANCE, ONGC-style names) stay EQUITY. Futures
    # end in FUT. Everything else is EQUITY.
    segment = "DERIVATIVE" if _is_derivative_symbol(symbol) else "EQUITY"

    return OrderRequest(
        security_id="",  # resolved async in the handler via resolve_symbol()
        exchange=exchange,
        segment=segment,
        transaction_type=side.upper(),
        quantity=qty,
        order_type=order_type,
        product=product,
        limit_price=limit_price,
        symbol=symbol,
    )


def format_order_summary(req: OrderRequest) -> str:
    """Human-readable confirm summary shown before firing."""
    price = "at market (auto-LIMIT @ live price)" if req.order_type == "MARKET" \
        else f"LIMIT @ ₹{req.limit_price:g}"
    emoji = "🟢" if req.transaction_type == "BUY" else "🔴"
    return (
        f"{emoji} *Confirm order*\n\n"
        f"• {req.transaction_type} *{req.symbol}*\n"
        f"• Qty: *{req.quantity}*\n"
        f"• {price}\n"
        f"• Product: {req.product}  |  {req.exchange} {req.segment}\n\n"
        f"Place this order?"
    )
