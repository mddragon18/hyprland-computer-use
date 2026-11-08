# 90-second demo

The video must stay under 90 seconds. Record a real agent task, then compress
the waiting. A 6-call task on a slow local model can take several minutes; show
it at 8–16× with an honest speed label and a call counter.

Record at 1080p:

```sh
gpu-screen-recorder -w screen -f 60 -s 1920x1080 -o docs/demo-hyprland.mp4
# stop with: pkill -SIGINT gpu-screen-recorder
```

Keep the cursor visible. Rehearse once and pre-warm the model before the take.

## Storyboard

| time | picture | on-screen text / narration |
|---|---|---|
| 0:00–0:06 | Title over a Hyprland desktop with the terminal and Brave tiled | **"Computer use on Hyprland. No X11. No overlay. No root."** |
| 0:06–0:14 | Terminal: `hermes computer-use doctor` | Nine green checks; hold on `wlr-virtual-pointer: ok`. Narration: "grim for capture, wlr-virtual-pointer for input, wtype for text." |
| 0:14–0:20 | Terminal: `make -C plugin/hyprland/pointer`, then `ls pointer/bin` | "The pointer helper is built from source; no binary is committed." |
| 0:20–0:28 | Terminal: `python3 -m http.server 8000 -d docs`; Brave already open on `http://localhost:8000/demo-form.html` | "A local form. Everything after this is the agent using pixels and synthetic input." |
| 0:28–0:36 | Hermes chat; prompt typed | Prompt: **"Use only computer_use. Capture the Brave window, click Full name and type Ada Lovelace, select Team, click Submit registration, then capture the confirmation."** |
| 0:36–0:44 | First `capture` tool call; note shows the Brave window geometry | "Capture is scoped to the named window, not the whole tiled screen." |
| 0:44–1:08 | **8–16× timelapse** of the real run: click, type, select, submit; call counter overlay | "Six computer_use calls, real input, no accessibility tree, no XWayland, no uinput." |
| 1:08–1:20 | Final capture showing **Response recorded** | "The confirmation is read back from a fresh capture." |
| 1:20–1:30 | End card | **"github.com/mddragon18/hyprland-computer-use"** · `hermes plugins install hyprland` |

## Narration

> Hyprland is Wayland-only. This provider uses the protocols Hyprland actually
> exposes: grim for capture, wlr-virtual-pointer for clicks, drags, and
> scrolling, wtype for text.
>
> Captures can be scoped to a named window, so the agent works on that window
> and not on the application next to it.
>
> Here the agent fills and submits a local form in six computer_use calls:
> capture, click, type, select, submit, and a final capture to confirm.

## Keeping the run short

The model is the slow part, so reduce calls rather than pixels:

- Use the six-call prompt above; do not ask for verification captures between
  every step.
- Pre-open Brave on the form and position both windows before recording.
- Pre-warm the model with a one-line prompt so the first recorded call does not
  include weight loading.
- If calls still take minutes, set `capture_width: 1200` for the demo and use
  `scope: window`. Fewer image tokens reduce prefill time, at the cost of some
  grounding precision.
- Record at real speed; apply the speed-up in the edit and label it. Do not
  fabricate the task or the confirmation.

## Before recording

- Wake the monitor and confirm `hyprctl monitors -j | jq '.[0].dpmsStatus'` is `true`; grim hangs on a sleeping output.
- Close notifications and anything with credentials on screen.
- Use a throwaway Hermes profile (`--profile task-demo`), not your main one.
- Keep the terminal and Brave side by side so the window-scoped capture visibly excludes the terminal.
- Clear the form before the take so the confirmation is unambiguous.

## Upload

- Post the video on X with the draft in [`X-POST.md`](X-POST.md), tagging `@NousResearch`.
- Keep the file under X's limit; 1080p60 H.264 at ~8 Mbps is sufficient for 90 seconds.
- Upload the same file as a GitHub release asset and put that link in the submission form as a fallback.
