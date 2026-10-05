"""Participant pause controls must stop exports without re-registering Codex."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tracing.codex import control
from tracing.codex.hooks import handlers
from tracing.codex.install import _write_env_file


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    (home / "arize-env.sh").write_text(
        'export ARIZE_TRACE_ENABLED=true\nexport ARIZE_USER_ID=participant\nexport PHOENIX_API_KEY="fake-secret"\n'
    )
    return home


def test_pause_and_resume_stop_and_restart_exports_without_reloading_hook(codex_home, monkeypatch, mock_collector):
    monkeypatch.setenv("PHOENIX_ENDPOINT", mock_collector["url"])
    monkeypatch.setenv("PHOENIX_PROJECT", "participant-control-test")
    payload = {
        "type": "agent-turn-complete",
        "thread-id": "synthetic-control-test",
        "turn-id": "turn",
        "input-messages": ["Synthetic pause verification"],
        "last-assistant-message": "Synthetic result",
    }
    monkeypatch.setattr(sys, "argv", ["notify", json.dumps(payload)])
    handlers.notify()
    assert len(mock_collector["received"]) == 1
    control.main(["off"])
    handlers.notify()
    assert len(mock_collector["received"]) == 1
    control.main(["on"])
    handlers.notify()
    assert len(mock_collector["received"]) == 2


def test_control_preserves_identity_credentials_and_other_settings(codex_home, capsys):
    path = codex_home / "arize-env.sh"
    original = path.read_text()
    control.main(["off"])
    assert path.read_text() == original.replace("ARIZE_TRACE_ENABLED=true", "ARIZE_TRACE_ENABLED=false")
    assert path.stat().st_mode & 0o777 == 0o600
    assert "fake-secret" not in capsys.readouterr().out


def test_status_does_not_rewrite_settings(codex_home, capsys):
    path = codex_home / "arize-env.sh"
    original = path.read_bytes()
    modified = path.stat().st_mtime_ns
    control.main(["status"])
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == modified
    assert "ON" in capsys.readouterr().out


def test_missing_install_does_not_create_settings(codex_home):
    path = codex_home / "arize-env.sh"
    path.unlink()
    with pytest.raises(SystemExit) as error:
        control.main(["off"])
    assert error.value.code == 1
    assert not path.exists()


def test_update_does_not_resume_paused_capture_or_remove_overrides(codex_home):
    path = codex_home / "arize-env.sh"
    control.main(["off"])
    _write_env_file(path, user_id="updated-participant")
    text = path.read_text()
    assert "ARIZE_TRACE_ENABLED=false" in text
    assert "ARIZE_USER_ID=updated-participant" in text
    assert 'PHOENIX_API_KEY="fake-secret"' in text


def test_last_setting_matches_hook_semantics():
    text = 'export ARIZE_TRACE_ENABLED=true\nARIZE_TRACE_ENABLED="false"\n'
    assert control.env_value(text, "ARIZE_TRACE_ENABLED") == "false"
    changed = control.replace_setting(text, "ARIZE_TRACE_ENABLED", "true")
    assert control.env_value(changed, "ARIZE_TRACE_ENABLED") == "true"


def test_installed_shell_commands_need_no_download_or_codex_restart(tmp_path):
    home = tmp_path / "home"
    profile = home / ".codex"
    profile.mkdir(parents=True)
    (profile / "arize-env.sh").write_text("export ARIZE_TRACE_ENABLED=true\n")
    bin_dir = home / ".arize/harness/venv/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ, HOME=str(home), CODEX_HOME=str(profile))
    for command, expected in (("pause", "OFF"), ("trace-status", "OFF"), ("resume", "ON")):
        result = subprocess.run(
            ["bash", str(root / "install.sh"), command, "codex"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "Codex trace export: " + expected in result.stdout
