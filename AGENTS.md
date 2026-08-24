# AGENTS.md

## Repository Structure
- **Package location**: `smolagents/` subdirectory (main code in `src/smolagents/`)
- **Python**: 3.10+
- **Main entrypoint**: `src/smolagents/agents.py` (~1000 lines)

## Developer Commands
```bash
make quality   # lint + format check (ruff)
make style     # auto-fix lint + format
make test      # pytest ./tests/
pip install -e ".[dev]"  # install with dev deps
```

**Important**: Run `make quality` before committing (quality → test order).

## Code Quality
- **Linter/Formatter**: `ruff` (line-length: 119)
- **Lint targets**: `examples src tests`
- **CI**: Runs `ruff check` and `ruff format --check` on PRs

## Key Source Files
| File | Purpose |
|------|---------|
| `src/smolagents/agents.py` | `CodeAgent`, `ToolCallingAgent` |
| `src/smolagents/models.py` | `InferenceClientModel`, `LiteLLMModel` |
| `src/smolagents/tools.py` | `Tool` base class, `ToolCollection` |
| `src/smolagents/local_python_executor.py` | **NOT a security sandbox** |
| `src/smolagents/cli.py` | `smolagent` CLI |
| `src/smolagents/gradio_ui.py` | GradioUI |

## Optional Dependencies
```bash
pip install "smolagents[extra]"  # extras: toolkit, litellm, transformers, telemetry, mcp, vision
```

## CLI Commands
```bash
smolagent "task" --model-type InferenceClientModel --model-id Qwen/Qwen2.5-32B --tools web_search
webagent "browser task" --model-type LiteLLMModel --model-id gpt-4o
```

## Testing
- **Framework**: pytest
- **Install**: `pip install -e ".[test]"`
- **Run**: `pytest ./tests/`
- **Addopts**: `-sv --durations=0` (verbose, show durations)

## Documentation
- Source: `docs/source/en/` (English), `docs/source/{lang}/` (translations)
- Build: `doc-builder build smolagents docs/source/en/ --build_dir ~/tmp/test-build`
- **Arabic docs**: `docs/source/ar/` (22 files, see `glossary.md`)

## Security
`LocalPythonExecutor` is **NOT a security sandbox**. Use E2B, Blaxel, Modal, or Docker for untrusted code.

## Contributing
- Follow OOP principles, be Pythonic
- Write unit tests for new functionality
- See `CONTRIBUTING.md`

## Agent Workflow

### Edit Tool Workflow

When multiple edits are needed on the **same file** (or across files) in sequence:
- Batch them into **parallel `edit` tool calls in a single message** instead of one call per turn.
- Only sequence edits when later edits depend on earlier ones (e.g., line shifts, shared context).
- A `read` of the file is still required before any `edit` batch — do it once, then issue all edits together.
- Verify `oldString` uniqueness across the batch to avoid collisions.

### Research Workflow

To avoid reinventing, catch deprecated APIs, and build a cumulative knowledge base across sessions, follow these rules **before** any new feature and **after** any completed phase.

#### Trigger tiers

| Tier | When | Action | Doc required? |
|---|---|---|---|
| **1 — Trivial lookup** | Single API name, syntax check, version pin | Call `webfetch` directly from main session | No (or one-line inline note) |
| **2 — New feature / non-trivial change** | New module, new library, new API surface, new agent flow | Spawn **one** sub-agent in research mode (see prompt skeleton below) | Yes → `research_doc/<feature>.md` |
| **3 — Multi-library comparison or architecture choice** | Choosing between 2+ libraries; pick a state-mgmt pattern, pick a DI approach | Spawn **one** researcher sub-agent with explicit trade-off table requirement | Yes → `research_doc/decisions/<topic>.md` |

#### Source priority (Python / HuggingFace ecosystem)

1. `pypi.org` package page, `docs.python.org`, PEP index
2. HuggingFace Hub docs, `transformers` docs, `litellm` docs, `gradio` docs
3. Project's own GitHub releases + changelog
4. **Curated blogs (allowed as secondary):** HuggingFace blog, Real Python, PyCoder's, Roman Elizarov (when relevant), official library blogs
5. Stack Overflow only as a sanity check — never as primary source

#### Sub-agent prompt skeleton (Tier 2 & 3)

When delegating to a researcher sub-agent, the prompt **must** include:

- The exact question
- The 2–5 official URLs to start from (PyPI, official docs, project GitHub)
- The required output structure (matching the doc template below)
- The constraint: **"Do not modify any code. Return findings only."**

#### Validation after each phase

1. `make quality` — ruff check + format check (matches existing CI)
2. `make test` — pytest run
3. Spot-check changed files against current docs for **deprecated APIs only** (don't re-research the whole feature)
4. If an outdated approach is found, write `research_doc/overrides/<topic>.md` and link from the original doc

#### Folder layout

```
research_doc/
├── README.md            ← index + tier rules + template (canonical source)
├── <feature>.md         ← tier-2 research
├── overrides/
│   └── <topic>.md       ← mid-flight corrections to a prior doc
└── decisions/
    └── <comparison>.md  ← tier-3 architecture / library choices
```

#### Document template — `research_doc/<topic>.md`

```markdown
# <Topic>

**Date:** YYYY-MM-DD
**Trigger:** <feature | phase | question>
**Sources:** (list with URLs)
**Status:** active | superseded

## Question
<What we needed to learn>

## Findings
- ...

## Decision
<What we chose and why>

## Code Impact
<Files changed + line refs, e.g. src/smolagents/foo.py:42>

## References
- ...
```

#### Document lifecycle

- Every doc must have a `Status:` line. `active` is the default.
- If a doc is invalidated by later research, **do not delete it**. Mark it `superseded` and add a `## Superseded by` link to the new doc.
- Tier-3 decision docs are append-only once written.