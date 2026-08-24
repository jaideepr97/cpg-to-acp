"""Tests for figure persistence in the ingestion service."""

import base64

import cpg_ingester.services.ingestion as ing


class _FakeStore:
    """Minimal artifact store that records put_raw calls."""

    def __init__(self):
        self.calls = []

    def put_raw(self, key, data, content_type="application/octet-stream"):
        self.calls.append((key, data, content_type))
        return f"bucket:{key}"


def _figs():
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
    figures = [
        {"id": "fig-001", "page": 1, "classification": "flow_chart"},
        {"id": "fig-002", "page": 2, "classification": "picture"},
    ]
    images = {"fig-001": png, "fig-002": png}
    return figures, images, png


def test_persist_figures_uploads_to_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(ing, "_store", store)
    figures, images, _ = _figs()

    result = ing._persist_figures(figures, images, "run-xyz")

    # Each figure gets an image_ref and no inline bytes.
    for fig in result:
        assert fig["image_ref"] == f"bucket:run-xyz/figures/{fig['id']}.png"
        assert "image_b64" not in fig
    # Uploaded as PNGs under the shared run prefix.
    assert [c[0] for c in store.calls] == [
        "run-xyz/figures/fig-001.png",
        "run-xyz/figures/fig-002.png",
    ]
    assert all(c[2] == "image/png" for c in store.calls)


def test_persist_figures_inline_without_store(monkeypatch):
    monkeypatch.setattr(ing, "_store", None)
    figures, images, png = _figs()

    result = ing._persist_figures(figures, images, "run-xyz")

    for fig in result:
        assert fig["image_b64"] == png
        assert "image_ref" not in fig


def test_persist_figures_skips_missing_bitmap(monkeypatch):
    monkeypatch.setattr(ing, "_store", _FakeStore())
    figures = [{"id": "fig-001", "page": 1}]  # metadata-only, no bitmap captured

    result = ing._persist_figures(figures, {}, "run-xyz")

    assert "image_ref" not in result[0]
    assert "image_b64" not in result[0]
