"""DMN publication keys must not require proxy-path percent encoding."""

import re
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest

from cpg_ingester.artifact_id import make_artifact_id
from cpg_ingester.nodes.delivery import delivery


@pytest.mark.parametrize("name", [
    "Decision Table One",
    "Decision/Table: One?",
    "Decision + Table #1 (reviewed)",
    "Decision%20Table",
    "Décision — Übersicht",
    "決定表",
    "../../outside",
    "./",
    "",
    "A" * 400,
    "Decision\nTable\tOne",
])
def test_dmn_filename_is_a_bounded_url_safe_basename(name):
    from cpg_ingester.nodes.delivery import _dmn_object_filename

    filename = _dmn_object_filename(name, "Section 1")

    assert re.fullmatch(r"[a-z0-9_-]+-[0-9a-f]{12}\.dmn", filename)
    assert len(filename) <= 67
    assert quote(filename, safe="") == filename
    assert _dmn_object_filename(name, "Section 1") == filename


@pytest.mark.parametrize(("first", "second"), [
    (("Decision Table", "1"), ("Decision-Table", "1")),
    (("Decision Table", "1"), ("Decision Table", "2")),
    (("Decision Table", "1"), ("decision table", "1")),
    (("Decision:", "A"), ("Decision", ":A")),
    (("A" * 100 + "X", "1"), ("A" * 100 + "Y", "1")),
    (("決定表", "1"), ("表", "1")),
])
def test_dmn_filenames_do_not_collide_after_slug_normalization(first, second):
    from cpg_ingester.nodes.delivery import _dmn_object_filename

    assert _dmn_object_filename(*first) != _dmn_object_filename(*second)


def test_delivery_uses_safe_keys_and_preserves_manifest_identity(tmp_path):
    store = MagicMock()
    store.bucket = "cpg-artifacts"
    store.put.side_effect = lambda key, value: f"cpg-artifacts:{key}"
    uploaded = {}

    def put_raw(key, body, content_type):
        # Model the reported proxy canonical-path failure. This is not a live
        # OpenShell/S3 signature test: it makes encoding-sensitive keys fail.
        if quote(key, safe="/") != key:
            raise RuntimeError("SignatureDoesNotMatch: encoded object key")
        assert content_type == "application/xml"
        assert key not in uploaded
        uploaded[key] = body
        return f"cpg-artifacts:{key}"

    store.put_raw.side_effect = put_raw
    items = [
        {"name": "Decision Table / A", "section": "1"},
        {"name": "Decision-Table-A", "section": "1"},
        {"name": "Decision Table / A", "section": "2"},
    ]
    xml = b'<definitions id="unchanged"/>'
    state = {
        "cpg_metadata": {"cpg_id": "CPG-TEST"},
        "dmn_results": [{"item": item, "dmn_xml": xml.decode()} for item in items],
        "artifact_store": store,
        "output_dir": str(tmp_path),
    }

    result = delivery(state)["delivery_status"]

    assert result["published"] is True
    assert result["errors"] == []
    assert len(uploaded) == len(items)
    artifacts = [a for a in result["artifacts"] if a["type"] == "dmn"]
    assert len(artifacts) == len(items)
    for item, artifact in zip(items, artifacts):
        assert artifact["name"] == item["name"]
        assert artifact["artifact_id"] == make_artifact_id(
            "CPG-TEST", "dmn", item["name"], item["section"]
        )
        key = artifact["ref"].removeprefix("cpg-artifacts:")
        assert key.startswith("published/CPG-TEST/dmn/")
        assert re.fullmatch(r"[a-z0-9_-]+-[0-9a-f]{12}\.dmn", key.rsplit("/", 1)[-1])
        assert uploaded[key] == xml

    # Retries overwrite the same object names rather than creating new keys.
    original_keys = set(uploaded)
    uploaded.clear()
    retried = delivery(state)["delivery_status"]
    assert retried["published"] is True
    assert set(uploaded) == original_keys
    assert retried["artifacts"] == result["artifacts"]
