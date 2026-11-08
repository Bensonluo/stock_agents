from typing import cast

from langgraph.checkpoint.base import Checkpoint

from app.orchestration.checkpoint import PostgresCheckpointManager, _pin_legacy_postgres_driver


def test_checkpoint_metadata_uses_mapped_column(tmp_path) -> None:
    manager = PostgresCheckpointManager(f"sqlite:///{tmp_path / 'checkpoints.db'}")
    checkpoint = cast(
        Checkpoint,
        {
            "id": "checkpoint-1",
            "channel_values": {},
            "channel_versions": {},
            "versions_seen": {},
        },
    )

    manager.save_checkpoint(
        thread_id="thread-1",
        checkpoint_id="checkpoint-1",
        checkpoint=checkpoint,
        metadata={"source": "test"},
    )

    checkpoints = manager.list_checkpoints("thread-1")
    assert checkpoints[0]["metadata"] == {"source": "test"}


def test_driverless_postgres_url_pins_psycopg2() -> None:
    """SQLAlchemy 2.1 defaults driverless postgres:// to psycopg (v3); we ship psycopg2."""
    assert (
        _pin_legacy_postgres_driver("postgresql://admin:pw@localhost:5432/stockdb")
        == "postgresql+psycopg2://admin:pw@localhost:5432/stockdb"
    )


def test_explicit_driver_urls_pass_through() -> None:
    assert (
        _pin_legacy_postgres_driver("postgresql+psycopg2://u:p@h/db")
        == "postgresql+psycopg2://u:p@h/db"
    )
    assert (
        _pin_legacy_postgres_driver("postgresql+psycopg://u:p@h/db")
        == "postgresql+psycopg://u:p@h/db"
    )
    assert _pin_legacy_postgres_driver("sqlite:///checkpoints.db") == "sqlite:///checkpoints.db"
