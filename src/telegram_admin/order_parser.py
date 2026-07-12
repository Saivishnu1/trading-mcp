"""Pure (Telegram-free) parser for /buy and /sell command arguments.

Kept separate from handlers.py so it is unit-testable without a Telegram
Update/Context. Produces a partially-populated OrderRequest (security_id is
resolved later, asynchronously, in the handler) or an error string.

Grammar:
    /buy  SYMBOL QTY [MARKET | LIMIT <price>] [CNC | INTRADAY | MARGIN] [NSE | BSE]
          [SL <trigger> [<limit>]] [TARGET <trigger> [<limit>]] [TRAIL <points>]
    /sell SYMBOL QTY [MARKET | LIMIT <price>] [CNC | INTRADAY | MARGIN] [NSE | BSE]
          [SL <trigger> [<limit>]] [TARGET <trigger> [<limit>]] [TRAIL <points>]

SL/TARGET route the order through INDstocks' Smart Order (GTT-style) endpoint
instead of the plain order endpoint (see OrderRequest.is_smart_order). If only
the trigger price is given, the limit price defaults to the trigger (a
market-ish stop). TRAIL has no native INDstocks field — it is honored
client-side by src/execution/trailing_sl.py, which ratchets SL via
/smart/order/modify as the live price moves favorably; TRAIL requires SL to
also be given (it needs a starting stop to trail from).

Examples:
    /buy RELIANCE 1                                → MARKET, INTRADAY, NSE
    /buy RELIANCE 1 LIMIT 2870                      → LIMIT @ 2870
    /sell TCS 5 LIMIT 3900 CNC BSE
    /buy RELIANCE 1 SL 2820 TARGET 2950             → entry + SL leg + target leg
    /buy RELIANCE 1 SL 2820 TARGET 2950 TRAIL 5     → same, SL trails by 5 points
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.brokers.models import OrderRequest

# Option symbols: a strike (digits, optional decimal) before CE/PE, either
# immediately adjacent (Telegram's compact typed format: NIFTY24200CE,
# BANKNIFTY52000PE, NIFTY24500.5CE) or hyphen-separated (INDstocks' own
# TRADING_SYMBOL for index options: NIFTY-JUL2026-24250-CE — confirmed bug,
# 2026-07-12: the web dropdown's picked segment is now trusted directly
# instead of relying on this regex, but a free-typed hyphenated symbol
# without picking from the dropdown still falls through to here). Futures
# end in FUT.
_OPTION_RE = re.compile(r"\d(\.\d+)?-?(CE|PE)$")


def _is_derivative_symbol(symbol: str) -> bool:
    return bool(_OPTION_RE.search(symbol)) or symbol.endswith("FUT")

_ORDER_TYPES = {"MARKET", "LIMIT"}
_PRODUCTS = {"CNC", "INTRADAY", "MARGIN"}
_EXCHANGES = {"NSE", "BSE"}
_LEG_KEYWORDS = {"SL", "TARGET", "TRAIL"}


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
        f"[CNC | INTRADAY | MARGIN] [NSE | BSE] [SL <trigger> [<limit>]] "
        f"[TARGET <trigger> [<limit>]] [TRAIL <points>]\n"
        f"e.g. /{side.lower()} RELIANCE 1 LIMIT 2870 SL 2820 TARGET 2950"
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
    sl_trigger_price = None
    sl_limit_price = None
    tgt_trigger_price = None
    tgt_limit_price = None
    trailing_sl_points = None

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
        elif tok == "SL":
            if i + 1 >= len(rest):
                return ParseError("SL requires a trigger price, e.g. SL 2820.")
            try:
                sl_trigger_price = float(rest[i + 1])
            except ValueError:
                return ParseError(f"Invalid SL trigger price '{rest[i + 1]}'.")
            if sl_trigger_price <= 0:
                return ParseError("SL trigger price must be positive.")
            i += 2
            # optional second number = distinct SL limit price
            if i < len(rest):
                try:
                    sl_limit_price = float(rest[i])
                    i += 1
                except ValueError:
                    sl_limit_price = sl_trigger_price
            else:
                sl_limit_price = sl_trigger_price
            continue
        elif tok == "TARGET":
            if i + 1 >= len(rest):
                return ParseError("TARGET requires a trigger price, e.g. TARGET 2950.")
            try:
                tgt_trigger_price = float(rest[i + 1])
            except ValueError:
                return ParseError(f"Invalid TARGET trigger price '{rest[i + 1]}'.")
            if tgt_trigger_price <= 0:
                return ParseError("TARGET trigger price must be positive.")
            i += 2
            if i < len(rest):
                try:
                    tgt_limit_price = float(rest[i])
                    i += 1
                except ValueError:
                    tgt_limit_price = tgt_trigger_price
            else:
                tgt_limit_price = tgt_trigger_price
            continue
        elif tok == "TRAIL":
            if i + 1 >= len(rest):
                return ParseError("TRAIL requires a point value, e.g. TRAIL 5.")
            try:
                trailing_sl_points = float(rest[i + 1])
            except ValueError:
                return ParseError(f"Invalid TRAIL points '{rest[i + 1]}'.")
            if trailing_sl_points <= 0:
                return ParseError("TRAIL points must be positive.")
            i += 2
            continue
        else:
            return ParseError(f"Unrecognized token '{tok}'.\n\n{usage}")
        i += 1

    if trailing_sl_points is not None and sl_trigger_price is None:
        return ParseError("TRAIL requires SL to also be set (it trails an existing stop).")

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
        sl_trigger_price=sl_trigger_price,
        sl_limit_price=sl_limit_price,
        tgt_trigger_price=tgt_trigger_price,
        tgt_limit_price=tgt_limit_price,
        trailing_sl_points=trailing_sl_points,
    )


def format_order_summary(req: OrderRequest) -> str:
    """Human-readable confirm summary shown before firing."""
    price = "at market (auto-LIMIT @ live price)" if req.order_type == "MARKET" \
        else f"LIMIT @ ₹{req.limit_price:g}"
    emoji = "🟢" if req.transaction_type == "BUY" else "🔴"
    lines = [
        f"{emoji} *Confirm order*\n",
        f"• {req.transaction_type} *{req.symbol}*",
        f"• Qty: *{req.quantity}*",
        f"• {price}",
        f"• Product: {req.product}  |  {req.exchange} {req.segment}",
    ]
    if req.sl_trigger_price is not None:
        lines.append(f"• SL: trigger ₹{req.sl_trigger_price:g} / limit ₹{req.sl_limit_price:g}")
    if req.tgt_trigger_price is not None:
        lines.append(f"• Target: trigger ₹{req.tgt_trigger_price:g} / limit ₹{req.tgt_limit_price:g}")
    if req.trailing_sl_points is not None:
        lines.append(f"• Trailing SL: {req.trailing_sl_points:g} points (managed by the bot, not the broker)")
    lines.append("\nPlace this order?")
    return "\n".join(lines)
