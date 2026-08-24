"""Configuration for smolcode.

Resolution order (per docs/architecture.md 5.1):
    1. CLI flag (highest priority)
    2. Process env / shell export
    3. .env file (parent <repo>/.env loaded via python-dotenv, override=False)
    4. Dataclass default (lowest priority)

Smolcode refuses to start if SMOLCODE_WORKSPACE is unset AND the
default <repo>/workspace/ cannot be created. See docs/environment.md
section 11 for the parent .env loading rules.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# --- Provider keys -----------------------------------------------------------

# Explicit search list for the parent .env so we do not pick up the wrong file
# by accident on developer machines with multiple projects in CWD.
DEFAULT_DOTENV_SEARCH_PATHS = (
    Path.cwd() / ".env",
    Path(__file__).resolve().parents[2] / ".env",
    Path(__file__).resolve().parents[3] / ".env",
    Path.home() / ".env",
)


def load_dotenv_into_environ(search_paths=DEFAULT_DOTENV_SEARCH_PATHS):
    """Load the first existing .env from search_paths into os.environ.

    Shell env wins over .env (override=False). Returns the path loaded,
    or None if nothing matched.
    """
    for p in search_paths:
        if p.is_file():
            load_dotenv(dotenv_path=p, override=False)
            return p
    return None


# --- Tier + Settings dataclasses --------------------------------------------


# Phase 1 (decision 0025 §6.3): a Project is a named workspace root.
# Projects let the SPA switch between multiple working directories
# without restarting smolcode. Stored as a tuple on Settings so it
# behaves immutably like Tier. Equality + hash follow the Tier pattern
# so two Projects with the same name + root compare equal.
class Project:
    """A named project root (Phase 1, decision 0025 §6.3)."""

    __slots__ = ("name", "root")

    def __init__(self, name, root):
        if not isinstance(name, str) or not name:
            raise ConfigError("project name must be a non-empty string")
        # Project names are used as URL path segments and filesystem
        # directory names; reject anything that would either need
        # percent-encoding or fail the latter.
        if any(ch in name for ch in ("/", "\\", ",", "=", "..", ":")):
            raise ConfigError("invalid project name " + repr(name) + "; must not contain /, \\, ',', '=', ':' or '..'")
        if any(ch.isspace() for ch in name):
            raise ConfigError("invalid project name " + repr(name) + "; must not contain whitespace")
        self.name = name
        self.root = Path(root).resolve()

    def __repr__(self):
        return "Project(name=" + repr(self.name) + ", root=" + str(self.root) + ")"

    def __eq__(self, other):
        if not isinstance(other, Project):
            return NotImplemented
        return self.name == other.name and self.root == other.root

    def __hash__(self):
        return hash((self.name, str(self.root)))


class Tier:
    """A trust tier. See docs/architecture.md 5.1."""

    __slots__ = (
        "name",
        "imports",
        "commands",
        "paths",
        "network",
        "network_allowlist",
        "mcp_servers",
        "max_steps",
        "timeout_s",
        "docker_image",
        "uploads",
    )

    def __init__(
        self,
        name,
        imports,
        commands,
        paths,
        network,
        network_allowlist,
        mcp_servers,
        max_steps,
        timeout_s,
        docker_image,
        uploads="",
    ):
        self.name = name
        self.imports = tuple(imports)
        self.commands = tuple(commands)
        self.paths = tuple(paths)
        self.network = network
        self.network_allowlist = tuple(network_allowlist)
        self.mcp_servers = tuple(mcp_servers)
        self.max_steps = max_steps
        self.timeout_s = timeout_s
        self.docker_image = docker_image
        self.uploads = uploads

    def __repr__(self):
        return f"Tier(name={self.name!r}, max_steps={self.max_steps})"

    def __eq__(self, other):
        return (
            self.name == other.name
            and self.imports == other.imports
            and self.commands == other.commands
            and self.paths == other.paths
            and self.network == other.network
            and self.network_allowlist == other.network_allowlist
            and self.mcp_servers == other.mcp_servers
            and self.max_steps == other.max_steps
            and self.timeout_s == other.timeout_s
            and self.docker_image == other.docker_image
            and self.uploads == other.uploads
        )

    def __hash__(self):
        return hash(
            (
                self.name,
                self.imports,
                self.commands,
                self.paths,
                self.network,
                self.network_allowlist,
                self.mcp_servers,
                self.max_steps,
                self.timeout_s,
                self.docker_image,
                self.uploads,
            )
        )


class Settings:
    """Resolved configuration for one smolcode run."""

    __slots__ = (
        "workspace",
        "executor",
        "provider",
        "model",
        "litellm_proxy",
        "log_level",
        "tiers",
        # M8: uploads
        "uploads_dir",
        "upload_max_bytes",
        "upload_allowed_mime",
        # Phase 1 (decision 0025 §6.3): named project roots. When
        # non-empty, the SPA exposes a switcher; ``deps.get_active_project``
        # resolves the active one from ``?project=`` or the SPA's last
        # selection. When empty (legacy single-workspace mode), the
        # ``workspace`` path is the implicit project.
        "projects",
        # Phase 3 (decision 0025 sec 6.5 / Q5): per-provider per-model USD
        # cost rates as {provider: {model: [in_per_1k, out_per_1k, cache_per_1k]}}.
        # Loaded from SMOLCODE_COST_RATES (JSON env var). Empty dict means
        # "use model_catalog.DEFAULT_COST_RATES only".
        "cost_rates",
    )

    def __init__(
        self,
        workspace,
        executor,
        provider,
        model,
        litellm_proxy,
        log_level,
        tiers,
        uploads_dir=None,
        upload_max_bytes=None,
        upload_allowed_mime=None,
        projects=(),
        cost_rates=None,
    ):
        self.workspace = Path(workspace)
        self.executor = executor
        self.provider = provider
        self.model = model
        self.litellm_proxy = litellm_proxy
        self.log_level = log_level
        self.tiers = dict(tiers)
        # M8: uploads defaults resolved in load_settings(); here we just
        # record what was passed (None is OK for both tests and the
        # with_executor/with_overrides pass-through paths).
        self.uploads_dir = Path(uploads_dir) if uploads_dir is not None else None
        self.upload_max_bytes = upload_max_bytes
        self.upload_allowed_mime = upload_allowed_mime
        # Phase 1: tuple of Project. ``with_*`` helpers thread it through.
        self.projects = tuple(projects)
        # Phase 3: cost rates. ``None`` defaults to {} (use defaults only).
        self.cost_rates = dict(cost_rates) if cost_rates is not None else {}

    def with_executor(self, executor):
        """Return a new Settings with the executor swapped."""
        return Settings(
            workspace=self.workspace,
            executor=executor,
            provider=self.provider,
            model=self.model,
            litellm_proxy=self.litellm_proxy,
            log_level=self.log_level,
            tiers=self.tiers,
            uploads_dir=self.uploads_dir,
            upload_max_bytes=self.upload_max_bytes,
            upload_allowed_mime=self.upload_allowed_mime,
            projects=self.projects,
            cost_rates=self.cost_rates,
        )

    def with_overrides(self, provider=None, model=None, litellm_proxy=None, workspace=None):
        """Return a new Settings with the given overrides applied."""
        return Settings(
            workspace=workspace or self.workspace,
            executor=self.executor,
            provider=provider or self.provider,
            model=model or self.model,
            litellm_proxy=(litellm_proxy if litellm_proxy is not None else self.litellm_proxy),
            log_level=self.log_level,
            tiers=self.tiers,
            uploads_dir=self.uploads_dir,
            upload_max_bytes=self.upload_max_bytes,
            upload_allowed_mime=self.upload_allowed_mime,
            projects=self.projects,
            cost_rates=self.cost_rates,
        )

    def __repr__(self):
        return (
            f"Settings(workspace={self.workspace!r}, provider={self.provider!r}, "
            f"model={self.model!r}, executor={self.executor!r})"
        )


# Tier.network_allowlist semantics (M16, decision 0020):
#
#   - ()            -> no hosts allowed (paired with network="none" or
#                       network="restricted"); the elevated container
#                       will have a default-deny OUTPUT chain with
#                       loopback + Docker DNS only (no egress)
#   - tuple of strs -> allowed egress CIDRs (paired with network="restricted")
#                       e.g. ("140.82.112.0/24", "151.101.0.0/16")
#                       (M16: CHANGED from hostnames to CIDRs; the v1.0
#                        hostname form had no consumers and was never
#                        enforced, so this is a clean rename of
#                        semantics, not a breaking API change.)
#   - ("*",)        -> sentinel meaning "all hosts" (paired with
#                       network="open"). Used by the full_access tier.
#
# For the elevated tier, M16 enforces this list at the kernel level via
# iptables inside the container (see docker/iptables-init.sh and
# decision 0020). The Python-side helper `container.elevated_container_env`
# validates each CIDR via `ipaddress.ip_network(strict=False)` and
# raises ConfigError on the first malformed entry (fail-closed).
#
# IPv6 is NOT supported in the allowlist in M16 (v1.7); the elevated
# container drops all IPv6 OUTPUT. IPv6 support is a v1.8 candidate.


# --- Defaults ----------------------------------------------------------------


def _default_workspace():
    """Default workspace = <repo>/workspace/ (one level above src/smolcode)."""
    return Path(__file__).resolve().parents[3] / "workspace"


def _default_tiers():
    return {
        "restricted": Tier(
            name="restricted",
            imports=("json", "pathlib", "ast", "textwrap", "re", "typing", "dataclasses"),
            commands=("python", "pytest", "git", "ruff"),
            paths=(),
            network="none",
            network_allowlist=(),
            mcp_servers=(),
            max_steps=12,
            timeout_s=120.0,
            docker_image="smolcode:restricted",
            uploads="read",  # M8: restricted tier can read uploads but not modify/delete
        ),
        # Elevated: workspace + extra stdlib imports + a few extra
        # tools (pip, npm, curl, jq, make). No destructive git ops.
        # Network is "restricted" with an empty CIDR allowlist by
        # default (operators opt in by populating network_allowlist
        # with CIDRs). M16 (decision 0020) enforces the allowlist at
        # the kernel level inside the container via iptables -- see
        # smolcode/src/smolcode/docker/iptables-init.sh and
        # docs/decisions/0020-m16-iptables-enforcement.md.
        "elevated": Tier(
            name="elevated",
            imports=(
                "json",
                "pathlib",
                "ast",
                "textwrap",
                "re",
                "typing",
                "dataclasses",
                "collections",
                "itertools",
                "functools",
                "os",
                "sys",
                "tempfile",
                "hashlib",
                "shutil",
                "glob",
            ),
            commands=("python", "pytest", "git", "ruff", "pip", "npm", "node", "curl", "jq", "make"),
            paths=(),
            network="restricted",
            network_allowlist=(),
            mcp_servers=(),
            max_steps=20,
            timeout_s=180.0,
            docker_image="smolcode:elevated",
            uploads="readwrite",  # M8: elevated tier can modify/delete
        ),
        # Full access: opt-in only, per-run confirmation prompt is
        # enforced by cli.py BEFORE the agent is built (decision 0006).
        # Wider imports (I/O + process + concurrency + network +
        # crypto), wider commands (ssh, scp, rsync, docker, kubectl,
        # terraform, ansible, aws, gcloud, az CLIs), open network.
        "full_access": Tier(
            name="full_access",
            imports=(
                "json",
                "pathlib",
                "ast",
                "textwrap",
                "re",
                "typing",
                "dataclasses",
                "collections",
                "itertools",
                "functools",
                "os",
                "sys",
                "tempfile",
                "hashlib",
                "shutil",
                "glob",
                "subprocess",
                "threading",
                "multiprocessing",
                "asyncio",
                "socket",
                "http",
                "http.client",
                "urllib",
                "urllib.parse",
                "urllib.request",
                "ssl",
                "smtplib",
                "secrets",
                "base64",
                "sqlite3",
                "csv",
                "configparser",
                "xml",
                "xml.etree",
                "pickle",
                "ctypes",
            ),
            commands=(
                "python",
                "pytest",
                "git",
                "ruff",
                "pip",
                "npm",
                "node",
                "curl",
                "jq",
                "make",
                "ssh",
                "scp",
                "rsync",
                "docker",
                "kubectl",
                "terraform",
                "ansible",
                "aws",
                "gcloud",
                "az",
            ),
            paths=(),
            network="open",
            network_allowlist=("*",),
            mcp_servers=(),
            max_steps=40,
            timeout_s=300.0,
            docker_image="smolcode:full_access",
            uploads="readwrite",  # M8: full_access can modify/delete
        ),
    }


# --- Public loader -----------------------------------------------------------


class ConfigError(RuntimeError):
    """Raised when configuration cannot be resolved."""


# Phase 1 (decision 0025 §6.3): parse the SMOLCODE_PROJECTS env var into a
# tuple of Project. Format:
#
#     name1,name2,name3           -> each rooted under <workspace>/<name>
#     name1=path1,name2=path2     -> explicit root; relative paths resolve
#                                     against <workspace>; absolute paths
#                                     must already exist.
#
# Bare names auto-create the directory on first load so the SPA can
# switch into a freshly-named project without an extra step. Names with
# ``=`` must use the ``name=path`` form.
def _parse_cost_rates(raw):
    """Parse the SMOLCODE_COST_RATES JSON env var.

    Shape: {"provider": {"model": [in_per_1k, out_per_1k, cache_per_1k]}}
    Empty -> {}. Invalid JSON or wrong shape -> ConfigError (fail-closed,
    matches the decision 0025 Q5 contract + decision 0025 sec 6.5).
    """
    if not raw:
        return {}
    import json as _json

    try:
        parsed = _json.loads(raw)
    except _json.JSONDecodeError as e:
        raise ConfigError("SMOLCODE_COST_RATES is not valid JSON: " + str(e)) from e
    if not isinstance(parsed, dict):
        raise ConfigError("SMOLCODE_COST_RATES must be a JSON object")
    for prov, models in parsed.items():
        if not isinstance(models, dict):
            raise ConfigError("SMOLCODE_COST_RATES[" + repr(prov) + "] must be a dict")
        for model, rates in models.items():
            if not isinstance(rates, (list, tuple)) or len(rates) != 3:
                raise ConfigError(
                    "SMOLCODE_COST_RATES[" + repr(prov) + "][" + repr(model) + "] must be [in, out, cache]"
                )
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in rates):
                raise ConfigError("SMOLCODE_COST_RATES[" + repr(prov) + "][" + repr(model) + "] rates must be numeric")
    return parsed


def _parse_projects(raw, workspace):
    if not raw:
        return ()
    out = []
    seen = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            name, path_str = entry.split("=", 1)
            name = name.strip()
            path_str = path_str.strip()
        else:
            name = entry
            path_str = entry
        p = Path(path_str)
        if not p.is_absolute():
            p = workspace / p
        # Bare names auto-create; explicit paths must already exist.
        if "=" in entry:
            if not p.exists():
                raise ConfigError("project " + repr(name) + ": root " + str(p) + " does not exist")
        else:
            p.mkdir(parents=True, exist_ok=True)
        if name in seen:
            raise ConfigError("project names must be unique; duplicate " + repr(name))
        seen.add(name)
        out.append(Project(name, p))
    return tuple(out)


def load_settings(cli_overrides=None, dotenv_paths=None):
    """Resolve settings from CLI overrides + env + dotenv + defaults.

    CLI > env > .env > defaults.
    """
    search = tuple(dotenv_paths) if dotenv_paths is not None else DEFAULT_DOTENV_SEARCH_PATHS
    load_dotenv_into_environ(search)

    raw_ws = os.environ.get("SMOLCODE_WORKSPACE") or ""
    workspace = Path(raw_ws).expanduser() if raw_ws else _default_workspace()
    workspace = workspace.resolve()
    if not workspace.exists():
        try:
            workspace.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigError(f"Workspace path {str(workspace)!r} does not exist and cannot be created: {e}") from e
    if not workspace.is_dir():
        raise ConfigError(f"Workspace path {str(workspace)!r} is not a directory.")

    # M8: uploads_dir, upload_max_bytes, upload_allowed_mime resolution.
    # Default uploads_dir = <workspace>/.smolcode/uploads/ (hidden).
    # Override via SMOLCODE_UPLOAD_DIR.
    uploads_dir_env = os.environ.get("SMOLCODE_UPLOAD_DIR")
    if uploads_dir_env:
        uploads_dir = Path(uploads_dir_env).expanduser().resolve()
    else:
        uploads_dir = (workspace / ".smolcode" / "uploads").resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Default size cap: 50 MB. Override via SMOLCODE_UPLOAD_MAX_BYTES.
    raw_max = os.environ.get("SMOLCODE_UPLOAD_MAX_BYTES", "").strip()
    if raw_max:
        try:
            upload_max_bytes = int(raw_max)
        except ValueError as e:
            raise ConfigError(f"SMOLCODE_UPLOAD_MAX_BYTES must be an integer, got {raw_max!r}") from e
    else:
        from .uploads import DEFAULT_MAX_BYTES

        upload_max_bytes = DEFAULT_MAX_BYTES
    if upload_max_bytes <= 0:
        raise ConfigError(f"SMOLCODE_UPLOAD_MAX_BYTES must be > 0, got {upload_max_bytes}")

    # Allowed MIME: comma-separated override; empty = use default.
    raw_mime = os.environ.get("SMOLCODE_UPLOAD_ALLOWED_MIME", "").strip()
    if raw_mime:
        upload_allowed_mime = tuple(m.strip() for m in raw_mime.split(",") if m.strip())
    else:
        from .uploads import DEFAULT_ALLOWED_MIME

        upload_allowed_mime = DEFAULT_ALLOWED_MIME

    settings = Settings(
        workspace=workspace,
        executor=os.environ.get("SMOLCODE_EXECUTOR", "docker"),
        provider=os.environ.get("SMOLCODE_PROVIDER", "opencode-go"),
        model=os.environ.get("SMOLCODE_MODEL", "deepseek-v4-flash"),
        litellm_proxy=os.environ.get("SMOLCODE_LITELLM_PROXY") or None,
        log_level=os.environ.get("SMOLCODE_LOG_LEVEL", "INFO"),
        tiers=_default_tiers(),
        uploads_dir=uploads_dir,
        upload_max_bytes=upload_max_bytes,
        upload_allowed_mime=upload_allowed_mime,
        projects=_parse_projects(os.environ.get("SMOLCODE_PROJECTS", ""), workspace),
        cost_rates=_parse_cost_rates(os.environ.get("SMOLCODE_COST_RATES", "")),
    )

    if cli_overrides:
        settings = settings.with_overrides(
            provider=cli_overrides.get("provider"),
            model=cli_overrides.get("model"),
            litellm_proxy=cli_overrides.get("litellm_proxy"),
            workspace=cli_overrides.get("workspace"),
        )

    if settings.executor not in ("docker", "local"):
        raise ConfigError(f"executor must be docker or local, got {settings.executor!r}")
    if settings.provider not in ("opencode-go", "MiniMax", "openai", "anthropic", "custom"):
        raise ConfigError(f"unknown provider {settings.provider!r}")
    if settings.log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ConfigError(f"unknown log level {settings.log_level!r}")

    return settings


def as_dict(s):
    """Settings -> plain dict for YAML printing. Paths become str."""
    out = {
        "workspace": str(s.workspace),
        "executor": s.executor,
        "provider": s.provider,
        "model": s.model,
        "litellm_proxy": s.litellm_proxy,
        "log_level": s.log_level,
        "tiers": {
            name: {
                "imports": list(t.imports),
                "commands": list(t.commands),
                "network": t.network,
                "network_allowlist": list(t.network_allowlist),
                "mcp_servers": list(t.mcp_servers),
                "max_steps": t.max_steps,
                "timeout_s": t.timeout_s,
                "docker_image": t.docker_image,
                "uploads": t.uploads,
            }
            for name, t in s.tiers.items()
        },
    }
    # M8: include uploads settings only when resolved (None is OK for tests).
    if s.uploads_dir is not None:
        out["uploads_dir"] = str(s.uploads_dir)
    if s.upload_max_bytes is not None:
        out["upload_max_bytes"] = s.upload_max_bytes
    if s.upload_allowed_mime is not None:
        out["upload_allowed_mime"] = list(s.upload_allowed_mime)
    # Phase 1 (decision 0025 §6.3): list of project roots. Empty tuple
    # means legacy mode (single implicit project == ``workspace``).
    out["projects"] = [{"name": p.name, "root": str(p.root)} for p in s.projects]
    # Phase 3 (decision 0025 sec 6.5 / Q5): only surface overrides (defaults
    # are owned by model_catalog.DEFAULT_COST_RATES, not duplicated here).
    if s.cost_rates:
        out["cost_rates"] = s.cost_rates
    return out
