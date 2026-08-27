"""Report generation tool over the shared ReportService.

All section building lives in ``app/services/report_service.py``; this module
keeps only the LangChain tool wrapper the ReAct agent calls.
"""

from datetime import datetime
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.services.report_service import ReportService


class GenerateReportInput(BaseModel):
    data: dict = Field(description="All analysis data to compile into a report")


@tool(args_schema=GenerateReportInput)
def generate_report(data: dict) -> dict[str, Any]:
    """Generate a structured investment analysis report.

    This is the FINAL tool you should call. It compiles all analysis results
    into a comprehensive report.
    """
    report = ReportService.build_report(data)
    report["generated_at"] = datetime.now().isoformat()
    return report
