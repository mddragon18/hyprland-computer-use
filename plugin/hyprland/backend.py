"""Hyprland backend for Hermes computer use.

Design constraints (why this exists at all):

* Hyprland is Wayland-only. There is no XTEST, no X11 screen grab, and the
  native CUA driver fails here (``X11 Error Match`` without its Wayland bridge,
  a screen-blocking cursor overlay with it).
* This backend therefore speaks only Wayland-native protocols:
    - capture      ``grim`` (wlr-screencopy)
    - pointer      ``hypr-vinput`` (wlr-virtual-pointer-unstable-v1), built
                   locally from ``pointer/`` — clicks, drags, wheel
    - text / keys  ``wtype`` (virtual-keyboard-unstable-v1)
    - window info  ``hyprctl`` JSON (clients / monitors / activewindow)
* No SOM/AX elements: the model acts on coordinates read from the screenshot.
  To make that reliable the capture carries a coordinate ruler and the backend
  scales image pixels back to native pixels itself, so the model never does
  display-scale arithmetic and captures stay small enough to be token-cheap.

Config (all optional)::

    computer_use:
      backend: hyprland
      hyprland:
        capture_width: 1600      # downscale target; clicks are in this space
        grid: true               # draw the coordinate ruler
        ruler_step: 200          # image px between ruler labels (100 = finer)
        scope: screen            # screen | window (follow the focused window)
        enforce_target: true     # refuse input outside the last captured window
        pointer_bin: ...         # default: <plugin>/pointer/bin/hypr-vinput

``capture(app=… | pid=… | window_id=…)`` focuses that window and returns a frame
cropped to it, so a tiled desktop does not have to be captured as a whole.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.computer_use.backend import (
    ActionResult,
    CaptureResult,
    ComputerUseBackend,
)

_PLUGIN_DIR = Path(__file__).resolve().parent
_DEFAULT_POINTER = _PLUGIN_DIR / "pointer" / "bin" / "hypr-vinput"
_FONT_PATH = next(
    (p for p in ("/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
                 "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf") if Path(p).is_file()),
    "sans",
)

_KEY_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "tab": "Tab", "space": "space", "backspace": "BackSpace", "delete": "Delete",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
}


def _cfg() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        return (((load_config_readonly() or {}).get("computer_use") or {}).get("hyprland") or {})
    except Exception:
        return {}


def _run(cmd: List[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, text=False)


def _run_input(cmd: List[str], data: bytes, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=data, capture_output=True, timeout=timeout, text=False)


def _png_size(data: bytes) -> Optional[Tuple[int, int]]:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    return None


def _pointer_path(opts: Optional[Dict[str, Any]] = None) -> Path:
    """Pointer helper resolution: config, env, the bundled build, then PATH."""
    opts = opts if opts is not None else _cfg()
    configured = opts.get("pointer_bin") or os.environ.get("HYPRLAND_CU_POINTER_BIN")
    if configured:
        return Path(str(configured)).expanduser()
    if _DEFAULT_POINTER.is_file():
        return _DEFAULT_POINTER
    found = shutil.which("hypr-vinput")
    return Path(found) if found else _DEFAULT_POINTER


class HyprlandBackend(ComputerUseBackend):
    """One backend per Hermes session; the pointer helper is spawned per event batch."""

    def __init__(self, *, permission_mode: str = "standard"):
        self.permission_mode = permission_mode
        opts = _cfg()
        self.capture_width = max(320, int(opts.get("capture_width") or 1600))
        self.grid = bool(opts.get("grid", True))
        # Distance between ruler labels, in image pixels. 100 halves the interpolation the model
        # has to do vertically (radio rows are ~32 px apart at 1600 wide) at the cost of clutter.
        self.ruler_step = min(400, max(50, int(opts.get("ruler_step") or 200)))
        self.scope = str(opts.get("scope") or "screen").lower()
        # Refuse input outside the window the last capture/focus_app selected. Disable for
        # genuine cross-window gestures (e.g. dragging a file from one app to another).
        self.enforce_target = bool(opts.get("enforce_target", True))
        self.pointer_bin = _pointer_path(opts)

        # Set by capture(); every coordinate the model sends is in this frame.
        self._frame: Optional[Dict[str, Any]] = None
        self._last_app: Optional[str] = None
        self._last_target: Optional[dict] = None
        # The window the frame belongs to. Used to refuse clicks that would land in another
        # app (a real failure mode on a tiled screen: the model read the wrong half of the
        # screenshot and clicked the terminal behind the app it was driving).
        self._target_win: Optional[dict] = None
        self._target_gone = False

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self) -> None:
        pass  # every event batch is a short-lived helper process

    def stop(self) -> None:
        pass

    def is_available(self) -> bool:
        return self.probe()

    @classmethod
    def probe(cls) -> bool:
        opts = _cfg()
        return bool(
            os.environ.get("WAYLAND_DISPLAY")
            and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
            and _pointer_path(opts).is_file()
            and shutil.which("grim")
            and shutil.which("wtype")
        )

    # ── helpers ───────────────────────────────────────────────────────────
    def _hyprctl_json(self, *args: str) -> Any:
        p = _run(["hyprctl", *args, "-j"])
        if p.returncode != 0:
            raise RuntimeError((p.stderr or b"").decode(errors="replace").strip() or "hyprctl failed")
        return json.loads((p.stdout or b"{}").decode(errors="replace") or "{}")

    def _monitor_bbox(self) -> Tuple[int, int, int, int]:
        monitors = self._hyprctl_json("monitors")
        if not monitors:
            raise RuntimeError("hyprctl monitors returned no outputs")
        minx = min(int(m["x"]) for m in monitors)
        miny = min(int(m["y"]) for m in monitors)
        maxx = max(int(m["x"]) + int(m["width"]) for m in monitors)
        maxy = max(int(m["y"]) + int(m["height"]) for m in monitors)
        return minx, miny, maxx - minx, maxy - miny

    def _active_window(self) -> Dict[str, Any]:
        try:
            win = self._hyprctl_json("activewindow")
        except Exception:
            return {}
        return win if isinstance(win, dict) else {}

    # ── window resolution ─────────────────────────────────────────────────
    def _clients(self) -> List[dict]:
        try:
            clients = self._hyprctl_json("clients")
        except Exception:
            return []
        return clients if isinstance(clients, list) else []

    @staticmethod
    def _win_bounds(win: Optional[dict]) -> Optional[Tuple[int, int, int, int]]:
        try:
            w, h = int(win["size"][0]), int(win["size"][1])  # type: ignore[index]
            if w < 40 or h < 40:
                return None
            return int(win["at"][0]), int(win["at"][1]), w, h  # type: ignore[index]
        except Exception:
            return None

    @staticmethod
    def _win_app(win: Optional[dict]) -> str:
        return str((win or {}).get("class") or (win or {}).get("initialClass") or "")

    @staticmethod
    def _addr_int(win: dict) -> Optional[int]:
        try:
            return int(str(win.get("address") or ""), 16)
        except Exception:
            return None

    def _resolve_window(self, app: Optional[str] = None, pid: Optional[int] = None,
                        window_id: Optional[int] = None) -> Optional[dict]:
        """Find the window the caller named. ``window_id`` arrives either as the hex string from
        ``list_windows`` or as its decimal value (models convert it), so accept both."""
        clients = self._clients()
        if window_id is not None:
            try:
                want_int = int(window_id)
            except Exception:
                want_int = None
            want_str = str(window_id).strip().lower()
            for c in clients:
                addr = str(c.get("address") or "")
                if addr.lower() == want_str or (want_int is not None and self._addr_int(c) == want_int):
                    return c
        if pid is not None:
            try:
                want_pid = int(pid)
            except Exception:
                want_pid = None
            if want_pid is not None:
                for c in clients:
                    if int(c.get("pid") or -1) == want_pid:
                        return c
        if app:
            wanted = str(app).strip().lower()
            if wanted:
                # Exact class first: an app name such as "hermes" must not match another
                # window's title before the real Hermes window.
                for c in clients:
                    klass = str(c.get("class") or c.get("initialClass") or "").lower()
                    if wanted == klass:
                        return c
                for c in clients:
                    klass = str(c.get("class") or c.get("initialClass") or "").lower()
                    if wanted in " ".join((klass, str(c.get("title") or "").lower())):
                        return c
        return None

    def _focus_window(self, win: dict, raise_window: bool = False) -> None:
        addr = str(win.get("address") or "")
        if not addr:
            return
        self._hypr_repl(f'hl.dispatch(hl.dsp.focus({{window="address:{addr}"}}))')
        if raise_window:
            self._hypr_repl(f'hl.dispatch(hl.dsp.window.bring_to_top({{window="address:{addr}"}}))')
        time.sleep(0.12)

    def _refresh_target(self) -> None:
        """Pick up a move/resize since the capture (tiling reflows when windows open)."""
        if not self._target_win:
            return
        addr = str(self._target_win.get("address") or "")
        if not addr:
            return
        clients = self._clients()
        for c in clients:
            if str(c.get("address") or "") == addr:
                self._target_win = c
                self._target_gone = False
                return
        if clients:  # an empty list can be a transient hyprctl failure; don't lock out
            self._target_gone = True

    def _checked_point(self, nx: int, ny: int) -> Optional[str]:
        """Message when (nx, ny) falls outside the window this frame belongs to, else None.

        The tool's contract is that input goes to the sticky target from the last capture or
        focus_app. Enforcing it in pixel space turns a silent wrong-window click into an
        actionable error — the exact failure that cost an 89-call session on a split screen.
        """
        if not self.enforce_target:
            return None
        self._refresh_target()
        if self._target_gone:
            return ("the window captured earlier is no longer open; capture again to pick a new "
                    "target")
        bounds = self._win_bounds(self._target_win)
        if bounds is None:
            return None
        bx, by, bw, bh = bounds
        if bx <= nx < bx + bw and by <= ny < by + bh:
            return None
        img = ""
        if self._frame:
            ox, oy = self._frame["origin"]
            sx, sy = self._frame["scale"]
            img = (f"; in the current screenshot that window spans image x "
                   f"{round((bx - ox) / sx)}..{round((bx + bw - ox) / sx)}, y "
                   f"{round((by - oy) / sy)}..{round((by + bh - oy) / sy)}")
        return (f"coordinate ({nx}, {ny}) native is outside the captured window "
                f"{self._win_app(self._target_win) or '?'!r} at native {bx},{by} {bw}x{bh}{img}. "
                "Click inside that window, or capture/focus the app you mean first.")

    def _apply_delivery(self, delivery_mode: Optional[str], bring_to_front: bool = False) -> None:
        """Our injection is always a real event; 'foreground' therefore means 'focus the target
        first'. 'background' is a no-op (events still go to whatever has focus)."""
        mode = (delivery_mode or "").lower()
        if not (mode in ("foreground", "front", "bring_to_front") or bring_to_front):
            return
        if self._target_win is not None:
            try:
                self._focus_window(self._target_win, raise_window=bool(bring_to_front))
            except Exception:
                pass

    def _to_native(self, x: float, y: float) -> Tuple[int, int]:
        if not self._frame:
            return int(round(x)), int(round(y))
        ox, oy = self._frame["origin"]
        sx, sy = self._frame["scale"]
        return int(round(ox + x * sx)), int(round(oy + y * sy))

    def _extents(self) -> Tuple[int, int, int, int]:
        """(origin_x, origin_y, layout_w, layout_h) for wlr absolute motion."""
        return self._monitor_bbox()

    def _pointer(self, *args: str, timeout: float = 8.0) -> subprocess.CompletedProcess:
        if not self.pointer_bin.is_file():
            raise RuntimeError(
                f"pointer helper missing: {self.pointer_bin}. Build it with "
                f"`make -C {self.pointer_bin.parent.parent}` and retry."
            )
        return _run([str(self.pointer_bin), *args], timeout=timeout)

    # ── capture ───────────────────────────────────────────────────────────
    def capture(self, mode: str = "som", app: Optional[str] = None, pid: Optional[int] = None,
                window_id: Optional[int] = None) -> CaptureResult:
        ox, oy, lw, lh = self._monitor_bbox()
        active = self._active_window()

        wanted = self._resolve_window(app=app, pid=pid, window_id=window_id)
        explicit = bool(app or pid is not None or window_id is not None)
        subject: Optional[dict] = None
        missing = False
        if explicit:
            if self._win_bounds(wanted):
                subject = wanted
                # grim captures the composited screen: an occluded window would otherwise
                # capture whatever is on top of it.
                if str(active.get("address") or "") != str(subject.get("address") or ""):
                    try:
                        self._focus_window(subject, raise_window=False)
                    except Exception:
                        pass
            else:
                missing = True
                subject = active if self._win_bounds(active) else None
        else:
            subject = active if self._win_bounds(active) else None

        region = (ox, oy, lw, lh)
        title = str(subject.get("title") or "") if subject else ""
        klass = self._win_app(subject)

        window_scope = subject is not None and (explicit or self.scope == "window")
        if window_scope:
            b = self._win_bounds(subject)
            if b:
                bx, by, bw, bh = b
                x1, y1 = max(bx, ox), max(by, oy)
                x2, y2 = min(bx + bw, ox + lw), min(by + bh, oy + lh)
                if x2 - x1 > 40 and y2 - y1 > 40:
                    region = (x1, y1, x2 - x1, y2 - y1)

        rx, ry, rw, rh = region
        fell_back = False
        try:
            p = _run(["grim", "-g", f"{rx},{ry} {rw}x{rh}", "-"], timeout=10.0)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                "grim did not produce a frame within 10 s. The output may be asleep "
                "(dpmsStatus false) or the window may have no frame; wake the monitor "
                "and retry.") from e
        if p.returncode != 0 or not p.stdout:
            # One retry without a geometry: capture the whole layout if -g was refused.
            try:
                p = _run(["grim", "-"], timeout=10.0)
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    "grim did not produce a frame within 10 s. The output may be asleep "
                    "(dpmsStatus false); wake the monitor and retry.") from e
            rx, ry, rw, rh = ox, oy, lw, lh
            fell_back = True
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError("grim capture failed: " + (p.stderr or b"").decode(errors="replace").strip())
        raw = p.stdout
        out_w, out_h, scale_x, scale_y, raw = self._postprocess(raw, rw, rh)

        self._frame = {
            "origin": (rx, ry),
            "native": (rw, rh),
            "image": (out_w, out_h),
            "scale": (scale_x, scale_y),
        }
        self._target_win = subject
        self._target_gone = False
        self._last_app = klass or app or None
        # Pixel-only backend: never hand the tool a stale pid/window_id for recapture.
        self._last_target = None

        subject_desc = f"{app or pid or window_id!r}"
        if subject is not None and window_scope and not fell_back:
            where = f"window {klass or '?'!r} at native {rx},{ry} {rw}x{rh}"
        else:
            where = f"screen at native {rx},{ry} {rw}x{rh}"
        if self.grid:
            note = (f"pixel-only Hyprland capture of {where}; click coordinates are image pixels "
                    f"and are scaled back to native by the backend. Ruler labels every {self.ruler_step} image px.")
        else:
            note = (f"pixel-only Hyprland capture of {where}; click coordinates are image pixels "
                    f"({out_w}x{out_h}).")
        if missing:
            note += (f" Requested {subject_desc} was not found; captured the focused window instead.")
        if fell_back and window_scope:
            note += " Window crop failed; this frame is the whole screen."
        return CaptureResult(
            # Pixel-only: an `ax` request still returns the frame (elements are always empty here),
            # otherwise the model would get a dead-end "0 elements" response with no image.
            mode="vision",
            width=out_w,
            height=out_h,
            png_b64=base64.b64encode(raw).decode("ascii"),
            elements=[],
            app=klass or (app or ""),
            window_title=title,
            png_bytes_len=len(raw),
            image_mime_type="image/png",
            note=note,
        )

    def _postprocess(self, raw: bytes, rw: int, rh: int) -> Tuple[int, int, float, float, bytes]:
        """Resize + optional ruler, using ImageMagick (no Python image deps in the Hermes runtime).

        Returns ``(out_w, out_h, scale_x, scale_y, png_bytes)`` where scale maps image px → native px.
        Any failure degrades to the native grim PNG with a 1:1 click space.
        """
        native = _png_size(raw)
        if native:
            rw, rh = native
        out_w = min(rw, self.capture_width)
        out_h = max(1, int(round(rh * out_w / rw)))
        if not shutil.which("magick"):
            return rw, rh, 1.0, 1.0, raw

        cmd: List[str] = ["magick", "-", "-resize", f"{out_w}x>"]
        if self.grid:
            label_step = self.ruler_step
            line_step = max(50, label_step // 2)
            lines: List[str] = []
            for x in range(line_step, out_w, line_step):
                lines.append(f"line {x},0 {x},{out_h}")
            for y in range(line_step, out_h, line_step):
                lines.append(f"line 0,{y} {out_w},{y}")
            if lines:
                cmd += ["-stroke", "rgba(99,102,241,0.10)", "-strokewidth", "1", "-fill", "none",
                        "-draw", " ".join(lines)]
            cmd += ["-stroke", "none", "-font", _FONT_PATH, "-pointsize", "13"]
            for x in range(label_step, out_w, label_step):
                label = str(x)
                box_w = 8 * len(label) + 4
                cmd += ["-fill", "rgba(255,255,255,0.82)", "-draw", f"rectangle {x},0 {x + box_w},15",
                        "-fill", "#1e1e1e", "-draw", f"text {x + 1},12 '{label}'"]
            for y in range(label_step, out_h, label_step):
                label = str(y)
                cmd += ["-fill", "rgba(255,255,255,0.82)", "-draw", f"rectangle 0,{y} 34,{y + 14}",
                        "-fill", "#1e1e1e", "-draw", f"text 2,{y + 12} '{label}'"]
        cmd += ["png:-"]
        try:
            q = _run_input(cmd, raw, timeout=15.0)
            if q.returncode == 0 and q.stdout:
                got = _png_size(q.stdout)
                if got:
                    out_w, out_h = got
                return out_w, out_h, rw / out_w, rh / out_h, q.stdout
        except Exception:
            pass
        return rw, rh, 1.0, 1.0, raw

    # ── pointer ───────────────────────────────────────────────────────────
    _BUTTONS = ("left", "right", "middle")

    def click(self, *, element: Optional[int] = None, x: Optional[float] = None, y: Optional[float] = None,
              button: str = "left", click_count: int = 1, modifiers: Optional[list[str]] = None,
              delivery_mode: Optional[str] = None, bring_to_front: bool = False) -> ActionResult:
        if x is None or y is None:
            return ActionResult(ok=False, action="click", code="unsupported_action",
                                message="this backend has no element tree; click with coordinate=[x, y]")
        if modifiers:
            return ActionResult(
                ok=False, action="click", code="unsupported_action",
                message=("modifier+click is not supported: holding a key across a pointer event needs "
                         "/dev/uinput, which this backend deliberately avoids. Type the shortcut with "
                         "`key` and use a plain click, or use a different backend for that action."))
        nx, ny = self._to_native(x, y)
        _, _, ew, eh = self._extents()
        btn = (button or "left").lower()
        if btn not in self._BUTTONS:
            return ActionResult(ok=False, action="click", code="unsupported_action", message=f"unknown button {button!r}")
        outside = self._checked_point(nx, ny)
        if outside:
            return ActionResult(ok=False, action="click", code="target_mismatch", message=outside)

        self._apply_delivery(delivery_mode, bring_to_front)
        count = max(1, int(click_count or 1))
        try:
            for _ in range(count):
                p = self._pointer("hitat", str(nx), str(ny), str(ew), str(eh), btn)
                if p.returncode != 0:
                    return ActionResult(ok=False, action="click",
                                        message=(p.stderr or b"").decode(errors="replace").strip() or "hypr-vinput failed")
                if count > 1:
                    time.sleep(0.06)
        except Exception as e:
            return ActionResult(ok=False, action="click", message=str(e))
        suffix = f" x{count}" if count > 1 else ""
        return ActionResult(ok=True, action="click", message=f"clicked ({nx}, {ny}) native {btn}{suffix}")

    def drag(self, *, from_element: Optional[int] = None, to_element: Optional[int] = None,
             from_xy: Optional[tuple] = None, to_xy: Optional[tuple] = None,
             button: str = "left", modifiers: Optional[list[str]] = None,
             delivery_mode: Optional[str] = None, bring_to_front: bool = False) -> ActionResult:
        if not from_xy or not to_xy:
            return ActionResult(ok=False, action="drag", code="unsupported_action",
                                message="drag needs from_coordinate and to_coordinate")
        if modifiers:
            return ActionResult(ok=False, action="drag", code="unsupported_action",
                                message="modifier+drag is not supported by this backend")
        x1, y1 = self._to_native(*from_xy)
        x2, y2 = self._to_native(*to_xy)
        btn = (button or "left").lower()
        if btn not in self._BUTTONS:
            return ActionResult(ok=False, action="drag", code="unsupported_action", message=f"unknown button {button!r}")
        for px, py in ((x1, y1), (x2, y2)):
            outside = self._checked_point(px, py)
            if outside:
                return ActionResult(ok=False, action="drag", code="target_mismatch", message=outside)

        self._apply_delivery(delivery_mode, bring_to_front)
        _, _, ew, eh = self._extents()
        try:
            p = self._pointer("drag", str(x1), str(y1), str(x2), str(y2), str(ew), str(eh), btn,
                              timeout=10.0)
            if p.returncode != 0:
                return ActionResult(ok=False, action="drag",
                                    message=(p.stderr or b"").decode(errors="replace").strip() or "hypr-vinput failed")
        except Exception as e:
            return ActionResult(ok=False, action="drag", message=str(e))
        return ActionResult(ok=True, action="drag", message=f"dragged ({x1}, {y1}) → ({x2}, {y2})")

    def scroll(self, *, direction: str, amount: int = 3, element: Optional[int] = None,
               x: Optional[float] = None, y: Optional[float] = None,
               modifiers: Optional[list[str]] = None, delivery_mode: Optional[str] = None,
               bring_to_front: bool = False) -> ActionResult:
        d = (direction or "down").lower()
        n = max(1, abs(int(amount or 3)))
        # wl_pointer.axis is positive downwards.
        ticks = -n if d == "up" else n
        self._apply_delivery(delivery_mode, bring_to_front)
        if x is None or y is None:
            # No coordinate: scroll the window this frame belongs to, not whatever the
            # user's physical pointer happens to be over.
            bounds = self._win_bounds(self._target_win)
            if bounds:
                bx, by, bw, bh = bounds
                if self._frame:
                    ox, oy = self._frame["origin"]
                    sx, sy = self._frame["scale"]
                    x, y = (bx + bw / 2 - ox) / sx, (by + bh / 2 - oy) / sy
                else:
                    x, y = float(bx + bw // 2), float(by + bh // 2)
        try:
            if x is not None and y is not None:
                nx, ny = self._to_native(x, y)
                outside = self._checked_point(nx, ny)
                if outside:
                    return ActionResult(ok=False, action="scroll", code="target_mismatch", message=outside)
                _, _, ew, eh = self._extents()
                p = self._pointer("scrollat", str(nx), str(ny), str(ew), str(eh), str(ticks))
            else:
                p = self._pointer("scroll", str(ticks))
            if p.returncode != 0:
                return ActionResult(ok=False, action="scroll",
                                    message=(p.stderr or b"").decode(errors="replace").strip() or "hypr-vinput failed")
        except Exception as e:
            return ActionResult(ok=False, action="scroll", message=str(e))
        return ActionResult(ok=True, action="scroll", message=f"scrolled {d} x{n}")

    # ── keyboard ──────────────────────────────────────────────────────────
    def type_text(self, text: str, *, delivery_mode: Optional[str] = None,
                  bring_to_front: bool = False) -> ActionResult:
        if not text:
            return ActionResult(ok=True, action="type", message="nothing to type")
        self._apply_delivery(delivery_mode, bring_to_front)
        try:
            # wtype parses leading dashes as options; use clipboard paste for those.
            if text.lstrip().startswith("-"):
                self._clipboard(text)
                self._wtype_key("v", ["ctrl"])
            else:
                p = _run(["wtype", text], timeout=15.0)
                if p.returncode != 0:
                    self._clipboard(text)
                    self._wtype_key("v", ["ctrl"])
        except Exception as e:
            return ActionResult(ok=False, action="type", message=str(e))
        return ActionResult(ok=True, action="type", message=f"typed {len(text)} chars")

    @staticmethod
    def _clipboard(text: str) -> None:
        subprocess.run(["wl-copy"], input=text.encode(), timeout=5.0, check=True)
        time.sleep(0.05)

    def _wtype_key(self, key: str, mods: Optional[List[str]] = None) -> None:
        # wtype names the Windows/Super key "logo", not "super".
        alias = {"super": "logo", "meta": "logo", "win": "logo", "cmd": "logo", "command": "logo"}
        mods = [alias.get(str(m).lower(), str(m).lower()) for m in (mods or [])]
        cmd = ["wtype"]
        for m in mods:
            cmd += ["-M", m]
        cmd += ["-k", key]
        for m in reversed(mods):
            cmd += ["-m", m]
        p = _run(cmd, timeout=8.0)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or b"").decode(errors="replace").strip() or "wtype failed")

    def key(self, keys: str, *, delivery_mode: Optional[str] = None,
            bring_to_front: bool = False) -> ActionResult:
        parts = [p.strip() for p in (keys or "").replace("-", "+").split("+") if p.strip()]
        if not parts:
            return ActionResult(ok=False, action="key", message="empty key combo")
        mods = [p.lower() for p in parts[:-1]]
        key = parts[-1]
        if key.lower() in _KEY_ALIASES:
            key = _KEY_ALIASES[key.lower()]
        self._apply_delivery(delivery_mode, bring_to_front)
        try:
            self._wtype_key(key, mods)
        except Exception as e:
            return ActionResult(ok=False, action="key", message=str(e))
        return ActionResult(ok=True, action="key", message=f"pressed {'+'.join(parts)}")

    # ── windows ───────────────────────────────────────────────────────────
    def list_apps(self) -> list[dict[str, Any]]:
        try:
            clients = self._hyprctl_json("clients")
        except Exception:
            return []
        by_app: Dict[str, dict] = {}
        for c in clients:
            name = str(c.get("class") or c.get("initialClass") or "")
            if not name:
                continue
            row = by_app.setdefault(name, {"app": name, "pids": [], "window_count": 0})
            row["window_count"] += 1
            if c.get("pid") not in row["pids"]:
                row["pids"].append(c.get("pid"))
        return sorted(by_app.values(), key=lambda r: r["app"].lower())

    def list_windows(self) -> list[dict[str, Any]]:
        try:
            clients = self._hyprctl_json("clients")
        except Exception:
            return []
        out = []
        for c in clients:
            try:
                x, y = int(c["at"][0]), int(c["at"][1])
                w, h = int(c["size"][0]), int(c["size"][1])
            except Exception:
                x = y = w = h = 0
            out.append({
                "window_id": c.get("address"),
                "address": c.get("address"),
                "pid": c.get("pid"),
                "app": c.get("class") or c.get("initialClass") or "",
                "title": c.get("title") or "",
                "bounds": [x, y, w, h],
                "workspace": (c.get("workspace") or {}).get("name"),
                "focused": bool(c.get("focusHistoryID") == 0),
            })
        return out

    def focus_app(self, app: str, raise_window: bool = False) -> ActionResult:
        wanted = (app or "").strip().lower()
        if not wanted:
            return ActionResult(ok=False, action="focus_app", message="empty app")
        hero = self._resolve_window(app=app)
        if not hero:
            return ActionResult(ok=False, action="focus_app", message=f"no window matching {app!r}")
        try:
            self._focus_window(hero, raise_window=raise_window)
        except Exception as e:
            return ActionResult(ok=False, action="focus_app", message=str(e))
        # From here on, coordinates belong to this window: clicks outside it are refused
        # instead of silently landing in whatever is tiled next to it.
        self._target_win = hero
        self._target_gone = False
        b = self._win_bounds(hero)
        where = f" at native {b[0]},{b[1]} {b[2]}x{b[3]}" if b else ""
        return ActionResult(ok=True, action="focus_app",
                            message=f"focused {self._win_app(hero) or ''} {hero.get('address') or ''}{where}")

    @staticmethod
    def _hypr_repl(expr: str) -> None:
        p = _run(["hyprctl", "repl", expr], timeout=6.0)
        blob = ((p.stdout or b"") + (p.stderr or b"")).decode(errors="replace").strip()
        if p.returncode != 0 or "error:" in blob.lower():
            raise RuntimeError(blob or "hyprctl repl failed")

    def set_value(self, value: str, element: Optional[int] = None) -> ActionResult:
        return ActionResult(ok=False, action="set_value", code="unsupported_action",
                            message="no accessibility tree here; click the control and use key/type instead")



