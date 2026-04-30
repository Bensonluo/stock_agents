import pytest


def test_analyze_technical():
    """Test technical analysis with synthetic data."""
    from app.tools.analysis.technical import analyze_technical

    market_data = {
        "AAPL": {
            "current_price": 150.0,
            "historical_data": {
                "dates": ["2024-01-" + str(i).zfill(2) for i in range(1, 31)],
                "open": [100.0 + i for i in range(30)],
                "high": [101.0 + i for i in range(30)],
                "low": [99.0 + i for i in range(30)],
                "close": [100.0 + i for i in range(30)],
                "volume": [1000000] * 30,
            }
        }
    }

    result = analyze_technical.invoke({"market_data": market_data})

    assert "AAPL" in result
    assert "indicators" in result["AAPL"]
    assert "signals" in result["AAPL"]
    assert "sentiment" in result["AAPL"]


def test_analyze_fundamental():
    """Test fundamental analysis."""
    from app.tools.analysis.fundamental import analyze_fundamental

    financial_data = {
        "AAPL": {
            "metrics": {
                "roe": 0.25,
                "roa": 0.15,
                "profit_margin": 0.20,
                "operating_margin": 0.25,
                "pe_ratio": 20.0,
                "pb_ratio": 5.0,
                "ps_ratio": 6.0,
                "ev_ebitda": 15.0,
                "debt_to_equity": 1.5,
                "current_ratio": 1.2,
                "quick_ratio": 1.0,
            }
        }
    }

    market_data = {"AAPL": {"current_price": 150.0}}

    result = analyze_fundamental.invoke({
        "financial_data": financial_data,
        "market_data": market_data,
    })

    assert "AAPL" in result
    assert "overall_score" in result["AAPL"]
    assert "recommendation" in result["AAPL"]


def test_analyze_sentiment():
    """Test sentiment analysis."""
    from app.tools.analysis.sentiment import analyze_sentiment

    news_data = [
        {
            "title": "Apple stock surges on strong earnings",
            "summary": "Apple reported record profits",
            "related_symbols": ["AAPL"],
            "original_symbol": "AAPL",
        },
        {
            "title": "Market falls on recession fears",
            "summary": "Global markets decline",
            "related_symbols": ["AAPL"],
            "original_symbol": "AAPL",
        },
    ]

    result = analyze_sentiment.invoke({
        "news_data": news_data,
        "symbols": ["AAPL"],
    })

    assert "sentiment_by_symbol" in result
    assert "AAPL" in result["sentiment_by_symbol"]
    assert "score" in result["sentiment_by_symbol"]["AAPL"]
