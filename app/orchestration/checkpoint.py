"""PostgreSQL checkpoint manager for state persistence."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.orchestration.state import AgentState

Base = declarative_base()


class CheckpointEntry(Base):
    """Checkpoint database model."""

    __tablename__ = "checkpoints"

    thread_id = Column(String, primary_key=True)
    checkpoint_id = Column(String, primary_key=True)
    checkpoint = Column(Text, nullable=False)
    meta_data = Column(Text, nullable=True)  # Renamed from 'metadata'
    created_at = Column(DateTime, default=datetime.utcnow)
    step = Column(Integer, default=0)


class CheckpointState(Base):
    """State associated with checkpoints."""

    __tablename__ = "checkpoint_states"

    thread_id = Column(String, primary_key=True)
    checkpoint_id = Column(String, primary_key=True)
    state = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PostgresCheckpointManager:
    """PostgreSQL state persistence manager.

    This class provides:
    - Checkpoint saving and loading
    - State recovery after failures
    - Time travel (restore to previous checkpoints)
    - Concurrent-safe state management

    Core learning: Understanding how state persistence enables
    fault tolerance and recovery in distributed systems.
    """

    def __init__(self, connection_string: Optional[str] = None):
        """Initialize the checkpoint manager.

        Args:
            connection_string: PostgreSQL connection string.
                If None, uses the connection string from settings.
        """
        self.connection_string = connection_string or settings.database_url
        self.engine = create_engine(self.connection_string)
        self.Session = sessionmaker(bind=self.engine)

        # Create tables if they don't exist
        Base.metadata.create_all(self.engine)

        # LangGraph checkpoint saver (in-memory for now, can be replaced with PostgreSQL)
        self.checkpoint_saver = MemorySaver()

    def save_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpoint: Checkpoint,
        metadata: Optional[CheckpointMetadata] = None,
        state: Optional[AgentState] = None,
    ) -> None:
        """Save a checkpoint to PostgreSQL.

        Args:
            thread_id: Unique identifier for the conversation/workflow thread
            checkpoint_id: Unique identifier for this checkpoint
            checkpoint: The checkpoint data from LangGraph
            metadata: Optional metadata about the checkpoint
            state: Optional AgentState to serialize and save
        """
        session = self.Session()

        try:
            # Serialize checkpoint
            checkpoint_data = self._serialize_checkpoint(checkpoint)

            # Create checkpoint entry
            entry = CheckpointEntry(
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                checkpoint=checkpoint_data,
                metadata=json.dumps(metadata) if metadata else None,
                created_at=datetime.utcnow(),
            )

            # Merge to handle new and existing entries
            session.merge(entry)

            # Save state if provided
            if state:
                state_entry = CheckpointState(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    state=json.dumps(state, default=str),
                    created_at=datetime.utcnow(),
                )
                session.merge(state_entry)

            session.commit()

        except Exception as e:
            session.rollback()
            raise RuntimeError(f"Failed to save checkpoint: {e}") from e
        finally:
            session.close()

    def load_checkpoint(
        self, thread_id: str, checkpoint_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Load a checkpoint from PostgreSQL.

        Args:
            thread_id: Unique identifier for the conversation/workflow thread
            checkpoint_id: Optional checkpoint ID. If None, loads the latest.

        Returns:
            The loaded checkpoint, or None if not found
        """
        session = self.Session()

        try:
            query = session.query(CheckpointEntry).filter_by(thread_id=thread_id)

            if checkpoint_id:
                query = query.filter_by(checkpoint_id=checkpoint_id)
            else:
                # Get the latest checkpoint
                query = query.order_by(CheckpointEntry.created_at.desc())

            entry = query.first()

            if not entry:
                return None

            return self._deserialize_checkpoint(entry.checkpoint)

        except Exception as e:
            raise RuntimeError(f"Failed to load checkpoint: {e}") from e
        finally:
            session.close()

    def load_state(
        self, thread_id: str, checkpoint_id: Optional[str] = None
    ) -> Optional[AgentState]:
        """Load an AgentState from PostgreSQL.

        Args:
            thread_id: Unique identifier for the conversation/workflow thread
            checkpoint_id: Optional checkpoint ID. If None, loads the latest.

        Returns:
            The loaded AgentState, or None if not found
        """
        session = self.Session()

        try:
            query = session.query(CheckpointState).filter_by(thread_id=thread_id)

            if checkpoint_id:
                query = query.filter_by(checkpoint_id=checkpoint_id)
            else:
                # Get the latest state
                query = query.order_by(CheckpointState.created_at.desc())

            entry = query.first()

            if not entry:
                return None

            return AgentState(**json.loads(entry.state))

        except Exception as e:
            raise RuntimeError(f"Failed to load state: {e}") from e
        finally:
            session.close()

    def list_checkpoints(
        self, thread_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """List all checkpoints for a thread.

        This enables "time travel" - the ability to restore to any
        previous state in the workflow.

        Args:
            thread_id: Unique identifier for the conversation/workflow thread
            limit: Maximum number of checkpoints to return

        Returns:
            List of checkpoint summaries
        """
        session = self.Session()

        try:
            entries = (
                session.query(CheckpointEntry)
                .filter_by(thread_id=thread_id)
                .order_by(CheckpointEntry.created_at.desc())
                .limit(limit)
                .all()
            )

            return [
                {
                    "checkpoint_id": entry.checkpoint_id,
                    "created_at": entry.created_at.isoformat(),
                    "step": entry.step,
                    "metadata": json.loads(entry.meta_data) if entry.meta_data else None,
                }
                for entry in entries
            ]

        except Exception as e:
            raise RuntimeError(f"Failed to list checkpoints: {e}") from e
        finally:
            session.close()

    def delete_checkpoint(self, thread_id: str, checkpoint_id: str) -> bool:
        """Delete a specific checkpoint.

        Args:
            thread_id: Unique identifier for the conversation/workflow thread
            checkpoint_id: Checkpoint ID to delete

        Returns:
            True if deleted, False if not found
        """
        session = self.Session()

        try:
            # Delete checkpoint entry
            deleted = (
                session.query(CheckpointEntry)
                .filter_by(thread_id=thread_id, checkpoint_id=checkpoint_id)
                .delete()
            )

            # Delete associated state
            session.query(CheckpointState).filter_by(
                thread_id=thread_id, checkpoint_id=checkpoint_id
            ).delete()

            session.commit()
            return deleted > 0

        except Exception as e:
            session.rollback()
            raise RuntimeError(f"Failed to delete checkpoint: {e}") from e
        finally:
            session.close()

    def delete_thread(self, thread_id: str) -> int:
        """Delete all checkpoints for a thread.

        Args:
            thread_id: Unique identifier for the conversation/workflow thread

        Returns:
            Number of checkpoints deleted
        """
        session = self.Session()

        try:
            # Count checkpoints to be deleted
            count = (
                session.query(CheckpointEntry)
                .filter_by(thread_id=thread_id)
                .count()
            )

            # Delete all checkpoints
            session.query(CheckpointEntry).filter_by(thread_id=thread_id).delete()
            session.query(CheckpointState).filter_by(thread_id=thread_id).delete()

            session.commit()
            return count

        except Exception as e:
            session.rollback()
            raise RuntimeError(f"Failed to delete thread: {e}") from e
        finally:
            session.close()

    def get_checkpoint_saver(self) -> BaseCheckpointSaver:
        """Get the LangGraph checkpoint saver.

        Returns:
            LangGraph compatible checkpoint saver
        """
        return self.checkpoint_saver

    def _serialize_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Serialize checkpoint to JSON string.

        Args:
            checkpoint: Checkpoint to serialize

        Returns:
            JSON string representation
        """
        # Convert checkpoint to dict for JSON serialization
        checkpoint_dict = {
            "id": checkpoint.get("id"),
            "channel_values": checkpoint.get("channel_values", {}),
            "channel_versions": checkpoint.get("channel_versions", {}),
            "versions_seen": checkpoint.get("versions_seen", {}),
        }

        return json.dumps(checkpoint_dict, default=str)

    def _deserialize_checkpoint(self, data: str) -> Checkpoint:
        """Deserialize JSON string to checkpoint.

        Args:
            data: JSON string representation

        Returns:
            Checkpoint object
        """
        checkpoint_dict = json.loads(data)
        return Checkpoint(**checkpoint_dict)

    def create_config(self, thread_id: str) -> Dict[str, Any]:
        """Create a LangGraph config dict for a thread.

        Args:
            thread_id: Unique identifier for the conversation/workflow thread

        Returns:
            Config dict for LangGraph operations
        """
        return {
            "configurable": {
                "thread_id": thread_id,
            }
        }


class InMemoryCheckpointManager:
    """In-memory checkpoint manager for testing and development.

    This is a simpler alternative to PostgreSQL persistence,
    useful for development and testing.
    """

    def __init__(self):
        """Initialize the in-memory checkpoint manager."""
        self.checkpoints: Dict[str, Dict[str, Checkpoint]] = {}
        self.states: Dict[str, Dict[str, AgentState]] = {}
        self.checkpoint_saver = MemorySaver()

    def save_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpoint: Checkpoint,
        metadata: Optional[CheckpointMetadata] = None,
        state: Optional[AgentState] = None,
    ) -> None:
        """Save a checkpoint to memory."""
        if thread_id not in self.checkpoints:
            self.checkpoints[thread_id] = {}
        self.checkpoints[thread_id][checkpoint_id] = checkpoint

        if state:
            if thread_id not in self.states:
                self.states[thread_id] = {}
            self.states[thread_id][checkpoint_id] = state

    def load_checkpoint(
        self, thread_id: str, checkpoint_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """Load a checkpoint from memory."""
        if thread_id not in self.checkpoints:
            return None

        if checkpoint_id:
            return self.checkpoints[thread_id].get(checkpoint_id)

        # Return latest checkpoint
        checkpoints = self.checkpoints[thread_id]
        return list(checkpoints.values())[-1] if checkpoints else None

    def load_state(
        self, thread_id: str, checkpoint_id: Optional[str] = None
    ) -> Optional[AgentState]:
        """Load a state from memory."""
        if thread_id not in self.states:
            return None

        if checkpoint_id:
            return self.states[thread_id].get(checkpoint_id)

        # Return latest state
        states = self.states[thread_id]
        return list(states.values())[-1] if states else None

    def list_checkpoints(
        self, thread_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """List checkpoints for a thread."""
        if thread_id not in self.checkpoints:
            return []

        checkpoints = self.checkpoints[thread_id]
        return [
            {"checkpoint_id": ck_id, "created_at": datetime.now().isoformat()}
            for ck_id, _ in list(checkpoints.items())[:limit]
        ]

    def delete_checkpoint(self, thread_id: str, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        if thread_id in self.checkpoints and checkpoint_id in self.checkpoints[thread_id]:
            del self.checkpoints[thread_id][checkpoint_id]
            if thread_id in self.states and checkpoint_id in self.states[thread_id]:
                del self.states[thread_id][checkpoint_id]
            return True
        return False

    def delete_thread(self, thread_id: str) -> int:
        """Delete all checkpoints for a thread."""
        count = len(self.checkpoints.get(thread_id, {}))
        self.checkpoints.pop(thread_id, None)
        self.states.pop(thread_id, None)
        return count

    def get_checkpoint_saver(self) -> BaseCheckpointSaver:
        """Get the LangGraph checkpoint saver."""
        return self.checkpoint_saver

    def create_config(self, thread_id: str) -> Dict[str, Any]:
        """Create a LangGraph config dict for a thread."""
        return {
            "configurable": {
                "thread_id": thread_id,
            }
        }
