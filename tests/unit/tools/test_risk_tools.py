import pytest
import numpy as np


def test_assess_risk():
    """Test risk assessment with synthetic data."""
    from app.tools.risk.assessment import assess_risk

    market_data = {
        "AAPL": {
            "historical_data": {
                "close": list(100.0 + np.random.randn(50).cumsum()),
            }
        }
    }

    result = assess_risk.invoke({"market_data": market_data})

    assert "AAPL" in result
    assert "risk_score" in result["AAPL"]
    assert "risk_level" in result["AAPL"]
    assert "metrics" in result["AAPL"]


def test_calculate_position_size():
    """Test position sizing."""
    from app.tools.decision.portfolio import calculate_position_size

    risk_data = {
        "AAPL": {
            "risk_score": 50,
            "risk_level": "medium",
            "position_recommendation": {
                "max_position_size": 10.0,
                "stop_loss_percentage": 5.0,
            }
        }
    }

    result = calculate_position_size.invoke({"risk_data": risk_data})

    assert "AAPL" in result
    assert "position_size" in result["AAPL"]
