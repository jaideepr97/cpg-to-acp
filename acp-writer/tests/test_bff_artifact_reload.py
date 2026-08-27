"""Regression tests for restoring CPG artifacts from MinIO."""

from unittest.mock import MagicMock, patch

from acp_writer.services import bff


def test_reload_preserves_source_cpg_when_registering_dmn_models():
    artifact_store = MagicMock()
    client = artifact_store._get_client.return_value
    client.list_objects_v2.side_effect = [
        {"CommonPrefixes": [{"Prefix": "published/VA-HTN-2020/"}]},
        {"Contents": [{"Key": "published/VA-HTN-2020/dmn/module-a.dmn"}]},
    ]

    with (
        patch.object(bff, "_artifacts_store", artifact_store),
        patch.object(bff, "_register_metadata"),
        patch.object(bff, "_register_dmn_model") as register_dmn_model,
        patch.object(bff, "_register_recommendations"),
    ):
        bff._reload_cpg_artifacts()

    register_dmn_model.assert_called_once_with(
        "cpg-artifacts:published/VA-HTN-2020/dmn/module-a.dmn",
        "module-a",
        "VA-HTN-2020",
    )
