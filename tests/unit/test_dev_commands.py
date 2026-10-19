"""Development commands stay scoped and preserve local configuration and data."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_idp.dev import main


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("up", ["up", "--detach", "--build", "--wait", "--wait-timeout", "300"]),
        ("down", ["down", "--remove-orphans", "--timeout", "35"]),
        ("status", ["ps", "--all"]),
        ("check", ["config", "--quiet"]),
        ("restart", ["restart", "--timeout", "35", "api", "worker"]),
        ("logs", ["logs", "--tail", "100"]),
    ],
)
def test_commands_are_project_scoped_and_non_destructive(tmp_path, monkeypatch, action, expected):
    (tmp_path / ".env.example").write_text("APP_ENV=development\n")
    calls = []
    monkeypatch.setattr("ai_idp.dev.shutil.which", lambda _: "docker")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("ai_idp.dev.subprocess.run", run)
    assert main(tmp_path, project="test-core", url="http://localhost", argv=[action]) == 0
    command, kwargs = calls[0]
    assert command[:4] == ["docker", "compose", "--project-name", "test-core"]
    assert command[command.index("--file") + 1] == str(tmp_path / "compose.dev.yaml")
    assert command[-len(expected) :] == expected
    assert kwargs["cwd"] == tmp_path
    assert "--volumes" not in command
    assert (tmp_path / ".env").read_text() == "APP_ENV=development\n"


def test_failure_preserves_env_and_exit_code(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("LOCAL_SETTING=keep\n")
    monkeypatch.setattr("ai_idp.dev.shutil.which", lambda _: "docker")
    monkeypatch.setattr(
        "ai_idp.dev.subprocess.run", lambda *a, **k: subprocess.CompletedProcess(a[0], 7)
    )
    assert main(tmp_path, project="test", url="http://localhost", argv=["up"]) == 7
    assert env_file.read_text() == "LOCAL_SETTING=keep\n"


def test_missing_docker_does_not_change_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_idp.dev.shutil.which", lambda _: None)
    assert main(tmp_path, project="test", url="http://localhost", argv=["up"]) == 1
    assert not (tmp_path / ".env").exists()


def test_worker_readiness_rejects_unmigrated_database(tmp_path, monkeypatch):
    from ai_idp.adapters.outbound.persistence.database import build_engine, init_db_schema
    from ai_idp.workers import healthcheck

    url = f"sqlite:///{(tmp_path / 'worker.sqlite3').as_posix()}"
    monkeypatch.setattr(healthcheck, "get_settings", lambda: SimpleNamespace(database_url=url))
    assert healthcheck.main() == 1
    engine = build_engine(url)
    try:
        init_db_schema(engine)
        assert healthcheck.main() == 0
    finally:
        engine.dispose()
