from mcp.server.fastmcp import FastMCP

from src.analysis import regime


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def detect_market_regime(symbol: str) -> dict:
        """Detect the current market regime for a symbol.

        Reuses the same daily technical snapshot logic as the technical tools
        and classifies the symbol into a deterministic market regime.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        return regime.detect_market_regime(symbol)

    @mcp.tool()
    def generate_trade_setup(symbol: str) -> dict:
        """Generate a deterministic trade setup for a symbol.

        Uses the bundled technical analysis plus detected market regime to
        output BUY, SELL, NEUTRAL, NEUTRAL_BULLISH, or NEUTRAL_BEARISH
        with deterministic entry zones, targets, and reasoning.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        return regime.generate_trade_setup(symbol)

    @mcp.tool()
    def recommend_strategy(symbol: str) -> dict:
        """Recommend an options strategy based on the detected market regime.

        Maps trending, neutral, range-bound, and breakout conditions to
        common options structures such as spreads, condors, and straddles.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        return regime.recommend_strategy(symbol)

    @mcp.tool()
    def calculate_risk_reward(entry: float, stoploss: float, target: float) -> dict:
        """Calculate absolute risk, reward, and reward-to-risk ratio.

        Args:
            entry: Proposed trade entry price.
            stoploss: Protective stop price.
            target: Profit target price.
        """
        return regime.calculate_risk_reward(entry, stoploss, target)

    @mcp.tool()
    def calculate_position_size(
        capital: float,
        risk_percent: float,
        entry: float,
        stoploss: float,
    ) -> dict:
        """Calculate position size from capital, risk %, entry, and stoploss.

        Args:
            capital: Total trading capital.
            risk_percent: Percent of capital to risk on the trade.
            entry: Planned entry price.
            stoploss: Planned stoploss price.
        """
        return regime.calculate_position_size(capital, risk_percent, entry, stoploss)
