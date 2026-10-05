"""The participant install needs no backend choices, account, or email."""

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core import common, setup
from core.constants import WORKSHOP_ENDPOINT, WORKSHOP_PROFILE, WORKSHOP_PROJECT
from core.setup import workshop
from tracing.codex import control, install
from tracing.codex.hooks import handlers


@pytest.fixture
def workshop_home(tmp_path, tmp_harness_dir, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
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
    monkeypatch.setattr(install, "CONFIG_FILE", config_path)
    monkeypatch.setattr("core.config.CONFIG_FILE", config_path)
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text('model = "preserve-model"\nnotify = ["existing-notifier", "keep-argument"]\n')
    (codex / "auth.json").write_text("preserve-auth")
    return codex, config_path


def test_fresh_cli_only_asks_for_key_and_content_logging(workshop_home, monkeypatch, capsys):
    codex, config_path = workshop_home
    questions = []

    def key(prompt):
        questions.append(prompt)
        return "shared-test-key"

    def consent(prompt):
        questions.append(prompt)
        return "yes"

    monkeypatch.setattr(workshop, "getpass", key)
    monkeypatch.setattr("builtins.input", consent)
    # Stale developer settings must not silently supply a local key or identity.
    monkeypatch.setenv("PHOENIX_API_KEY", "old-local-key")
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://localhost:6006")
    monkeypatch.setenv("ARIZE_USER_ID", "old@example.com")
    install.cli_main(["install.py", "install"])
    assert len(questions) == 2
    assert "API key" in questions[0]
    assert "Send prompts" in questions[1]
    config = json.loads(config_path.read_text())
    entry = config["harnesses"]["codex"]
    assert entry["profile"] == WORKSHOP_PROFILE
    assert entry["endpoint"] == WORKSHOP_ENDPOINT
    assert entry["project_name"] == WORKSHOP_PROJECT
    assert entry["api_key"] == "shared-test-key"
    assert entry["user_id"].startswith("participant-") and "@" not in entry["user_id"]
    assert all(config["logging"].values())
    assert config_path.stat().st_mode & 0o777 == 0o600
    text = (codex / "arize-env.sh").read_text()
    assert "PHOENIX_TELEMETRY_ENABLED=false" in text
    assert "old@example.com" not in text
    toml = install._toml_load_strict(codex / "config.toml")
    assert toml["model"] == "preserve-model"
    assert "keep-argument" in " ".join(toml["notify"])
    assert (codex / "auth.json").read_text() == "preserve-auth"
    assert "shared-test-key" not in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["n", "no"])
def test_content_logging_can_be_declined(workshop_home, monkeypatch, answer):
    _, config_path = workshop_home
    monkeypatch.setattr(workshop, "getpass", lambda _: "test-key")
    monkeypatch.setattr("builtins.input", lambda _: answer)
    workshop.configure({}, config_path)
    assert not any(json.loads(config_path.read_text())["logging"].values())


def test_reinstall_preserves_anonymous_identity_consent_and_pause(workshop_home, monkeypatch):
    codex, config_path = workshop_home
    monkeypatch.setattr(workshop, "getpass", lambda _: "test-key")
    monkeypatch.setattr("builtins.input", lambda _: "no")
    install.install(workshop=True)
    original = json.loads(config_path.read_text())
    control.main(["off"])
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Reinstall asked another question"))
    monkeypatch.setattr(workshop, "getpass", lambda _: pytest.fail("Reinstall asked for the saved key"))
    # The shell updater requests advanced mode for existing installs. A saved
    # workshop profile must retain its anonymous label and pinned destination.
    install.cli_main(["install.py", "install", "--advanced"])
    assert json.loads(config_path.read_text()) == original
    assert control.env_value((codex / "arize-env.sh").read_text(), "ARIZE_TRACE_ENABLED") == "false"
    install.uninstall()
    assert not (codex / "arize-env.sh").exists()
    assert install._toml_load_strict(codex / "config.toml")["notify"] == ["existing-notifier", "keep-argument"]


def test_local_install_is_reconfigured_without_reusing_local_credentials(workshop_home, monkeypatch):
    _, config_path = workshop_home
    config_path.write_text(
        json.dumps(
            {
                "user_id": "keep-other-harness-identity@example.com",
                "logging": dict.fromkeys(("prompts", "tool_details", "tool_content"), True),
                "harnesses": {
                    "codex": {"target": "phoenix", "endpoint": "http://localhost:6006", "api_key": "local-key"}
                },
            }
        )
    )
    monkeypatch.setattr(workshop, "getpass", lambda _: "event-key")
    monkeypatch.setattr("builtins.input", lambda _: "no")
    install.install(workshop=True)
    config = json.loads(config_path.read_text())
    assert config["harnesses"]["codex"]["api_key"] == "event-key"
    assert not any(config["logging"].values())
    assert config["user_id"] == "keep-other-harness-identity@example.com"


def test_noninteractive_install_is_explicit_about_capture_and_requires_key(workshop_home, monkeypatch):
    _, config_path = workshop_home
    monkeypatch.setenv("ARIZE_NONINTERACTIVE", "true")
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Unexpected prompt"))
    monkeypatch.setattr(workshop, "getpass", lambda _: pytest.fail("Unexpected key prompt"))
    with pytest.raises(ValueError, match="key is required"):
        workshop.configure({}, config_path)
    assert not config_path.exists()
    monkeypatch.setenv("PHOENIX_API_KEY", "test-key")
    workshop.configure({}, config_path)
    assert not any(json.loads(config_path.read_text())["logging"].values())
    monkeypatch.setenv("ARIZE_LOG_PROMPTS", "true")
    workshop.configure({}, config_path)
    assert json.loads(config_path.read_text())["logging"]["prompts"]


@pytest.mark.parametrize("key,consent", [("", "yes"), ("test-key", "invalid")])
def test_invalid_input_does_not_write_configuration(workshop_home, monkeypatch, key, consent):
    _, config_path = workshop_home
    monkeypatch.setattr(workshop, "getpass", lambda _: key)
    monkeypatch.setattr("builtins.input", lambda _: consent)
    with pytest.raises(ValueError):
        workshop.configure({}, config_path)
    assert not config_path.exists()


def test_workshop_hook_exports_only_to_shared_phoenix_despite_inherited_arize_credentials(workshop_home, monkeypatch):
    _, config_path = workshop_home
    monkeypatch.setattr(workshop, "getpass", lambda _: "event-key")
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    install.install(workshop=True)
    for key, value in {
        "ARIZE_API_KEY": "ax-key",
        "ARIZE_SPACE_ID": "ax-space",
        "ARIZE_OTLP_ENDPOINT": "https://otlp.arize.com",
        "PHOENIX_ENDPOINT": "http://localhost:6006",
        "PHOENIX_API_KEY": "local-key",
        "PHOENIX_PROJECT": "local-project",
        "PHOENIX_TELEMETRY_ENABLED": "true",
        "ARIZE_USER_ID": "old@example.com",
    }.items():
        monkeypatch.setenv(key, value)
    requests = []

    def receive(request, timeout):
        requests.append(request)
        return nullcontext(SimpleNamespace(status=200))

    monkeypatch.setattr("urllib.request.urlopen", receive)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "notify",
            json.dumps(
                {
                    "type": "agent-turn-complete",
                    "thread-id": "synthetic-workshop-test",
                    "turn-id": "turn",
                    "input-messages": ["synthetic workshop check"],
                    "last-assistant-message": "synthetic result",
                }
            ),
        ],
    )
    handlers.notify()
    assert len(requests) == 1
    assert requests[0].full_url == WORKSHOP_ENDPOINT + "/v1/traces"
    assert requests[0].get_header("Authorization") == "Bearer event-key"
    assert WORKSHOP_PROJECT.encode() in requests[0].data
    assert "old@example.com".encode() not in requests[0].data
    assert json.loads(config_path.read_text())["harnesses"]["codex"]["user_id"].encode() in requests[0].data
    assert common.os.environ["PHOENIX_TELEMETRY_ENABLED"] == "false"
    # Losing the workshop key must not fall back to the inherited AX credentials.
    config = json.loads(config_path.read_text())
    del config["harnesses"]["codex"]["api_key"]
    config_path.write_text(json.dumps(config))
    handlers.notify()
    assert len(requests) == 1


def test_advanced_cli_retains_original_setup_option():
    with patch.object(install, "install") as called:
        install.cli_main(["install.py", "install", "--advanced"])
    called.assert_called_once_with(with_skills=False, workshop=False)
