"""Removed configuration keys must not prevent upgrades with existing dotenv files."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_existing_dotenv_can_keep_removed_redis_url(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("REDIS_URL=redis://localhost:6379\nMAX_RETRIES=7\n")

    settings = Settings(_env_file=dotenv)

    assert settings.max_retries == 7
    assert "redis_url" not in settings.model_dump()
    assert "redis_url" not in Settings.model_fields


def test_unknown_dotenv_keys_remain_validation_errors(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("REDIS_URL=redis://localhost:6379\nUNKNOWN_SETTING=true\n")

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=dotenv)

    assert [(item["loc"], item["type"]) for item in error.value.errors()] == [
        (("unknown_setting",), "extra_forbidden")
    ]
