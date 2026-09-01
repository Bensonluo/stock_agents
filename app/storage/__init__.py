"""
Storage module for stock analysis system.
"""

from .database import AnalysisRecord, Database, get_database

__all__ = ["Database", "AnalysisRecord", "get_database"]
