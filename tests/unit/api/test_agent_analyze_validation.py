"""Contract pins for the ReAct analyze request model.

The pipeline twin (StockAnalysisRequest, analysis.py) has enforced
min_length=1 on both query and symbols since it was written; the ReAct
route accepted an empty query or an empty symbol list, which flowed into
the agent loop as a no-instruction run. These pins lock the parity.
"""

import pytest
from pydantic import ValidationError

from app.api.routes.agent import AnalyzeRequest


class TestAnalyzeRequestValidation:
    def test_empty_query_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AnalyzeRequest(query="", symbols=["AAPL"])

    def test_empty_symbols_list_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AnalyzeRequest(query="分析这只股票", symbols=[])

    def test_well_formed_request_accepted(self) -> None:
        request = AnalyzeRequest(query="分析这只股票的投资价值", symbols=["600000", "AAPL"])
        assert request.query == "分析这只股票的投资价值"
        assert request.symbols == ["600000", "AAPL"]
