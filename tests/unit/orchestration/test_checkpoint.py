from typing import cast

from langgraph.checkpoint.base import Checkpoint

from app.orchestration.checkpoint import PostgresCheckpointManager


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
