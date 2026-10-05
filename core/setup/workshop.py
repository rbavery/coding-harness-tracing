"""Configure the bug bash without backend, project, or identity prompts."""

from __future__ import annotations

from getpass import getpass
from pathlib import Path
from uuid import uuid4

from core.config import save_config
from core.constants import WORKSHOP_ENDPOINT, WORKSHOP_PROFILE, WORKSHOP_PROJECT
from core.setup import _env, dry_run, env_flag, info, non_interactive


def configure(config: dict, config_path: Path, harness_name: str = "codex") -> str:
    entry = config.get("harnesses", {}).get(harness_name) or {}
    existing = entry.get("profile") == WORKSHOP_PROFILE
    info(f"Workshop tracing: {WORKSHOP_ENDPOINT}, project {WORKSHOP_PROJECT}")
    info("No Phoenix account or email required. Arize usage telemetry is disabled.")

    # Reuse only a key already assigned to our shared Phoenix, never a local or AX key.
    api_key = _env("PHOENIX_API_KEY") if non_interactive() else ""
    if not api_key and entry.get("target") == "phoenix" and entry.get("endpoint", "").rstrip("/") == WORKSHOP_ENDPOINT:
        api_key = entry.get("api_key", "")
    if not api_key and not non_interactive():
        api_key = getpass("Shared workshop API key (paste from organizer): ").strip()
    if not api_key:
        raise ValueError("A shared workshop API key is required. Paste it at setup or supply PHOENIX_API_KEY.")

    saved_logging = entry.get("logging", config.get("logging"))
    if existing and isinstance(saved_logging, dict):
        logging = saved_logging
    elif non_interactive():
        logging = {
            "prompts": env_flag("ARIZE_LOG_PROMPTS", default=False),
            "tool_details": env_flag("ARIZE_LOG_TOOL_DETAILS", default=False),
            "tool_content": env_flag("ARIZE_LOG_TOOL_CONTENT", default=False),
        }
    else:
        capture = input("Send prompts, tool commands, and tool outputs to shared Phoenix? [Y/n]: ").strip().lower()
        if capture not in ("", "y", "yes", "n", "no"):
            raise ValueError("Enter y or n for workshop content logging. No settings were saved.")
        logging = dict.fromkeys(("prompts", "tool_details", "tool_content"), capture in ("", "y", "yes"))

    # An opaque, installation-specific label replaces email. Keep it on updates.
    user_id = entry.get("user_id", "") if existing else ""
    if not user_id.startswith("participant-"):
        user_id = "participant-" + uuid4().hex
    config.setdefault("harnesses", {})[harness_name] = {
        "profile": WORKSHOP_PROFILE,
        "target": "phoenix",
        "endpoint": WORKSHOP_ENDPOINT,
        "project_name": WORKSHOP_PROJECT,
        "api_key": api_key,
        "user_id": user_id,
    }
    if harness_name == "codex" or "logging" not in config:
        config["logging"] = logging
    config["harnesses"][harness_name]["logging"] = logging
    if dry_run():
        info("would save workshop tracing settings")
    else:
        save_config(config, str(config_path))
        config_path.chmod(0o600)
    info(f"Participant ID: {user_id}")
    return user_id
