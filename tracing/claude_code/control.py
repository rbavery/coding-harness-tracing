"""Pause and resume Claude Code capture without restarting the agent."""

from __future__ import annotations

import argparse
from typing import Optional

from core.config import load_config
from core.tracing_control import read_control, set_enabled


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("on", "off", "status"))
    args = parser.parse_args(argv)
    if "claude-code" not in load_config().get("harnesses", {}):
        parser.exit(1, "Claude Code tracing is not installed. Run the installer first.\n")
    try:
        current = (
            read_control("claude-code") if args.action == "status" else set_enabled("claude-code", args.action == "on")
        )
    except (OSError, ValueError):
        parser.exit(1, "Cannot read or update the Claude Code capture switch. Check the tracing installation.\n")
    print("Claude Code trace capture: " + ("ON" if current["enabled"] else "OFF"))
    print("Applies to all local Claude Code sessions using this tracing installation; no restart needed.")
    if args.action == "off":
        print("Subsequent hooks skip capture and export. An export already in progress may finish.")
    elif args.action == "on":
        print("Capture resumes at the next user prompt. Paused and interrupted turns are not backfilled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
