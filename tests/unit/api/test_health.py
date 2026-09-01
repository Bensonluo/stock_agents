from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import health


@pytest.mark.asyncio
async def test_readiness_checks_database(monkeypatch) -> None:
    database = Mock()
    monkeypatch.setattr(health, "get_database", lambda: database)

    result = await health.readiness_check()

    database.list_records.assert_called_once_with(limit=1)
    assert result["ready"] is True
    assert result["components"]["database"] == "ready"


@pytest.mark.asyncio
async def test_readiness_fails_when_database_is_unavailable(monkeypatch) -> None:
    database = Mock()
    database.list_records.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(health, "get_database", lambda: database)

    with pytest.raises(HTTPException) as exc_info:
        await health.readiness_check()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["ready"] is False
