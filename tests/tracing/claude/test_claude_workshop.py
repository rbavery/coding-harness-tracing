"""Workshop onboarding, routing, and live capture controls for Claude Code."""

import io
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import config, constants, setup
from core.setup import workshop
from core.tracing_control import control_path, read_control
from tracing.claude_code import control, install
from tracing.claude_code.hooks import adapter, handlers


@pytest.fixture
def workshop_home(tmp_path, tmp_harness_dir, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    for name, suffix in (
        ("INSTALL_DIR", ""),
        ("CONFIG_FILE", "config.json"),
        ("VENV_DIR", "venv"),
        ("BIN_DIR", "bin"),
        ("RUN_DIR", "run"),
        ("LOG_DIR", "logs"),
        ("STATE_DIR", "state"),
    ):
        monkeypatch.setattr(setup, name, tmp_harness_dir / suffix)
    config_path = tmp_harness_dir / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", config_path)
    state_dir = tmp_harness_dir / "state" / "claude-code"
    monkeypatch.setattr(adapter, "STATE_DIR", state_dir)
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir()
    settings_file.write_text(json.dumps({"env": {"KEEP_ME": "value"}, "permissions": {"defaultMode": "plan"}}))
    monkeypatch.setattr(install, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(workshop, "getpass", lambda _: "synthetic-event-key")
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    return config_path, settings_file


def _hook(monkeypatch, function, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    function()


def test_workshop_install_only_prompts_for_key_and_capture(workshop_home, monkeypatch, capsys):
    config_path, settings_file = workshop_home
    questions = []
    monkeypatch.setattr(workshop, "getpass", lambda prompt: questions.append(prompt) or "synthetic-event-key")
    monkeypatch.setattr("builtins.input", lambda prompt: questions.append(prompt) or "no")
    monkeypatch.setenv("PHOENIX_API_KEY", "stale-local-key")
    install.cli_main(["install.py", "install", "--workshop"])
    assert len(questions) == 2
    entry = config.load_config()["harnesses"]["claude-code"]
    assert entry["profile"] == constants.WORKSHOP_PROFILE
    assert entry["api_key"] == "synthetic-event-key"
    assert entry["endpoint"] == constants.WORKSHOP_ENDPOINT
    assert entry["project_name"] == constants.WORKSHOP_PROJECT
    assert entry["user_id"].startswith("participant-") and "@" not in entry["user_id"]
    assert not any(entry["logging"].values())
    settings = json.loads(settings_file.read_text())
    assert settings["env"]["KEEP_ME"] == "value"
    assert settings["permissions"] == {"defaultMode": "plan"}
    assert settings["env"]["PHOENIX_TELEMETRY_ENABLED"] == "false"
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert control_path("claude-code").stat().st_mode & 0o777 == 0o600
    assert "synthetic-event-key" not in capsys.readouterr().out


def test_reinstall_preserves_identity_consent_pause_and_other_registrations(workshop_home, monkeypatch):
    config_path, settings_file = workshop_home
    monkeypatch.setattr("builtins.input", lambda _: "no")
    install.install(workshop=True)
    original = config.load_config()
    control.main(["off"])
    paused = read_control("claude-code")
    settings = json.loads(settings_file.read_text())
    settings["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "unrelated-notifier"}]})
    settings_file.write_text(json.dumps(settings))
    config_data = config.load_config()
    config_data["harnesses"]["codex"] = {"target": "phoenix", "api_key": "preserve-codex"}
    config.save_config(config_data)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Unexpected prompt"))
    monkeypatch.setattr(workshop, "getpass", lambda _: pytest.fail("Unexpected key prompt"))
    install.install()
    assert config.load_config()["harnesses"]["claude-code"] == original["harnesses"]["claude-code"]
    assert read_control("claude-code") == paused
    settings = json.loads(settings_file.read_text())
    commands = [h["command"] for entry in settings["hooks"]["Stop"] for h in entry["hooks"]]
    assert len(commands) == len(set(commands))
    install.uninstall()
    settings = json.loads(settings_file.read_text())
    assert settings["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "unrelated-notifier"}]}]
    assert settings["env"] == {"KEEP_ME": "value"}
    assert config.load_config()["harnesses"]["codex"]["api_key"] == "preserve-codex"
    assert not control_path("claude-code").exists()


@pytest.mark.parametrize("old_target", ["arize", "phoenix"])
def test_existing_backend_replaced_without_reusing_its_key(workshop_home, old_target):
    config.save_config(
        {
            "harnesses": {
                "claude-code": {"target": old_target, "endpoint": "http://localhost:6006", "api_key": "stale-key"}
            }
        }
    )
    install.install(workshop=True)
    assert config.load_config()["harnesses"]["claude-code"]["api_key"] == "synthetic-event-key"


def test_claude_capture_choice_does_not_change_existing_codex_logging(workshop_home, monkeypatch):
    logging = dict.fromkeys(("prompts", "tool_details", "tool_content"), True)
    codex = {"profile": constants.WORKSHOP_PROFILE, "api_key": "codex-key", "logging": logging}
    config.save_config({"logging": logging, "harnesses": {"codex": codex}})
    monkeypatch.setattr("builtins.input", lambda _: "no")
    install.install(workshop=True)
    saved = config.load_config()
    assert saved["harnesses"]["codex"] == codex
    assert saved["logging"] == logging
    assert not any(saved["harnesses"]["claude-code"]["logging"].values())


@pytest.mark.parametrize("bad_settings", ["{broken", "[]", '{"env": []}', '{"hooks": {"Stop": {}}}'])
def test_malformed_settings_are_preserved(workshop_home, bad_settings):
    config_path, settings_file = workshop_home
    settings_file.write_text(bad_settings)
    with pytest.raises(ValueError):
        install.install(workshop=True)
    assert settings_file.read_text() == bad_settings
    assert not config_path.exists()


def test_declined_content_and_anonymous_identity_ignore_inherited_env(workshop_home, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "no")
    install.install(workshop=True)
    for name, value in {
        "ARIZE_API_KEY": "stale-ax-key",
        "ARIZE_SPACE_ID": "stale-space",
        "PHOENIX_ENDPOINT": "http://localhost:6006",
        "PHOENIX_API_KEY": "stale-local-key",
        "PHOENIX_PROJECT": "stale-project",
        "ARIZE_USER_ID": "private@example.com",
        "ARIZE_LOG_PROMPTS": "true",
        "ARIZE_LOG_TOOL_DETAILS": "true",
        "ARIZE_LOG_TOOL_CONTENT": "true",
    }.items():
        monkeypatch.setenv(name, value)
    requests = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: requests.append(request) or nullcontext(SimpleNamespace(status=200)),
    )
    payload = {"session_id": "synthetic-session", "prompt": "PRIVATE_PROMPT"}
    _hook(monkeypatch, handlers.user_prompt_submit, payload)
    _hook(monkeypatch, handlers.stop, {**payload, "last_assistant_message": "PRIVATE_ANSWER"})
    assert requests
    assert all(r.full_url == constants.WORKSHOP_ENDPOINT + "/v1/traces" for r in requests)
    assert all(r.get_header("Authorization") == "Bearer synthetic-event-key" for r in requests)
    body = b"".join(r.data for r in requests)
    for marker in (b"PRIVATE_PROMPT", b"PRIVATE_ANSWER", b"private@example.com", b"stale-project"):
        assert marker not in body
    assert config.load_config()["harnesses"]["claude-code"]["user_id"].encode() in body
    saved = config.load_config()
    del saved["harnesses"]["claude-code"]["api_key"]
    config.save_config(saved)
    count = len(requests)
    _hook(monkeypatch, handlers.user_prompt_submit, payload)
    _hook(monkeypatch, handlers.stop, {**payload, "last_assistant_message": "not exported"})
    assert len(requests) == count


@pytest.mark.parametrize("hooks_during_pause", [True, False])
def test_pause_resume_never_backfills_interrupted_or_paused_transcript(workshop_home, monkeypatch, hooks_during_pause):
    install.install(workshop=True)
    _, settings_file = workshop_home
    transcript = settings_file.parent / "synthetic-transcript.jsonl"
    transcript.write_text("")
    payload = {"session_id": "synthetic-pause", "transcript_path": str(transcript)}
    sent = []
    monkeypatch.setattr(handlers, "_send_span", lambda span: sent.append(span) or True)
    _hook(monkeypatch, handlers.user_prompt_submit, {**payload, "prompt": "interrupted prompt"})
    state = adapter.resolve_session(payload)
    state.set("pending_subagents", '{"old-agent": {"agent_id": "old-agent"}}')
    control.main(["off"])
    _hook(monkeypatch, handlers.stop, {**payload, "last_assistant_message": "INTERRUPTED_PRIVATE"})
    if hooks_during_pause:
        _hook(monkeypatch, handlers.user_prompt_submit, {**payload, "prompt": "PAUSED_PRIVATE"})
        _hook(monkeypatch, handlers.stop, {**payload, "last_assistant_message": "PAUSED_PRIVATE"})
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "PAUSED_PRIVATE"}]},
            }
        )
        + "\n"
    )
    assert not sent
    control.main(["on"])
    # Late completion of a turn started before resume must also be ignored.
    _hook(monkeypatch, handlers.stop, {**payload, "last_assistant_message": "PAUSED_PRIVATE"})
    assert not sent
    _hook(monkeypatch, handlers.user_prompt_submit, {**payload, "prompt": "RESUMED_PUBLIC"})
    assert state.get("pending_subagents") is None
    with transcript.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "RESUMED_PUBLIC"}]},
                }
            )
            + "\n"
        )
    _hook(monkeypatch, handlers.stop, {**payload, "last_assistant_message": "RESUMED_PUBLIC"})
    assert sent
    exported = json.dumps(sent)
    assert "RESUMED_PUBLIC" in exported
    assert "PAUSED_PRIVATE" not in exported and "INTERRUPTED_PRIVATE" not in exported


def test_pause_during_hook_blocks_later_sends_even_after_resume(workshop_home, monkeypatch):
    install.install(workshop=True)
    adapter.check_requirements({"session_id": "synthetic-race"}, "UserPromptSubmit")
    sent = []
    monkeypatch.setattr(handlers, "_send_span", lambda span: sent.append(span) or True)
    control.main(["off"])
    control.main(["on"])
    assert not handlers.send_span({})
    assert not sent


def test_resumed_turn_drops_late_tool_and_subagent_results(workshop_home, monkeypatch):
    install.install(workshop=True)
    payload = {"session_id": "synthetic-late"}
    _hook(monkeypatch, handlers.user_prompt_submit, {**payload, "prompt": "before pause"})
    _hook(monkeypatch, handlers.pre_tool_use, {**payload, "tool_use_id": "old-tool", "tool_name": "Bash"})
    _hook(monkeypatch, handlers.subagent_start, {**payload, "agent_id": "old-agent"})
    control.main(["off"])
    control.main(["on"])
    _hook(monkeypatch, handlers.user_prompt_submit, {**payload, "prompt": "after resume"})
    sent = []
    monkeypatch.setattr(handlers, "_send_span", lambda span: sent.append(span) or True)
    _hook(
        monkeypatch, handlers.post_tool_use, {**payload, "tool_use_id": "old-tool", "tool_response": "PAUSED_PRIVATE"}
    )
    _hook(
        monkeypatch,
        handlers.subagent_stop,
        {
            **payload,
            "agent_id": "old-agent",
            "agent_type": "general-purpose",
            "last_assistant_message": "PAUSED_PRIVATE",
        },
    )
    assert not sent
    _hook(monkeypatch, handlers.pre_tool_use, {**payload, "tool_use_id": "new-tool", "tool_name": "Bash"})
    _hook(
        monkeypatch,
        handlers.post_tool_use,
        {**payload, "tool_use_id": "new-tool", "tool_name": "Bash", "tool_response": "RESUMED_PUBLIC"},
    )
    assert "RESUMED_PUBLIC" in json.dumps(sent)


def test_legacy_paused_setting_migrates_to_control_without_changing_codex(workshop_home, monkeypatch):
    _, settings_file = workshop_home
    settings_file.write_text(json.dumps({"env": {"ARIZE_TRACE_ENABLED": "false"}}))
    codex_env = settings_file.parents[1] / ".codex" / "arize-env.sh"
    codex_env.parent.mkdir()
    codex_env.write_text("export ARIZE_TRACE_ENABLED=true\n")
    install.install(workshop=True)
    assert read_control("claude-code")["enabled"] is False
    assert json.loads(settings_file.read_text())["env"]["ARIZE_TRACE_ENABLED"] == "true"
    control.main(["on"])
    assert adapter.check_requirements({"session_id": "synthetic-migration"}, "UserPromptSubmit")
    control.main(["off"])
    assert codex_env.read_text() == "export ARIZE_TRACE_ENABLED=true\n"


def test_corrupt_control_fails_closed(workshop_home, monkeypatch):
    install.install(workshop=True)
    control_path("claude-code").write_text('{"enabled": "false"}')
    sent = []
    monkeypatch.setattr(handlers, "_send_span", lambda span: sent.append(span) or True)
    _hook(monkeypatch, handlers.user_prompt_submit, {"session_id": "synthetic-corrupt", "prompt": "private"})
    assert not handlers.send_span({})
    assert not sent


def test_shell_controls_work_without_changing_claude_registration(workshop_home):
    config_path, settings_file = workshop_home
    install.install(workshop=True)
    original = settings_file.read_text()
    venv_bin = config_path.parent / "venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    (venv_bin / "python").symlink_to(sys.executable)
    script = Path(__file__).parents[3] / "install.sh"
    import os

    child_env = {**os.environ, "HOME": str(settings_file.parents[1]), "NO_COLOR": "1"}
    for command, expected in (("pause", "OFF"), ("trace-status", "OFF"), ("resume", "ON")):
        result = subprocess.run(["bash", str(script), command, "claude"], env=child_env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "Claude Code trace capture: " + expected in result.stdout
        assert "synthetic-event-key" not in result.stdout + result.stderr
    assert settings_file.read_text() == original


def test_plugin_import_path_can_read_persistent_control(workshop_home):
    install.install(workshop=True)
    plugin_dir = Path(__file__).parents[3] / "tracing" / "claude_code"
    result = subprocess.run(
        [sys.executable, "-S", "-c", "from hooks.handlers import user_prompt_submit; user_prompt_submit()"],
        cwd=plugin_dir,
        input="{}",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(workshop_home[1].parents[1]), "ARIZE_TRACE_ENABLED": "false"},
    )
    assert result.returncode == 0, result.stderr
