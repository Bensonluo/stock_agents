import pytest


def test_generate_report():
    """Test report generation."""
    from app.tools.report.generate import generate_report

    data = {
        "query": "Should I buy AAPL?",
        "symbols": ["AAPL"],
        "market_data": {
            "AAPL": {"current_price": 150.0, "company_name": "Apple Inc"}
        },
        "technical_analysis": {
            "AAPL": {"sentiment": {"score": 30, "sentiment": "buy"}}
        },
        "fundamental_analysis": {
            "AAPL": {"overall_score": {"score": 65}, "recommendation": "buy"}
        },
        "sentiment_analysis": {
            "sentiment_by_symbol": {
                "AAPL": {"sentiment": "positive", "score": 25}
            }
        },
        "risk_assessment": {
            "AAPL": {"risk_level": "medium", "risk_score": 40}
        },
        "decision": {
            "AAPL": {"action": "buy", "confidence": 75}
        },
    }

    result = generate_report.invoke({"data": data})

    assert "title" in result
    assert "executive_summary" in result
    assert "sections" in result
    assert "AAPL" in result["sections"]["recommendations"]["by_symbol"]
