"""M1.2 + Phase 1 (decision 0025 §6.3) — config tests."""

from smolcode.config import (
    ConfigError,
    Project,
    as_dict,
    load_settings,
)


def test_defaults_resolve_when_no_env_set(_isolate_env):
    s = load_settings()
    assert s.provider == "opencode-go"
    assert s.model == "deepseek-v4-flash"
    assert s.executor == "docker"
    assert s.log_level == "INFO"
    assert s.litellm_proxy is None


def test_cli_overrides_win_over_env(_isolate_env, monkeypatch):
    monkeypatch.setenv("SMOLCODE_PROVIDER", "openai")
    monkeypatch.setenv("SMOLCODE_MODEL", "gpt-4o")
    s = load_settings(cli_overrides={"provider": "MiniMax", "model": "MiniMax-M3"})
    assert s.provider == "MiniMax"
    assert s.model == "MiniMax-M3"


def test_invalid_provider_raises(_isolate_env, monkeypatch):
    monkeypatch.setenv("SMOLCODE_PROVIDER", "not-a-provider")
    try:
        load_settings()
    except ConfigError as e:
        assert "unknown provider" in str(e)
    else:
        raise AssertionError("expected ConfigError")


def test_as_dict_round_trip(_isolate_env):
    s = load_settings()
    d = as_dict(s)
    assert d["provider"] == "opencode-go"
    assert d["tiers"]["restricted"]["network"] == "none"
    assert d["tiers"]["restricted"]["docker_image"] == "smolcode:restricted"


# --- Phase 1 (decision 0025 §6.3): Settings.projects ----------------------


class TestProjects:
    def test_default_projects_is_empty(self, _isolate_env):
        s = load_settings()
        assert s.projects == ()

    def test_project_name_only_resolves_under_workspace(self, _isolate_env, tmp_path, monkeypatch):
        # Default project root = <workspace>/<name>.
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha,beta")
        s = load_settings()
        assert len(s.projects) == 2
        names = [p.name for p in s.projects]
        assert names == ["alpha", "beta"]
        assert s.projects[0].root == (ws / "alpha").resolve()
        assert s.projects[1].root == (ws / "beta").resolve()

    def test_project_explicit_path(self, _isolate_env, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        ext = tmp_path / "external"
        ext.mkdir()
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha=" + str(ext))
        s = load_settings()
        assert len(s.projects) == 1
        assert s.projects[0].name == "alpha"
        assert s.projects[0].root == ext.resolve()

    def test_project_creates_dir_if_missing(self, _isolate_env, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha")
        load_settings()
        assert (ws / "alpha").is_dir()

    def test_project_invalid_name_raises(self, _isolate_env, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        # Spaces in names are not allowed.
        monkeypatch.setenv("SMOLCODE_PROJECTS", "bad name")
        try:
            load_settings()
        except ConfigError as e:
            assert "project" in str(e).lower()
        else:
            raise AssertionError("expected ConfigError")

    def test_project_explicit_missing_path_raises(self, _isolate_env, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        ghost = tmp_path / "does-not-exist"
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha=" + str(ghost))
        try:
            load_settings()
        except ConfigError as e:
            assert "project" in str(e).lower()
        else:
            raise AssertionError("expected ConfigError")

    def test_project_unique_names(self, _isolate_env, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha,alpha")
        try:
            load_settings()
        except ConfigError as e:
            assert "duplicate" in str(e).lower() or "unique" in str(e).lower()
        else:
            raise AssertionError("expected ConfigError")

    def test_with_overrides_preserves_projects(self, _isolate_env, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha")
        s = load_settings()
        s2 = s.with_overrides(provider="openai")
        assert len(s2.projects) == 1
        assert s2.projects[0].name == "alpha"

    def test_as_dict_includes_projects(self, _isolate_env, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        monkeypatch.setenv("SMOLCODE_WORKSPACE", str(ws))
        monkeypatch.setenv("SMOLCODE_PROJECTS", "alpha")
        s = load_settings()
        d = as_dict(s)
        assert "projects" in d
        assert len(d["projects"]) == 1
        assert d["projects"][0]["name"] == "alpha"
        assert d["projects"][0]["root"] == str((ws / "alpha").resolve())


def test_project_dataclass_equality_and_hash():
    # Project dataclass equality + hashability (used in tuple storage).
    from pathlib import Path

    p1 = Project("alpha", Path("/tmp/a"))
    p2 = Project("alpha", Path("/tmp/a"))
    p3 = Project("beta", Path("/tmp/a"))
    assert p1 == p2
    assert p1 != p3
    assert hash(p1) == hash(p2)
    # Tuple of Projects stores fine.
    t = (p1, p3)
    assert t[0] is p1
