"""Report evaluation: deterministic rubric grading + optional LLM-as-judge."""

from app.eval.rubric import EvalResult, grade_report

__all__ = ["EvalResult", "grade_report"]
