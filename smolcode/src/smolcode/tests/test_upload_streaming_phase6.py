"""Plan 6.4 #2 (R14): the upload endpoint must not buffer an unbounded body.

The defect is worse than "it buffers". `await file.read()` pulls the whole
upload into memory BEFORE the size cap is consulted, because the cap lives
in UploadsStore.save() and runs afterwards. A client that sends a body far
larger than the limit makes the server allocate that body in RAM and only
then get told no. The cap was enforced and still did not prevent the
exhaustion, which is the definition of enforcing it in the wrong place.

These tests pin three things: the cap is consulted before the read, the
refusal is 413 (not a generic 400), and the message names the limit the
operator actually configured rather than a hardcoded 50 MB.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

LIMIT = 4096


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("SMOLCODE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMOLCODE_EXECUTOR", "local")
    monkeypatch.setenv("SMOLCODE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SMOLCODE_UPLOAD_MAX_BYTES", str(LIMIT))
    from smolcode.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


class TestOversizedUploadIsRefused:
    def test_over_the_limit_is_rejected(self, client):
        payload = b"x" * (LIMIT + 1)
        r = client.post("/api/uploads?tier=restricted", files={"file": ("big.txt", payload, "text/plain")})
        assert r.status_code == 413

    def test_the_refusal_names_the_configured_limit(self, client):
        # The old message would have said 50 MB even when the operator set
        # something else entirely, which is actively misleading in a 413.
        r = client.post(
            "/api/uploads?tier=restricted",
            files={"file": ("big.txt", b"x" * (LIMIT + 1), "text/plain")},
        )
        assert str(LIMIT) in r.json()["detail"]

    def test_just_under_the_limit_still_succeeds(self, client):
        # A cap that rejects legitimate uploads is not a cap, it is a bug.
        payload = b"y" * (LIMIT - 10)
        r = client.post("/api/uploads?tier=restricted", files={"file": ("ok.txt", payload, "text/plain")})
        assert r.status_code == 201
        assert r.json()["size"] == len(payload)

    def test_nothing_is_written_when_refused(self, client):
        client.post("/api/uploads?tier=restricted", files={"file": ("big.txt", b"x" * (LIMIT + 1), "text/plain")})
        assert client.get("/api/uploads").json()["uploads"] == []


class TestCapIsConsultedBeforeTheRead:
    def test_a_lying_content_length_cannot_bypass_the_cap(self, client):
        # There is no Content-Length shortcut to lean on: because the endpoint
        # takes UploadFile, Starlette has already parsed the body by the time
        # the handler runs, so a header check there would refuse nothing. The
        # chunked read is the control, and a client can send any header it
        # likes without affecting it.
        payload = b"z" * (LIMIT * 4)
        r = client.post(
            "/api/uploads?tier=restricted",
            files={"file": ("liar.txt", payload, "text/plain")},
            headers={"Content-Length": "1"},
        )
        assert r.status_code == 413

    def test_the_handler_does_not_use_unbounded_read(self):
        # Structural guard: an argument-less read() is the exact call that
        # caused this finding, and it is easy to reintroduce.
        #
        # Deliberately AST-based rather than a substring search. A substring
        # test matches the handler's own DOCSTRING, which explains this very
        # line -- an earlier version of this test failed for that reason.
        import ast
        import inspect
        import textwrap

        from smolcode.web import api

        tree = ast.parse(textwrap.dedent(inspect.getsource(api.upload_file)))
        bare = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute) or fn.attr != "read":
                continue
            if not node.args and not node.keywords:
                bare.append(node.lineno)
        assert not bare, "argument-less .read() at line(s): " + repr(bare)


class TestDocumentedLimitMatchesConfiguration:
    def test_config_reports_the_real_limit(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        assert r.json()["upload_max_bytes"] == LIMIT
