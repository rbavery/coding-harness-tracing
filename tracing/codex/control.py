"""Pause and resume Codex trace exports without restarting Codex."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from tracing.codex.constants import get_codex_home


def env_value(text: str, key: str, default: str = "") -> str:
    """Read a setting using the same literal rules as the notify hook."""
    value = default
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        name, separator, candidate = line.partition("=")
        if separator and name.strip() == key:
            value = candidate.strip().strip("\"'")
    return value


def replace_setting(text: str, key: str, value: str) -> str:
    pattern = rf"(?m)^[ \t]*(?:export[ \t]+)?{re.escape(key)}=.*$"
    result, count = re.subn(pattern, lambda _: f"export {key}={value}", text)
    return result if count else text.rstrip("\n") + ("\n" if text else "") + f"export {key}={value}\n"


def write_env_file(path: Path, text: str) -> None:
    """Replace the file atomically so callbacks cannot read a partial update."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", prefix=".arize-env-", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("on", "off", "status"))
    args = parser.parse_args(argv)
    try:
        path = get_codex_home() / "arize-env.sh"
        text = path.read_text()
        if args.action != "status":
            text = replace_setting(text, "ARIZE_TRACE_ENABLED", "true" if args.action == "on" else "false")
            write_env_file(path, text)
        enabled = env_value(text, "ARIZE_TRACE_ENABLED", "true").lower() == "true"
    except (OSError, ValueError):
        parser.exit(1, "Cannot read or update the Codex tracing settings. Check installation and CODEX_HOME.\n")
    print("Codex trace export: " + ("ON" if enabled else "OFF"))
    print("Applies to all chats using " + str(path.parent) + "; no restart needed.")
    if args.action == "off":
        print("Subsequent turn callbacks skip export. An export already in progress may finish.")
    elif args.action == "on":
        print("Subsequent completed turns export using the saved destination and key.")
        print("A key revoked in Phoenix must be replaced before exports can succeed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
