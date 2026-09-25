# ADR 0041 — Tool/MCP hardening and the sandbox trust boundary

- **Status:** accepted
- **Date:** 2026-09-24
- **Phase:** 6 of `docs/reviews/2026-09-24-full-app-review/REMEDIATION-PLAN.md`
- **Supersedes:** nothing
- **Depends on:** Phase 1 (tier images, allowlists), decision 0020 (elevated network)

## Context

Phase 6 opened on R8: *the destructive gate does not cross the container
boundary.* Two comments in the codebase made opposite claims about the
same fact:

- `sandbox_guard.py:181` — `smolcode` lives on the HOST and is **not**
  installed inside the sandbox Jupyter kernel.
- `tools/shell.py` / `tools/git.py` — the absolute imports are safe
  *because the parent package IS importable on PYTHONPATH* in the remote
  container.

Only one can be true. This ADR records the measurement, the decision, and
— just as importantly — an option that was considered, recommended, and
then found to be impossible.

## The measurement

Once the tier images built at all (see "the build that was broken" below),
the question became answerable instead of theoretical:

```
$ docker run --rm smolcode:restricted python -c "import smolcode.destructive"
ModuleNotFoundError: No module named 'smolcode'

$ docker run --rm smolcode:restricted pip list
ipykernel, jupyter_client, jupyter_core, jupyter-kernel-gateway, pytest, ruff
  -- no smolcode
```

So `sandbox_guard.py` was right and the `shell.py`/`git.py` rationale was
wrong. The consequence is worse than a bypass: smolagents serialises tool
source into the container, so the gate's import raises `ImportError` there
and `run` / `git_push` are **broken** under the docker executor, not merely
unguarded. Pinned by `test_container_gate_phase6.py`.

## Option (a) — move the gate host-side — is NOT IMPLEMENTABLE

The plan offered three options. Option (a), "the gate logic runs on the
host", was recommended and later withdrawn, because it cannot be built.
That withdrawal is part of this ADR so the reasoning is not lost.

Under `CodeAgent` + `DockerExecutor`, model-written code calls tools
**by name, inside the container**. The host hands the tool source over
once, via `send_tools`, and never observes an individual call. There is
therefore no host-side hook at which a per-call gate could run. Evidence:

1. `test_bind_roundtrip.py:3-8` — *"smolagents' Docker executor
   serialises a Tool by capturing the class source via
   `instance_to_source`, then on the remote side calls the class with NO
   arguments."*
2. `sandbox_guard.GuardedExecutor.send_tools()` exists solely to
   intercept that handoff.
3. `tools/git.py` module docstring — policy is inlined *"so the source is
   self-contained for the Docker executor."*
4. Live: smolagents' validator rejected Phase 6 code with
   `forward: Name '_clip' is undefined` and
   `Complex attributes should be defined in __init__: max_output_bytes`,
   both raised from the serialisation path.

The same fact makes an in-container `SessionState.confirm_callback`
unreachable: the approval UI is host-side, so a tool executing in the
container cannot prompt a human even if the import were repaired.

## Decision

**Option (b): inline the gate so the tool source is self-contained.**

The host remains the sole authority for policy. `build_tools` computes a
`destructive_policy` and `bind_attrs` bakes it into the tool as a class
attribute, so the container carries **no policy code and no host
imports** — only a mechanical enforcement copy. The `run` classifier is
duplicated inline because it depends on the call arguments, which the
container is the first place to see.

`destructive_policy == "allow"` is the only value that permits a
destructive call. Everything else, including the default, blocks. The
gate therefore **fails closed**.

Option (c) — installing `smolcode` into the tier images — was rejected: it
enlarges every image and makes the whole package importable by
model-written code, for no security gain that (b) does not already give.

## Consequences

- `run` and `git_push` work again under the docker executor.
- The classifier now exists twice. `TestGateDoesNotDrift` runs one case
  table through **both** implementations and requires identical verdicts;
  this is not ceremony — it caught a wrong expectation in the first draft
  of the table (`aws` is destructive for *every* invocation, not only
  delete-ish subcommands).
- **Per-call interactive approval is not available to an in-container
  tool.** A session that has been auto-approved binds `"allow"`;
  otherwise destructive calls are refused. This is a real behavioural
  limitation, not an oversight, and it is the price of option (b).
- Detection of the regression is by AST, not string matching: these tools
  carry long comments *quoting* the old imports and the error they
  produced, so `"import smolcode" in source` matches prose.

## The build that was broken

Independent of the decision, this phase found that **all three tier images
could not be built at all**. They sat on `python:3.12-bullseye`, whose
pinned `git` version `bullseye-security` has superseded, so
`apt-get install git` 404s. The sandboxed executor was therefore entirely
non-functional, and the docker-marked tests had been skipping because the
daemon was down, which concealed it. Fixed by moving to
`python:3.12-bookworm` and binding the vendor apt suite names to a
`DEBIAN_CODENAME` ARG so they cannot drift from the base again.

`full_access` still cannot complete: `apt.releases.hashicorp.com`
returns HTTP 404 for every path (verified from host and container, with
DNS resolving and the other three vendor repos returning 200). This is an
upstream outage and was deliberately **not** worked around — the only ways
to force a green build would be trusting an unverified key, dropping
`signed-by`, or removing terraform. Documented in-file.

## Also decided in this phase

- **§6.2 (H2/R10)** — flag-shaped operands are refused in all nine git
  tools. Live holes closed included `git diff --output=<path>` (arbitrary
  file write), `git clone --upload-pack=<cmd>` and `ext::` URLs (RCE).
  `git_push` validates *before* the destructive gate, because the gate
  denies every call in a session with no confirm callback and would have
  made the guard unreachable in exactly the configuration it exists to
  cover.
- **§6.3 (H3/R9)** — restricted containers get a second, read-only mount
  of the uploads subtree. The whole workspace stays `rw`; only uploads
  become `ro`. Verified in a real container, not just by inspecting the
  kwargs. Policy enforced only in the tool layer is policy the model can
  route around.
- **§6.3** — the `run` tool now clamps `timeout` to the tier ceiling,
  caps output at 1 MiB with a truncation marker, and binds `cwd` to the
  workspace. `build_shell_tools` had no `cwd` parameter at all, so every
  `run` call inherited the *server's* working directory.
- **§6.4 (R11/H4)** — the uploads store refuses to follow symlinks. Every
  path was handled with pathlib methods that follow links, so anyone able
  to create one entry in the uploads directory had an arbitrary-file
  read/delete/write primitive — and model-written code qualifies, because
  the workspace is bind-mounted rw.
