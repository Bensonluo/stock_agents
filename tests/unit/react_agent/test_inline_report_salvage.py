"""Tests for the inline-report salvage path in the ReAct agent."""

from app.react_agent.react_agent import _report_to_markdown, _salvage_inline_report

_REPORT = {
    "title": "Test Report",
    "executive_summary": "It looks fine.",
    "sections": {"overview": {"symbols_analyzed": ["TEST"]}},
    "metadata": {"symbols": ["TEST"]},
}


class TestSalvageInlineReport:
    def test_json_answer_is_salvaged(self):
        import json

        answer = "Here is the report: " + json.dumps(_REPORT)
        assert _salvage_inline_report(answer) == _REPORT

    def test_python_literal_answer_is_salvaged(self):
        # Legacy model behavior: single quotes, unquoted-ish shape.
        answer = (
            "{'title': 'Test Report', 'executive_summary': 'It looks fine.', "
            "'sections': {'overview': {'symbols_analyzed': ['TEST']}}, "
            "'metadata': {'symbols': ['TEST']}}"
        )
        assert _salvage_inline_report(answer) == _REPORT

    def test_markdown_answer_returns_none(self):
        answer = "# Test Report\n\n## Executive Summary\n\nPlain markdown."
        assert _salvage_inline_report(answer) is None

    def test_json_without_sections_returns_none(self):
        assert _salvage_inline_report('{"title": "no sections"}') is None

    def test_non_dict_payload_returns_none(self):
        assert _salvage_inline_report("[1, 2, 3]") is None

    def test_prose_returns_none(self):
        assert _salvage_inline_report("The analysis failed to converge.") is None


class TestReportToMarkdown:
    def test_renders_title_summary_sections(self):
        md = _report_to_markdown(_REPORT)
        assert md.startswith("# Test Report")
        assert "## Executive Summary" in md
        assert "## Overview" in md
        assert '"symbols_analyzed"' in md  # section payload embedded as JSON

    def test_missing_fields_render_minimally(self):
        md = _report_to_markdown({"sections": {}})
        assert md == "# Analysis Report\n"
