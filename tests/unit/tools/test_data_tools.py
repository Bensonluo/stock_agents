import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_fetch_stock_data_mocked():
    """Test fetch_stock_data with mocked yfinance."""
    from app.tools.data.market_data import fetch_stock_data

    mock_ticker = MagicMock()
    mock_ticker.info = {
        "currentPrice": 150.0,
        "previousClose": 145.0,
        "volume": 1000000,
        "marketCap": 2000000000,
        "longName": "Apple Inc",
        "sector": "Technology",
    }
    mock_hist = MagicMock()
    mock_hist.empty = False
    mock_hist.index = [MagicMock(strftime=lambda fmt: "2024-01-01")]
    mock_hist.__getitem__ = lambda self, key: MagicMock(tolist=lambda: [150.0])
    mock_ticker.history.return_value = mock_hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await fetch_stock_data.ainvoke({"symbols": ["AAPL"]})

    assert "AAPL" in result
    assert result["AAPL"]["market_data"]["current_price"] == 150.0


@pytest.mark.asyncio
async def test_get_historical_prices_mocked():
    """Test get_historical_prices with mocked yfinance."""
    from app.tools.data.historical import get_historical_prices

    mock_ticker = MagicMock()
    mock_hist = MagicMock()
    mock_hist.empty = False
    mock_hist.index = [MagicMock(strftime=lambda fmt: "2024-01-01")]
    mock_hist.__getitem__ = lambda self, key: MagicMock(tolist=lambda: [150.0])
    mock_ticker.history.return_value = mock_hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = await get_historical_prices.ainvoke({
            "symbol": "AAPL",
            "period": "1mo",
        })

    assert "dates" in result
    assert "close" in result
