"""Deterministic artifact ID generation for CPG ingester outputs."""

import hashlib


def make_artifact_id(cpg_id: str, artifact_type: str, name: str, section: str = "") -> str:
    """Generate a deterministic, human-readable artifact ID.

    Format: ``{cpg_id}-{type}-{hash6}``
    The hash is derived from the item's name and section so it is
    stable across regenerations of the same content.
    """
    content = f"{name}:{section}"
    short_hash = hashlib.sha256(content.encode()).hexdigest()[:6]
    return f"{cpg_id}-{artifact_type}-{short_hash}"
