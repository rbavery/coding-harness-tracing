"""Persistent capture switches, readable from package and plugin hook processes."""

from __future__ import annotations

import json
import os
import tempfile
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from core import constants

# Each hook records the generation it started in. A pause/resume during a
# long-running hook must not allow that hook to export after the pause.
hook_generation: ContextVar[str | None] = ContextVar("hook_generation", default=None)
hook_service: ContextVar[str] = ContextVar("hook_service", default="")


def control_path(harness_name: str) -> Path:
    return constants.STATE_BASE_DIR / harness_name / "capture-control.json"


def read_control(harness_name: str) -> dict:
    path = control_path(harness_name)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {"enabled": True, "generation": ""}
    if (
        not isinstance(data, dict)
        or type(data.get("enabled")) is not bool
        or not isinstance(data.get("generation"), str)
        or not data["generation"]
    ):
        raise ValueError("Invalid tracing control file")
    return data


def _write_control(harness_name: str, enabled: bool) -> dict:
    path = control_path(harness_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"enabled": enabled, "generation": uuid4().hex}
    with tempfile.NamedTemporaryFile(mode="w", prefix=".capture-", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return data


def initialize_control(harness_name: str, enabled: bool = True) -> dict:
    """Keep an existing switch intact on reinstall, including a paused state."""
    if control_path(harness_name).exists():
        return read_control(harness_name)
    return _write_control(harness_name, enabled)


def set_enabled(harness_name: str, enabled: bool) -> dict:
    current = read_control(harness_name)
    if current["generation"] and current["enabled"] == enabled:
        return current
    return _write_control(harness_name, enabled)


def can_export(harness_name: str) -> bool:
    current = read_control(harness_name)
    expected = hook_generation.get()
    return bool(current["enabled"] and (expected is None or expected == current["generation"]))
