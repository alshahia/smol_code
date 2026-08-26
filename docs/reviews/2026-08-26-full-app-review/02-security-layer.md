# Area Review — Security Layer (sandbox_guard / container / destructive / confirm / checkpoint / redact / audit / uploads / docker)

**Date:** 2026-08-26 · **Reviewer:** parallel review agent · **Status:** active
**Note:** condensed from the reviewer's verified closing summary; full markdown appendix pending. All headline claims were runtime/source-verified by that agent against vendored smolagents 1.26.0.

## Headline findings

1. **[CRITICAL → C2] Tier Dockerfiles are never passed to DockerExecutor** — no `dockerfile_content` anywhere in smolcode src; agents/base.py only sends image_name + container_run_kwargs. Vendored smolagents rebuilds its stock root-by-default image under tags like `smolcode:elevated` on every run when absent, so the non-root user, gosu, and the iptables/ip6tables ENTRYPOINT (M16 + decision 0034) are inert at runtime unless images are pre-built manually.
2. **[HIGH → H1] No network isolation for any tier** — no `network_mode=none` set anywhere; docs/security.md §3.1/§10 claim otherwise.
3. **[HIGH] M4.x destructive-confirm gate is dead under the default docker executor** — tools hoisted into container via send_tools see a default SessionState(tier="restricted", callback=None), so git_push/destructive runs execute with no prompt and no audit record. (Independent angle on consolidated C1.)
4. **[HIGH → H5] Audit hash chain restarts at genesis per AuditSink** while the CLI appends every run to one shared logs/audit.jsonl ⇒ legitimate multi-run logs always fail verify_chain.
5. **[HIGH] full_access.Dockerfile installs terraform/kubectl/google-cloud-cli/azure-cli from stock bullseye** ⇒ build fails (repos/keys missing).
6. **[HIGH → H4] UploadsStore follows symlinks** — an agent can plant a symlink via the rw-mounted workspace; host-side read/download then discloses arbitrary host files.

## Medium
- Upload buffered-before-cap DoS (whole body read before size enforcement).
- Redaction gaps vs docs claims.
- audit record() hash computation races outside the lock.
- UTF-8 script content passes the MIME allowlist filter.
- Destructive classifier first-arg-only misses `aws s3 rm` / `gcloud … delete` shapes.
- ip6tables rules block ICMPv6 NDP/PMTUD (can break container networking health).
- checkpoint stash mutates the worktree; a stash failure does not abort the run.
- Orchestrator local-executor mode runs model-written code directly on the host (by design, but not surfaced/warned at runtime).

## Low
- Log rotation cutoff uses log mtime rather than event timestamps.
- confirm.py contains a dead branch and orphan reader threads.
- Sandbox-guard regexes have known-benign miss shapes.
- Base images and gosu download unpinned/unchecksummed in Dockerfiles.
- litellm_config.yaml minor nits.

## Cross-reference
See `00-consolidated-report.md` C1/C2/H1/H4/H5 and `03-tools-agents.md` findings 3, 15 for overlapping evidence trails.
