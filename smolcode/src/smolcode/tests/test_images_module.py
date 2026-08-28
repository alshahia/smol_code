"""Phase 1 (C2): tier sandbox image lifecycle - unit tests.

No Docker required: client interactions use fakes so these run
everywhere (CI Job A). The docker-marked consistency tests live in
test_tier_images_docker.py and run only in CI Job B.
"""

from __future__ import annotations

import pytest

from smolcode.agents.base import _executor_kwargs_for
from smolcode.config import load_settings
from smolcode.images import (
    IMAGE_SRC_LABEL,
    ImageBuildError,
    ensure_tier_images,
    image_is_current,
    source_hash,
    tier_build_context,
)


@pytest.fixture
def docker_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "docker")
    s = load_settings()
    return s


# --- source hashing ----------------------------------------------------------


def test_source_hash_is_stable():
    h1 = source_hash("restricted")
    h2 = source_hash("restricted")
    assert h1 == h2
    assert len(h1) == 64


def test_source_hash_differs_per_tier():
    assert source_hash("restricted") != source_hash("elevated")
    assert source_hash("full_access") != source_hash("elevated")


def test_source_hash_changes_when_input_changes(tmp_path):
    ctx = tier_build_context()
    # Copy real inputs into a scratch context, then mutate.
    for name in ("restricted.Dockerfile",):
        (tmp_path / name).write_bytes((ctx / name).read_bytes())
    before = source_hash("restricted", context_dir=tmp_path)
    (tmp_path / "restricted.Dockerfile").write_text("# touched\n", encoding="utf-8")
    after = source_hash("restricted", context_dir=tmp_path)
    assert before != after


def test_source_hash_missing_input_raises(tmp_path):
    with pytest.raises(ImageBuildError, match="build input missing"):
        source_hash("restricted", context_dir=tmp_path)


def test_unknown_tier_rejected():
    with pytest.raises(ImageBuildError, match="unknown sandboxed tier"):
        source_hash("made_up")


# --- image currency -----------------------------------------------------------


class FakeImage:
    def __init__(self, labels=None):
        self.labels = labels or {}


class FakeImages:
    def __init__(self, store):
        self._store = store

    def get(self, tag):
        if tag not in self._store:
            raise KeyError(tag)
        return self._store[tag]


class FakeApi:
    """Mock docker.api.build().

    Real Docker always yields at least the terminal '}' chunk before
    closing. This fake mirrors that so the chunk_count==0 defence in
    ensure_tier_images does not raise spuriously. Pass chunks=[] to
    simulate the silent-empty-stream failure mode (production code
    raises ImageBuildError on that).

    on_complete(tag, src_hash) is invoked AFTER build() returns so the
    FakeClient can record the freshly-built image and satisfy the
    post-build image_is_current() check.
    """

    def __init__(self, calls, chunks=None, on_complete=None):
        self._calls = calls
        self._chunks = chunks if chunks is not None else [{"stream": ""}]
        self._on_complete = on_complete

    def build(self, **kwargs):
        self._calls.append(kwargs)
        if self._on_complete is not None:
            self._on_complete(kwargs.get("tag"), kwargs.get("labels", {}).get(IMAGE_SRC_LABEL))
        return iter(self._chunks)


class FakeClient:
    def __init__(self):
        self.store = {}
        self.build_calls = []
        self.images = FakeImages(self.store)
        # Wire record_built as the post-build hook so production code's
        # post-build image_is_current() check observes the freshly
        # built image (mirrors real Docker's behaviour).
        self.api = FakeApi(self.build_calls, on_complete=self.record_built)

    def record_built(self, tag, src_hash):
        """Simulate Docker writing a freshly-built image into the store.

        Production code (ensure_tier_images) verifies the image exists
        AND carries the expected source-hash label after every build;
        the fake mirrors that by recording the tag here.
        """
        self.store[tag] = FakeImage({IMAGE_SRC_LABEL: src_hash})


def test_image_is_current_true_on_matching_label(docker_settings):
    h = source_hash("restricted")
    c = FakeClient()
    c.store["smolcode:restricted"] = FakeImage({IMAGE_SRC_LABEL: h})
    assert image_is_current(c, "smolcode:restricted", h) is True


def test_image_is_current_false_on_stale_label(docker_settings):
    c = FakeClient()
    c.store["smolcode:restricted"] = FakeImage({IMAGE_SRC_LABEL: "deadbeef"})
    assert image_is_current(c, "smolcode:restricted", source_hash("restricted")) is False


def test_image_is_current_false_when_missing():
    c = FakeClient()
    assert image_is_current(c, "nope:none", "x") is False


# --- ensure_tier_images --------------------------------------------------------


def test_ensure_skips_current_and_reports_empty(docker_settings):
    c = FakeClient()
    for t in ("restricted", "elevated", "full_access"):
        tag = docker_settings.tiers[t].docker_image
        c.store[tag] = FakeImage({IMAGE_SRC_LABEL: source_hash(t)})
    built = ensure_tier_images(docker_settings, ["restricted", "elevated", "full_access"], docker_client=c)
    assert built == []
    assert c.build_calls == []


def test_ensure_builds_missing_image_with_label_and_tag(docker_settings):
    c = FakeClient()
    built = ensure_tier_images(docker_settings, ["restricted"], docker_client=c)
    assert built == ["smolcode:restricted"]
    assert len(c.build_calls) == 1
    kw = c.build_calls[0]
    assert kw["tag"] == "smolcode:restricted"
    assert kw["labels"][IMAGE_SRC_LABEL] == source_hash("restricted")
    assert kw["path"] == str(tier_build_context())


def test_ensure_builds_stale_image(docker_settings):
    c = FakeClient()
    c.store["smolcode:elevated"] = FakeImage({IMAGE_SRC_LABEL: "stale"})
    built = ensure_tier_images(docker_settings, ["elevated"], docker_client=c)
    assert built == ["smolcode:elevated"]


def test_ensure_unknown_tier_name_fails_closed(docker_settings):
    c = FakeClient()
    with pytest.raises(ImageBuildError, match="settings has no tier"):
        ensure_tier_images(docker_settings, ["phantom"], docker_client=c)


def test_ensure_fails_closed_on_empty_build_stream(docker_settings):
    """Regression: a build endpoint that yields zero stream chunks (HTTP
    5xx with empty body observed on Windows named-pipe transports via
    the Python SDK) used to silently claim success. ensure_tier_images
    must now raise ImageBuildError instead.
    """
    c = FakeClient()
    # Simulate the silent-failure mode: build() yields no chunks.
    c.api = FakeApi(c.build_calls, chunks=[], on_complete=c.record_built)
    with pytest.raises(ImageBuildError, match="no stream chunks"):
        ensure_tier_images(docker_settings, ["restricted"], docker_client=c)
    assert c.build_calls, "build() should still have been attempted"


def test_ensure_fails_closed_when_build_completed_but_image_missing(docker_settings):
    """Defence in depth: a build that streams OK but never produces an
    image (e.g. daemon accepted the request then crashed mid-build)
    must not be reported as success.
    """
    c = FakeClient()
    # No on_complete -> image is never recorded into the store.
    c.api = FakeApi(c.build_calls, chunks=[{"stream": "ok"}], on_complete=None)
    with pytest.raises(ImageBuildError, match="missing or does not carry"):
        ensure_tier_images(docker_settings, ["restricted"], docker_client=c)


# --- executor kwargs pinning ----------------------------------------------------


def test_executor_kwargs_disable_executor_side_builds(docker_settings):
    """C2 core regression: smolagents must never rebuild our images."""
    tier = docker_settings.tiers["restricted"]
    kw = _executor_kwargs_for("docker", tier, docker_settings)
    assert kw["image_name"] == "smolcode:restricted"
    assert kw["build_new_image"] is False
