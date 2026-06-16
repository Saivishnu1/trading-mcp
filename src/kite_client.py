# Deprecated — replaced by src/broker/ (ZerodhaWebClient) and src/market/ (MarketService).
# This file is kept only to avoid breaking any external references.
# Do not import from here.
raise ImportError(
    "src.kite_client is deprecated. "
    "Use src.broker.get_broker() for portfolio data "
    "and src.market.get_market() for market data."
)
