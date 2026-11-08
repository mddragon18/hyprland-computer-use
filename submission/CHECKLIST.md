# Submission checklist

Deadline: **2026-11-11 17:00 EST** = **2026-11-12 03:30 IST**.
Nothing here needs to run on the live desktop except the demo recording.

## 1. Repository

- [ ] Create `github.com/mddragon18/hyprland-computer-use` as a **public** repo.
- [ ] Description: "Hyprland computer-use backend for Hermes — grim + wlr-virtual-pointer + wtype; no X11, AT-SPI, root, or /dev/uinput."
- [ ] Topics: `hermes`, `hyprland`, `wayland`, `computer-use`, `desktop-automation`.
- [ ] License visible as MIT (the `LICENSE` file is already in the tree).
- [ ] Confirm the tree contains no binaries or bytecode:

  ```sh
  git ls-files | grep -Ei '\.(pyc|pyo|so|o|a|dll|dylib)$|(^|/)bin/' || echo "clean"
  find . -name '__pycache__' -o -name '*.pyc'
  ```

  `plugin/hyprland/pointer/bin/` must be gitignored, not committed.

## 2. Clean build and validation

Run from a fresh clone, not the working tree:

```sh
git clone https://github.com/mddragon18/hyprland-computer-use /tmp/opencode/hcu-clean
cd /tmp/opencode/hcu-clean
hermes plugins validate plugin/hyprland          # must pass with no pointer/bin present
make -C plugin/hyprland/pointer                   # must build with no warnings
hermes plugins validate plugin/hyprland          # still passes with the binary present
```

- [x] `hermes plugins validate` passes both before and after the build.
- [x] No warnings on the compile line (`-Wall -Wextra`).
- [x] `hermes plugins doctor` reports no contract errors for `hyprland`.

## 3. Runtime verification

With the session environment:

```sh
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/1000/hypr | head -1)
hermes computer-use doctor                        # 9/9
plugin/hyprland/pointer/bin/hypr-vinput probe     # ok zwlr_virtual_pointer_manager_v1
```

- [x] Doctor is 9/9 (wake the monitor first; grim hangs on `dpmsStatus: false`).
- [x] Protocol probe succeeds.
- [x] One click, one drag, and one scroll are verified live after the 0.3.0
      change (they now all go through `hypr-vinput`; the old uinput daemon is
      gone). Results are recorded in `REPORT.md` §3.
- [x] Live-task results in `REPORT.md` are labeled with the version they ran on.

## 4. Commit and pin

```sh
git add -A
git commit -m "hyprland: 0.3.0 — self-contained pointer helper, no uinput"
git push origin main
git rev-parse HEAD        # full 40-character SHA
```

- [ ] `git status` is clean and the pushed tree matches the local tree.
- [ ] Put the full SHA into `submission/plugin-catalog/hyprland.yaml`.
- [ ] Re-run `hermes plugins validate` against a checkout at that exact SHA.
- [ ] If you add screenshots, pin their raw URLs to that SHA
      (`https://raw.githubusercontent.com/mddragon18/hyprland-computer-use/<sha>/docs/...`).

## 5. Catalog PR

Fork `NousResearch/hermes-agent`, then:

```sh
git checkout -b add-hyprland-computer-use
cp /path/to/submission/plugin-catalog/hyprland.yaml plugin-catalog/hyprland.yaml
git add plugin-catalog/hyprland.yaml
git commit -m "catalog: add hyprland computer-use provider"
```

PR body — say what it does, which Hermes surfaces it uses, and the rule 13
disclosures:

- **Surface:** `ctx.register_computer_use_provider()`; selected with
  `computer_use.backend: hyprland`. No tools, hooks, middleware, env vars, or
  Python dependencies.
- **Shell commands:** `hyprctl`, `grim`, `wtype`, `wl-copy`, `magick`, and the
  locally built `pointer/bin/hypr-vinput`. Fixed argv, no shell.
- **Real input and capture:** moves/clicks/drags/types on the live session and
  sends `grim` screenshots to the configured model.
- **No network, telemetry, credentials, stored data, or background daemons.**
- **Local build:** the pointer helper is C source and must be built with
  `make -C ~/.hermes/plugins/hyprland/pointer` (rule 17: no committed binary).
- **No self-update:** updates arrive only through SHA-bump PRs.
- **Limitations:** pixel-only, no modifier+click or modifier+drag (would need
  `/dev/uinput`), multi-monitor uses the layout bounding box.

- [ ] Catalog CI is green.
- [ ] `subdir: plugin/hyprland` resolves and the README renders at the pinned SHA.
- [ ] `version: "0.3.0"` matches `plugin.yaml`.
- [ ] `requires_hermes: ">=0.23.0"` matches `plugin.yaml`.

## 6. Demo

- [ ] Record from `docs/DEMO.md`; final file is **under 90 seconds**.
- [ ] Wake the monitor first (`dpmsStatus: true`) or grim hangs.
- [ ] No credentials, notifications, or personal files on screen.
- [ ] Upload the video and keep a second copy as a GitHub release asset.
- [ ] Post on X with `submission/X-POST.md`, tagging `@NousResearch`.
- [ ] Fill in the hackathon submission form with the repo, catalog PR, and video
      links before the deadline.

## 7. Final read-through

- [x] `plugin/hyprland/README.md` matches the shipped code (no uinput daemon,
      build step present, disclosures complete).
- [x] `README.md`, `REPORT.md`, and `docs/DEMO.md` agree on version and results.
- [x] `install.sh` works from a clean clone.
- [ ] `submission/plugin-catalog/hyprland.yaml` has a real SHA, not the placeholder.
- [x] No stale references to the retired protocol-probe directory.
