"""Agents module for multi-agent stock analysis system."""

from app.agents.analysis_agent import FundamentalAnalysisAgent, TechnicalAnalysisAgent
from app.agents.base import BaseAgent, StatelessAgent
from app.agents.data_agent import AkShareDataAgent, DataCollectionAgent
from app.agents.decision_agent import DecisionMakingAgent
from app.agents.report_agent import ReportGenerationAgent
from app.agents.risk_agent import RiskAssessmentAgent
from app.agents.sentiment_agent import SentimentAnalysisAgent
from app.agents.synthesis_agent import ResearchSynthesisAgent

__all__ = [
    # Base
    "BaseAgent",
    "StatelessAgent",
    # Data Collection
    "DataCollectionAgent",
    "AkShareDataAgent",
    # Analysis
    "TechnicalAnalysisAgent",
    "FundamentalAnalysisAgent",
    # Sentiment
    "SentimentAnalysisAgent",
    # Risk
    "RiskAssessmentAgent",
    # Research synthesis (debate/audit/committee)
    "ResearchSynthesisAgent",
    # Decision
    "DecisionMakingAgent",
    # Report
    "ReportGenerationAgent",
]
