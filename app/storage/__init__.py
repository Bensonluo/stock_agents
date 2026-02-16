"""
Storage module for stock analysis system.
"""

from .database import Database, AnalysisRecord, get_database

__all__ = ["Database", "AnalysisRecord", "get_database"]
