def test_agent_settings_exist():
    from app.config import settings

    assert hasattr(settings, "agent_max_iterations")
    assert settings.agent_max_iterations == 15
    assert hasattr(settings, "agent_cost_limit")
    assert settings.agent_cost_limit == 0.50
    assert hasattr(settings, "agent_reasoning_model")
    assert settings.agent_reasoning_model == "glm-4.7"
    assert hasattr(settings, "agent_reflection_model")
    assert settings.agent_reflection_model == "glm-4.5-air"
