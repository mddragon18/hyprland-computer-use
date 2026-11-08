# Hyprland computer use for Hermes

`hyprland` is a Hermes `computer_use` provider for Hyprland. It uses
Wayland-native protocols only:

- `grim` (wlr-screencopy) for screen capture
- `wlr-virtual-pointer` for clicks, drags, and scrolling
- `wtype` for text and key input
- `hyprctl` for window metadata and focus

It does not require XWayland, an accessibility tree, root, or `/dev/uinput`.

The backend is pixel-based: actions take coordinates read from a screenshot.
Captures carry a coordinate ruler, and the backend maps image pixels back to
native pixels, so the model works in the screenshot's coordinate space.

## Requirements

Runtime:

- Hyprland, with `HYPRLAND_INSTANCE_SIGNATURE` set
- [`grim`](https://github.com/emersion/grim) — screen capture
- [`wtype`](https://github.com/atx/wtype) — text and key injection
- [`wl-clipboard`](https://github.com/bugaevc/wl-clipboard) (`wl-copy`) — paste
  fallback for text that starts with `-`
- `hyprctl` — window list, geometry, focus (ships with Hyprland)
- ImageMagick (`magick`) — optional; downscaling and the coordinate ruler

Build:

- a C compiler (`cc`), `make`, `pkg-config`, and the `wayland-client`
  development headers

On Arch:

```sh
sudo pacman -S --needed base-devel pkgconf wayland grim wtype wl-clipboard imagemagick
```

The provider is developed and tested against Hyprland 0.56.2.

## Build the pointer helper

The pointer helper is C source and must be built locally; the plugin catalog
does not accept committed binaries.

```sh
make -C plugin/hyprland/pointer
```

This produces `plugin/hyprland/pointer/bin/hypr-vinput`, which is gitignored.
If the plugin was installed from the catalog, build in the installed copy:

```sh
make -C ~/.hermes/plugins/hyprland/pointer
```

Verify the toolchain first if needed:

```sh
pkg-config --exists wayland-client && echo ok
```

## Install

### From a checkout

```sh
./install.sh
```

The script builds the pointer helper, links `plugin/hyprland` into
`~/.hermes/plugins/hyprland`, and prints the configuration snippet.

### From the catalog

```sh
hermes plugins install hyprland
make -C ~/.hermes/plugins/hyprland/pointer
```

### Manual

```sh
ln -sfn "$PWD/plugin/hyprland" "$HOME/.hermes/plugins/hyprland"
make -C "$PWD/plugin/hyprland/pointer"
```

## Configure

`~/.hermes/config.yaml`:

```yaml
platform_toolsets:
  cli:
    - ...
    - computer_use          # expose the computer_use toolset to the agent
    - ...

computer_use:
  backend: hyprland
  hyprland:
    capture_width: 1600     # screenshot width / click space (default 1600)
    grid: true              # draw the coordinate ruler (default true)
    ruler_step: 200         # image px between ruler labels (default 200)
    scope: screen           # screen | window (follow the focused window)
    enforce_target: true    # refuse input outside the last captured window
    # pointer_bin: /path/to/hypr-vinput
```

Then check:

```sh
hermes computer-use doctor
hermes tools list | grep computer_use
```

`pointer_bin` can also be set with `HYPRLAND_CU_POINTER_BIN`, or a
`hypr-vinput` can be placed on `PATH`. Resolution order: config, environment,
bundled `pointer/bin/hypr-vinput`, `PATH`.

## How it works

| job | mechanism |
|---|---|
| capture | `grim` (wlr-screencopy), optionally cropped to the target window |
| click / drag / wheel | `hypr-vinput` (wlr-virtual-pointer-unstable-v1), built from `pointer/` |
| text | `wtype`; `wl-copy` + Ctrl+V fallback |
| keys | `wtype -M/-k/-m` |
| window list / geometry | `hyprctl clients/monitors/activewindow -j` |
| focus | `hyprctl repl 'hl.dispatch(hl.dsp.focus({window="address:0x…"}))'` |

Each input batch is a short-lived helper process. There is no daemon, no
background service, and no persistent device.

## Window targeting

`capture` accepts `app`, `pid`, or `window_id` (hex from `list_windows`, or its
decimal value). The backend focuses that window, crops the frame to it, and
makes it the input target:

```jsonc
{"action": "capture", "app": "com.nousresearch.hermes"}
```

The reply's note reports the window and its native geometry instead of the
whole screen. A window crop preserves the window's native resolution; a
full-screen capture downscales every window in it.

Input is checked against that window. `click`, `drag`, and `scroll` refuse a
coordinate outside it and return `code: target_mismatch`, together with the
window's native box and its span in the current screenshot. This turns a
mis-aimed click on a tiled desktop into a retryable error.

`delivery_mode: foreground` or `bring_to_front` focuses the target before the
event. Injection is always real input, so `background` delivery is a no-op. Set
`enforce_target: false` for a gesture that intentionally crosses windows, such
as dragging between two applications.

## Limitations

- **Pixel-only.** There is no element tree; actions take `coordinate=[x, y]`.
- **Modifier+click and modifier+drag are not supported.** Holding a key across
  a pointer event requires `/dev/uinput`, which this backend avoids. Use `key`
  for shortcuts followed by a plain click, or a different backend for that
  action.
- **Drag** is press, interpolated motion, then release inside one helper
  process. It supports text selection and common drag-and-drop gestures.
  Cross-window drags require `enforce_target: false`.
- **Multi-monitor** uses the layout bounding box. Negative-origin layouts are
  not verified.
- Without `app`, `pid`, or `window_id`, a capture follows the focused window, or
  the whole layout with `scope: screen`. On a tiled desktop, name the target
  window explicitly; two windows in one 1600-px frame reduce the legibility of
  both.
- `scope: window` follows the focused window. Separate dialogs are captured in
  `scope: screen` or by naming their window.
- Text goes to the focused surface. Call `focus_app` first, or pass
  `delivery_mode: foreground`, when the focus is uncertain.

## Disclosures

- **Real input injection.** The plugin moves the pointer, clicks, drags,
  scrolls, types, and presses keys on the live session. There is no sandbox and
  no synthetic-only mode.
- **Screen capture.** Every `capture` reads the screen through `grim` and sends
  the image to the model configured in Hermes.
- **Shell commands.** It runs `hyprctl`, `grim`, `wtype`, `wl-copy`, `magick`,
  and the locally built `pointer/bin/hypr-vinput`. All calls use fixed argv; no
  shell is spawned.
- **No network, telemetry, or credentials.** The plugin makes no network
  requests, stores no data, and reads no credential store. It reads only
  `computer_use.hyprland` through Hermes's configuration API.
- **No root and no `/dev/uinput`.** The pointer helper connects to the
  compositor over the Wayland socket with the same permissions as any client.
- **No self-update.** Updates arrive only through a new catalog pin or a manual
  `git pull`.

## Development

`tests/smoke.py` at the repository root exercises the provider directly. Run it
with the Hermes runtime:

```sh
HERMES_HOME=$HOME/.hermes \
  ~/.hermes/tools/python-3.14*/bin/python3 tests/smoke.py doctor
```

Test results are recorded in `REPORT.md`.

## Troubleshooting

| symptom | fix |
|---|---|
| `pointer helper missing` | `make -C ~/.hermes/plugins/hyprland/pointer` |
| `compositor does not advertise zwlr_virtual_pointer_manager_v1` | the Hyprland build lacks wlr-virtual-pointer; this backend requires it |
| capture is black or stale | `grim` cannot capture a hidden or scratchpad window; focus or raise it first |
| `grim did not produce a frame within 10 s` | the output is asleep (`hyprctl monitors -j` → `dpmsStatus: false`); wake the monitor and retry |
| clicks land in the wrong tile | pass `app=` or `window_id=` to `capture`, keep `enforce_target: true`, and use `delivery_mode: foreground` |
| `hyprctl repl` errors on Hyprland 0.56+ | expected: the backend uses the Lua REPL (`hyprctl repl`), not `hyprctl keyword` |
