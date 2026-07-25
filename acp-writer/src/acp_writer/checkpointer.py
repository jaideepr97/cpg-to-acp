"""Checkpoint management for pipeline state persistence."""

import os

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

CHECKPOINT_DB_PATH = os.environ.get("CHECKPOINT_DB_PATH", "data/checkpoints.db")


def get_checkpointer(use_sqlite: bool | None = None) -> MemorySaver | SqliteSaver:
    """Return a checkpointer for the pipeline.

    Uses SqliteSaver by default when CHECKPOINT_DB_PATH is set,
    MemorySaver otherwise. Pass use_sqlite explicitly to override.
    """
    if use_sqlite is False:
        return MemorySaver()

    if use_sqlite is True or os.environ.get("CHECKPOINT_DB_PATH"):
        db_path = CHECKPOINT_DB_PATH
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = SqliteSaver.from_conn_string(db_path)
        conn.setup()
        return conn

    return MemorySaver()
