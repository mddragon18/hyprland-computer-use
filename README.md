# Hyprland computer use for Hermes

A native Hermes `computer_use` provider for [Hyprland](https://hyprland.org/).
It drives the desktop through Wayland-native protocols, without XWayland, an
accessibility tree, root, `/dev/uinput`, or a cursor overlay.

The provider lives in [`plugin/hyprland`](plugin/hyprland). See
[`plugin/hyprland/README.md`](plugin/hyprland/README.md) for requirements,
configuration, disclosures, and limitations.

```yaml
computer_use:
  backend: hyprland
```

## Capabilities

| job | mechanism |
|---|---|
| capture | `grim` (wlr-screencopy), optionally cropped to a named window |
| click / drag / wheel | `hypr-vinput` (wlr-virtual-pointer), built locally from `pointer/` |
| text / keys | `wtype` |
| window list / focus | `hyprctl` |

Captures carry a coordinate ruler, and the backend maps image pixels to native
pixels. Window-scoped captures establish an input target: `click`, `drag`, and
`scroll` outside that window are refused with `target_mismatch` instead of
landing in a neighbouring application.

## Quick start

```sh
make -C plugin/hyprland/pointer
./install.sh
```

Set `computer_use.backend: hyprland` in `~/.hermes/config.yaml`, add
`computer_use` to `platform_toolsets.cli`, then verify:

```sh
hermes computer-use doctor
```

## Layout

```
plugin/hyprland/          provider, backend, manifest, and documentation
plugin/hyprland/pointer/  C source for the Wayland pointer helper and Makefile
tests/smoke.py            direct provider smoke tests
docs/                     demo video, storyboard, and screenshots
submission/               catalog entry and submission checklist
REPORT.md                 test log and result analysis
```

## License

MIT. See [`LICENSE`](LICENSE).
