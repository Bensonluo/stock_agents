from app.react_agent.prompts import (
    REASONING_SYSTEM_PROMPT,
    REFLECTION_PROMPT_TEMPLATE,
    PROMPT_VERSION,
    format_reflection_prompt,
)


def test_system_prompt_exists():
    assert isinstance(REASONING_SYSTEM_PROMPT, str)
    assert len(REASONING_SYSTEM_PROMPT) > 100
    assert "tools" in REASONING_SYSTEM_PROMPT.lower()


def test_reflection_prompt_exists():
    assert isinstance(REFLECTION_PROMPT_TEMPLATE, str)
    assert len(REFLECTION_PROMPT_TEMPLATE) > 50


def test_prompt_version_exists():
    assert isinstance(PROMPT_VERSION, str)
    assert len(PROMPT_VERSION.split(".")) >= 2


def test_format_reflection_prompt():
    prompt = format_reflection_prompt(
        iteration=3,
        max_iterations=15,
        tools_used=["fetch_stock_data", "analyze_technical"],
        query="Should I buy AAPL?",
    )
    assert "3/15" in prompt
    assert "fetch_stock_data" in prompt
    assert "AAPL" in prompt
