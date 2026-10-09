"""Artifact-store authentication paths for sandbox and regular deployments."""

import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3
import pytest
import requests

from cpg_contracts.artifact_store import ArtifactStore, get_artifact_store


class _S3Client:
    def __init__(self):
        self.calls = []

    def head_bucket(self, **kwargs):
        self.calls.append(("head_bucket", kwargs))

    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))

    def get_object(self, **kwargs):
        self.calls.append(("get_object", kwargs))
        return {"Body": io.BytesIO(b"pdf contents")}

    def generate_presigned_url(self, *args, **kwargs):
        self.calls.append(("generate_presigned_url", (args, kwargs)))
        return "http://minio:9000/upload?signature=test"


def test_sandbox_uses_aws_placeholders_and_sdk_signed_requests(monkeypatch):
    monkeypatch.setenv("ARTIFACT_STORE_URL", "http://minio:9000")
    monkeypatch.setenv("ARTIFACT_STORE_ACCESS_KEY", "legacy-access")
    monkeypatch.setenv("ARTIFACT_STORE_SECRET_KEY", "legacy-secret")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "sandbox-access-placeholder")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "sandbox-secret-placeholder")
    client = _S3Client()
    captured = {}

    def fake_client(service, **kwargs):
        captured.update(kwargs)
        assert service == "s3"
        return client

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.setattr(requests, "put", lambda *args, **kwargs: pytest.fail("presigned PUT used"))

    store = get_artifact_store()
    assert store is not None
    assert store.put_raw("test.pdf", b"pdf contents", "application/pdf") == "cpg-artifacts:test.pdf"
    assert store.put("test.json", {"ok": True}) == "cpg-artifacts:test.json"
    assert store.get_raw("cpg-uploads:test.pdf") == b"pdf contents"
    assert captured["aws_access_key_id"] == "sandbox-access-placeholder"
    assert captured["aws_secret_access_key"] == "sandbox-secret-placeholder"
    assert captured["config"].signature_version == "s3v4"
    assert captured["config"].s3 == {
        "addressing_style": "path",
        "payload_signing_enabled": False,
    }
    assert captured["config"].request_checksum_calculation == "when_required"
    assert ("put_object", {
        "Bucket": "cpg-artifacts",
        "Key": "test.pdf",
        "Body": b"pdf contents",
        "ContentType": "application/pdf",
    }) in client.calls
    assert ("put_object", {
        "Bucket": "cpg-artifacts",
        "Key": "test.json",
        "Body": b'{"ok": true}',
        "ContentType": "application/json",
    }) in client.calls
    assert ("get_object", {"Bucket": "cpg-uploads", "Key": "test.pdf"}) in client.calls
    assert not any(name == "generate_presigned_url" for name, _ in client.calls)


def test_regular_deployment_keeps_direct_credentials_and_presigned_put(monkeypatch):
    monkeypatch.setenv("ARTIFACT_STORE_URL", "http://minio:9000")
    monkeypatch.setenv("ARTIFACT_STORE_ACCESS_KEY", "real-access")
    monkeypatch.setenv("ARTIFACT_STORE_SECRET_KEY", "real-secret")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    client = _S3Client()
    captured = {}

    def fake_client(service, **kwargs):
        captured.update(kwargs)
        return client

    class _Response:
        def raise_for_status(self):
            pass

    put_calls = []
    monkeypatch.setattr(boto3, "client", fake_client)
    def fake_put(*args, **kwargs):
        put_calls.append((args, kwargs))
        return _Response()

    monkeypatch.setattr(requests, "put", fake_put)

    store = get_artifact_store()
    assert store is not None
    assert store.put("sample.json", {"ok": True}) == "cpg-artifacts:sample.json"
    assert captured["aws_access_key_id"] == "real-access"
    assert captured["aws_secret_access_key"] == "real-secret"
    assert len(put_calls) == 1
    assert put_calls[0][0][0].startswith("http://minio:9000/upload?")
    assert not any(name == "put_object" for name, _ in client.calls)


def test_incomplete_aws_pair_fails_closed(monkeypatch):
    monkeypatch.setenv("ARTIFACT_STORE_URL", "http://minio:9000")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "sandbox-placeholder")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(ValueError, match="must be set together"):
        get_artifact_store()


def test_explicit_bff_store_does_not_enable_proxy_signing(monkeypatch):
    """BFF construction stays direct even if unrelated AWS env vars are set."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "unrelated")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "unrelated")
    store = ArtifactStore("http://minio:9000", access_key="bff-key", secret_key="bff-secret")
    assert store._proxy_signing is False


def test_sandbox_put_object_emits_signable_header_request():
    """Exercise real boto3 serialization without sending credentials off-host."""
    requests_seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def do_PUT(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests_seen.append((self.path, dict(self.headers), body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        store = ArtifactStore(
            f"http://127.0.0.1:{server.server_port}",
            access_key="sandbox-access-placeholder",
            secret_key="sandbox-secret-placeholder",
            proxy_signing=True,
        )
        assert store.put_raw("test.pdf", b"pdf contents", "application/pdf") == "cpg-artifacts:test.pdf"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    assert len(requests_seen) == 1
    path, headers, body = requests_seen[0]
    assert path == "/cpg-artifacts/test.pdf"
    assert body == b"pdf contents"
    assert headers["Content-Type"] == "application/pdf"
    assert "Credential=sandbox-access-placeholder/" in headers["Authorization"]
    assert headers["X-Amz-Content-SHA256"] == "UNSIGNED-PAYLOAD"
