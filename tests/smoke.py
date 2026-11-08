#!/usr/bin/env python3
"""Smoke tests for the hyprland computer-use provider.

Run with the Hermes runtime (it has the bootstrap + tool packages)::

    HERMES_HOME=$HOME/.hermes \
      ~/.hermes/tools/python-3.14.9+20261021-linux-x64/bin/python3 tests/smoke.py doctor
    ... tests/smoke.py capture /tmp/opencode/cap.png
    ... tests/smoke.py capture /tmp/opencode/cap.png com.nousresearch.hermes
    ... tests/smoke.py click 550 506 /tmp/opencode/after.png    # inside that capture
    ... tests/smoke.py tool /tmp/opencode/tool.png     # through handle_computer_use()

These live outside ``plugin/hyprland`` on purpose: the Hermes plugin loader
executes every sibling ``.py`` file in the plugin directory.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

HERMES_AGENT = os.environ.get("HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent"))
sys.path.insert(0, HERMES_AGENT)
os.environ.setdefault("HERMES_HOME", str(Path.home() / ".hermes"))
import hermes_bootstrap  # noqa: F401,E402


def _provider():
    from plugins.computer_use import load_computer_use_provider

    provider = load_computer_use_provider("hyprland")
    if provider is None:
        raise SystemExit("provider 'hyprland' not found — is it linked into $HERMES_HOME/plugins?")
    return provider


def _save(cap, path: str) -> None:
    Path(path).write_bytes(base64.b64decode(cap.png_b64))
    print(f"saved {path} ({cap.width}x{cap.height}, {cap.png_bytes_len} bytes)")


def cmd_doctor() -> int:
    return _provider().doctor()


def cmd_capture(path: str, app: str | None) -> int:
    backend = _provider().create_backend(permission_mode="standard")
    backend.start()
    try:
        cap = backend.capture(mode="vision", app=app)
        print(f"capture {cap.width}x{cap.height} app={cap.app!r} window={cap.window_title!r}")
        print(f"note: {cap.note}")
        print(f"frame: {backend._frame}")
        print(f"windows: {len(backend.list_windows())}")
        _save(cap, path)
    finally:
        backend.stop()
    return 0


def cmd_click(x: int, y: int, path: str, app: str | None) -> int:
    backend = _provider().create_backend(permission_mode="standard")
    backend.start()
    try:
        cap = backend.capture(mode="vision", app=app)
        print(f"note: {cap.note}")
        print(backend.click(x=x, y=y))
        time.sleep(0.6)
        cap = backend.capture(mode="vision", app=app)
        print(f"after: {cap.width}x{cap.height} app={cap.app!r}")
        _save(cap, path)
    finally:
        backend.stop()
    return 0


def cmd_tool(path: str, session_id: str = "hyprland-smoke") -> int:
    from tools.computer_use.tool import handle_computer_use

    result = handle_computer_use({"action": "capture", "mode": "vision"}, session_id=session_id)
    if not (isinstance(result, dict) and result.get("_multimodal")):
        print(result)
        return 1
    print(result["text_summary"])
    print(f"meta: {result['meta']}")
    images = [part for part in result["content"] if part.get("type") == "image_url"]
    if images:
        data = images[0]["image_url"]["url"].split(",", 1)[1]
        Path(path).write_bytes(base64.b64decode(data))
        print(f"saved {path}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, rest = argv[1], argv[2:]
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "capture":
        return cmd_capture(rest[0] if rest else "/tmp/opencode/cap.png", rest[1] if len(rest) > 1 else None)
    if cmd == "click":
        if len(rest) < 2:
            print("click needs X Y [out.png] [app]")
            return 2
        return cmd_click(int(rest[0]), int(rest[1]),
                         rest[2] if len(rest) > 2 else "/tmp/opencode/after.png",
                         rest[3] if len(rest) > 3 else None)
    if cmd == "tool":
        return cmd_tool(rest[0] if rest else "/tmp/opencode/tool.png")
    print(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
