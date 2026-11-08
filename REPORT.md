# Hyprland computer use — hackathon result

The `hyprland` provider is a working Hermes computer-use backend for
Hyprland/Wayland. The earlier Google Form failure was **not** the injection
layer: with the plugin installed, the wrong tool was the one on the other side
of the screen — the local model's pixel grounding and its self-diagnosis.
A later Electron task did expose real capture/targeting gaps in the backend;
those are fixed in 0.2 (§5).

Demo frames: `docs/demo-claude-selected.png` (selected by run C),
`docs/demo-perplexity-selected.png` (selected end-to-end by run D, 3 calls,
40 s).

## 1. Native CUA on Hyprland is broken

| attempt | result |
|---|---|
| `computer_use.backend: cua` | `get_desktop_state` → `X11 Error Match`; the driver only lists its own overlay window |
| `cua` + `computer_use.native_wayland: true` | capture works, but one `click` maps a fullscreen `Cua.AgentCursorOverlay` that blacks out the screen and swallows input; `set_agent_cursor_enabled(false)` does not remove it |
| foreign-toplevel geometry | reports `0,0 1866x1016`, `z_index: null` for a window that is really `12,47 2536x1381` |

So the failure everyone saw was a Wayland integration gap, not a model problem.

## 2. What `hyprland` uses instead

All Wayland-native, no X11, no CUA binary, no overlay, no accessibility tree:

| job | mechanism |
|---|---|
| capture | `grim` (wlr-screencopy) |
| click / drag / wheel | `hypr-vinput` (wlr-virtual-pointer-unstable-v1), built locally from `plugin/hyprland/pointer/` |
| text | `wtype`; `wl-copy` + Ctrl+V fallback |
| keys | `wtype -M/-k/-m` |
| window list/focus | `hyprctl clients/monitors/activewindow -j`, `hl.dsp.focus` |

The capture is downscaled to 1600 px and stamped with a coordinate ruler, and
**image pixels are the declared click space**. The backend scales back to native
(1.6x here), so the model never does scale arithmetic. The ruler is not
decoration: without it, a first manual run missed a radio by 34 px because the
model's provider had downscaled the screenshot again.

## 3. Verification ladder

| rung | result |
|---|---|
| `hermes computer-use doctor` | 9/9 checks at the time; 9 checks now (uinput removed, `hyprctl` + protocol probes added) |
| backend direct: focus, capture, click, scroll, Ctrl+L + type + Return | pass (`image 551,473` → native `882,757`; ChatGPT radio selected) |
| real tool dispatcher (`handle_computer_use`) | `capture` returns multimodal 1600x900; `click` returns `ok: true` and the radio visually changes |
| manual mission | filled and submitted the real 10-question Google Form; `Your response has been recorded` |
| local model, loose prompt | see §4 — thrash |
| local model, strict prompt | on-target click in 2 calls; see §4 |
| **0.2.0 live pet task** | **pass** — model enabled the `nukey` pet in 30 `computer_use` calls / 10.3 min; capture scoped to `window='Hermes'`; ground truth `profiles/task-dump/config.yaml` → `pet.enabled: true`, `slug: nukey` |
| **0.3.0 live scroll + drag** | **pass** — window-scoped capture of a scratch Ghostty, `scroll up x5` moved the viewport 5 lines, `scroll down x5` returned to the tail; `drag (100,230) → (700,560)` selected lines 170–188. One code fix was required: `wl_pointer.axis` vertical is `0` (the helper sent `1`, horizontal) and a wheel notch is `10.0` axis units |

## 4. Model vs tooling, with numbers

All runs: `qwen3.8-flash-next-gyro-gyro-m` on LM Studio, vision on, ~275 image
tokens per capture, 12–106 s per model call.

| run | prompt | computer_use calls | outcome |
|---|---|---|---|
| A 21:11 | "click Claude, verify" | 23 (12 min, killed) | first click `image 527,538` = **one radio row low** (Claude is at y≈506); then `86,860`, `1492,43`, Tab/arrow experiments; concluded "page content clicks don't register" (false — URL-bar click worked); eventually selected Claude at 21:23 with a label double-click `image 583,508` |
| B 21:16 | same | 10 (killed) | repeated the same one-row-low miss (`513,537`), never selected anything |
| C 21:23 | "exactly 3 calls: capture, click Claude's centre, capture" | 2 | found Claude at `image 560,508` (centre is 550,506) and clicked it; interrupted by my own gateway restart before the final text |
| D 21:27 | "exactly 3 calls: capture, click **Perplexity**'s centre, capture; never submit" | 3 | clicked `image 575,540` → native `(920,864)`; Perplexity selected; replied `perplexity_selected: yes` in ~40 s |
| control | direct backend/tool calls | — | click at `551,473` selected ChatGPT exactly; `Ctrl+L` + typing + `Return` navigated away and back |

Run D is the end-to-end proof: a different radio, chosen by name, clicked at
`y=540` against a row centre of `538`, confirmed by the model's own follow-up
capture and by an independent `grim` screenshot. Cost: 3 captures ≈ 800 image
tokens, 40 s wall clock.

What the sessions prove:

- **Transport is sound.** The same backend, driven directly, lands clicks to the
  pixel across the whole screen; every tool call returned `ok: true` with the
  expected native coordinate. The model's own logs confirm a URL-bar click at
  `image 356,85` worked, so the click path was never broken.
- **Grounding is the weak link — and it is fixable in the prompt.** Loose
  prompts produced a stable *one-row-low* bias (31 px image ≈ 50 px native) and
  10–23 calls of thrash. With a 3-call budget and an explicit "image pixels"
  instruction, run D read Perplexity at `y=540` (true `538`) and finished in 40 s.
- **Self-diagnosis amplifies it.** The model decided "page clicks don't reach
  Chromium" from three misses, then spent most of its budget on Tab/arrow-key
  workarounds and DOM-free guesses instead of re-reading the ruler.
- **The screenshot is doing its job.** With labels every 200 px, the strict
  runs' estimates sit within 2–10 px of the row centre; interpolation is the
  remaining error source.

## 5. The Hermes-desktop pet session: what the tooling got wrong

On 2026-11-06 22:05 the same provider was asked to "enable a pet" in the Hermes
desktop app (`local-7eab…`; 180 messages, 89 tool calls — 79 `computer_use`,
9 `terminal`, 1 `execute_code`). It ran 33 minutes and never found the Pets
toggle. This is the most useful failure so far because the target is Electron,
the screen was two tiled windows, and every wrong click is visible in the
captures.

Layout: Hermes `1287,47 1261x1381`, Ghostty `12,47 1261x1381`; the full layout
`2536x1381` was scaled to `1600x900`, so each window was only ~795 px wide.

Four tooling gaps, all now fixed:

1. **`capture(app=/pid=/window_id=)` was ignored.** Calls 9–13 asked for the
   Hermes window by hex id, app name, pid, then by the hex id converted to
   decimal (`94045753158288`); every one returned the focused Ghostty window or
   the whole screen and reported `app=com.mitchellh.ghostty`. After `focus_app`
   (call 14) the note finally read `app=com.nousresearch.hermes window='Hermes'`,
   but the frame was still the full `2536x1381` layout: the label no longer
   described the image, and the model read coordinates across both windows
   (click `[846,805]` → native `1354,1288`). Fix: resolve
   `app`/`pid`/hex-or-decimal `window_id`, focus that window, crop to it, and say
   `window '…' at native …` instead of `screen at native …`.

2. **No input-target guard.** Click `[743,267]` mapped to native ≈`1189,427` —
   Ghostty, since Hermes starts at x=1287 — and was retried at `[745,264]` and
   `[743,267]`. An Electron modal closes when its window loses focus, so the
   Settings dialog disappeared each time. Fix: `click`/`drag`/`scroll` refuse a
   coordinate outside the captured window (`code: target_mismatch`) and report
   the window's native box and its span in the current screenshot.

3. **`delivery_mode: foreground` was a placebo.** The model missed a few
   background clicks, concluded only foreground delivery worked, and spent calls
   27–34, 46, 48–49, 53, 55–56, 60, 62–63, 65, 68–70, 73, 75, 78, 81–83 and 88
   on that theory. Fix: foreground/bring_to_front now focuses the target window
   before the event, so the option has a real effect.

4. **Scroll had no guaranteed pointer target.** Wheel events go to the surface
   under the pointer, and after an instantaneous warp the pointer may not have
   entered it yet; scrolls at calls 61, 65 and 66 did nothing. Fix: warp to the
   requested point, emit a real 3 px motion and back, then the wheel.

The model-side failures are separate and no backend can absorb them:

- It decided at 22:10 that screenshots were not reaching it and switched to
  `magick` crops + `tesseract` (calls 19–21), until the user interrupted with
  "Please only use screenshots" (and again at 22:29, "are you using screenshots
  or not"). Images *were* being delivered.
- Split-screen misreads: it repeatedly read the Ghostty half as Hermes and the
  Hermes half as Ghostty (own notes at 22:09:52 and 22:10:37), then misjudged the
  "Pets" row, and diagnosed "clicks aren't registering" instead of re-reading the
  frame.
- Each wrong diagnosis cost 5–10 calls: "background delivery isn't landing",
  "the panel didn't scroll", "Enter fired it as a plain message", "the composer
  flipped into command-chip mode".

Expected effect on this exact task: `capture(app="com.nousresearch.hermes")`
returns a `1261x1381` crop at 1:1 (nearly twice the width of the ~795 px half it
had), the wrong-half click is rejected with the window box, foreground delivery
really focuses, and the Pets pane scrolls. It does not make the model ground a
small sidebar row perfectly; it removes the failure modes that made the session
unrecoverable.

Verification: `py_compile` only. No desktop tests were run while Hermes was in
active use.

## 6. Reproduce

```sh
./install.sh                                  # build pointer helper + symlink into ~/.hermes/plugins
# config: computer_use.backend: hyprland, computer_use in platform_toolsets.cli
hermes computer-use doctor
HERMES_HOME=~/.hermes ~/.hermes/tools/python-3.14.9+*/bin/python3 tests/smoke.py doctor
HERMES_HOME=~/.hermes ~/.hermes/tools/python-3.14.9+*/bin/python3 tests/smoke.py capture /tmp/cap.png
```

Config knobs (`computer_use.hyprland`): `capture_width` (1600), `grid` (true),
`ruler_step` (200; 100 for finer vertical reading), `scope` (`screen`|`window`),
`enforce_target` (true), `pointer_bin`.

0.3.0 removes the `/dev/uinput` daemon entirely: clicks, drags, and the wheel
all go through the wlr-virtual-pointer helper, which is compiled locally because
catalog rule 17 forbids committed binaries. Modifier+click is therefore
unsupported (holding a key across a pointer event needs uinput); use `key` plus a
plain click instead.

For an app-scoped task, name the window on the first capture so the frame and the
click target are the same rectangle:

```
Use ONLY computer_use. Work only inside the Hermes desktop window.
(1) capture app="com.nousresearch.hermes" mode=vision.
    The note must say window '…', not screen. If it does not, say so and stop.
(2) Every click coordinate is in that screenshot's image pixels.
    If a click returns target_mismatch, re-read the window box in the error
    instead of guessing.
(3) capture app="com.nousresearch.hermes" mode=vision to confirm each change.
```

The prompt shape that worked (run D):

```
Use ONLY computer_use. Make exactly 3 computer_use tool calls, no more.
(1) capture mode=vision.
(2) In the question '<question text>' click the radio labelled '<answer>'
    using its centre coordinate in the screenshot's own image pixels.
    Do not scroll.
(3) capture mode=vision to confirm. Never press Submit.
Then reply with the window title and '<answer>_selected: yes|no'.
```

## 7. Next

- ~~Re-run the pet task once the desktop is free~~ — **done 2026-11-07**. The
  model opened Settings → Appearance → Pet and enabled `nukey`, confirmed from
  `profiles/task-dump/config.yaml` (`pet.enabled: true`). The acceptance half
  that matters for this plugin held: the first capture was
  `app=com.nousresearch.hermes` → `window='Hermes'`, not the neighbouring
  Ghostty tile. Notes for the next run: it took 30 calls / 10.3 min, clicked the
  gear that opens the sidebar before finding Settings, and needed
  `delivery_mode: foreground` before clicks landed.
- Halve the ruler step (or crop-and-zoom on a region) to remove the remaining
  one-row ambiguity for small radios.
- Give the model an explicit "you are pixel-only, there are no elements" line in
  the tool description *before* the first call, so `mode=ax` /
  `delivery_mode=foreground` detours do not consume the budget.
- Say in the task prompt that captures are attached as images. The pet session
  lost six calls to `tesseract` because the model decided (wrongly) that they
  were not.
- Keep the call budget in the task prompt; it changed behaviour from 23 calls of
  thrash to 2 calls and an on-target click.
