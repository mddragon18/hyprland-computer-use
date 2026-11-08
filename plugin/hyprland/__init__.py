"""Hermes computer-use provider for Hyprland (Wayland-native, no CUA).

Register with::

    computer_use:
      backend: hyprland

The backend behind this provider is :mod:`.backend` — grim capture,
wlr-virtual-pointer input via the locally built ``pointer/hypr-vinput``, wtype
text, and hyprctl window metadata.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from tools.computer_use.backend import ComputerUseBackend, ComputerUseProvider


class HyprlandProvider(ComputerUseProvider):
    name = "hyprland"
    display_name = "Hyprland (Wayland, pixel + wlr-virtual-pointer)"

    def create_backend(self, *, permission_mode: str) -> ComputerUseBackend:
        from .backend import HyprlandBackend

        return HyprlandBackend(permission_mode=permission_mode)

    def is_available(self) -> bool:
        from .backend import HyprlandBackend

        return HyprlandBackend.probe()

    def doctor(self) -> int:
        from .backend import _cfg, _pointer_path

        opts = _cfg()
        pointer = _pointer_path(opts)
        protocol = "pointer helper not built"
        protocol_ok = False
        if pointer.is_file():
            if not os.environ.get("WAYLAND_DISPLAY"):
                protocol = "not checked (no Wayland display)"
            else:
                try:
                    p = subprocess.run([str(pointer), "probe"], capture_output=True, timeout=5)
                    protocol_ok = p.returncode == 0
                    protocol = ((p.stdout or b"") + (p.stderr or b"")).decode(errors="replace").strip()
                except Exception as exc:
                    protocol = f"probe failed: {exc}"
        checks = [
            ("WAYLAND_DISPLAY", bool(os.environ.get("WAYLAND_DISPLAY")), os.environ.get("WAYLAND_DISPLAY", "")),
            ("HYPRLAND_INSTANCE_SIGNATURE", bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")),
             "set" if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") else "missing"),
            ("hyprctl", bool(shutil.which("hyprctl")), shutil.which("hyprctl") or "missing"),
            ("grim", bool(shutil.which("grim")), shutil.which("grim") or "missing"),
            ("wtype", bool(shutil.which("wtype")), shutil.which("wtype") or "missing"),
            ("wl-copy", bool(shutil.which("wl-copy")), shutil.which("wl-copy") or "optional, missing"),
            ("magick (ruler/downscale)", bool(shutil.which("magick")), shutil.which("magick") or "optional, missing"),
            ("hypr-vinput", pointer.is_file(), str(pointer)),
            ("wlr-virtual-pointer", protocol_ok, protocol),
        ]
        print("hyprland computer-use doctor")
        for name, ok, detail in checks:
            print(f"  [{'ok' if ok else '!!'}] {name}: {detail}")
        optional = ("wl-copy", "magick (ruler/downscale)")
        required_missing = [name for name, ok, _ in checks if not ok and name not in optional]
        if not pointer.is_file():
            print(f"\nBuild the pointer helper: make -C {pointer.parent.parent}")
        passed = sum(1 for _, ok, _ in checks if ok)
        print(f"\n{passed}/{len(checks)} checks passed")
        return 0 if not required_missing else 1


def register(ctx) -> None:
    # `hermes plugins validate` probes register() with a generic context that does
    # not expose the computer-use seam yet; the loader's own context and the
    # provider discovery path both do. Keep discovery working in the probe.
    register_provider = getattr(ctx, "register_computer_use_provider", None)
    if register_provider is not None:
        register_provider(HyprlandProvider())
