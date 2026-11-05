---
name: ride-overlay
description: Put a ride-data overlay (power, heart rate, speed from a bike computer's FIT file) on action-camera footage with HyperFrames. Use when someone hands over a ride folder (camera clips plus the ride's FIT) and asks for a Reel or Short with their numbers on it, their hardest or highest-power 30 seconds, "ride-overlay this", whole clips with the overlay, or a transparent overlay layer for an editor such as DaVinci Resolve. Folder mode reports what's in the folder, then renders; every output is checked against the FIT.
compatibility: >-
  macOS or Linux with ffmpeg/ffprobe, uv (for Python and fitdecode), and Node.js with npx
  (HyperFrames 0.8.207, pinned). Footage on local disk. Placing layers in Resolve needs DaVinci
  Resolve Studio and its MCP. HyperFrames runs locally with DO_NOT_TRACK=1: no HeyGen account,
  no paid features.
---

# ride-overlay

Turns ride clips plus the ride's FIT file into videos with a data overlay, rendered with HyperFrames. Keep the default design unless the user asks for a change; change it in `template/overlay.html`.

## The overlay (defaults)

- **A left-aligned serif stack** (EB Garamond, which HyperFrames bundles): white with a dark outline, no backing. Numbers and units are the same size.
- **Position:** bottom-left of the 9:16 frame, just above the band Reels and Shorts cover with the caption. On a 16:9 frame that's the same spot in the middle third, which is what survives a vertical crop.
- **Lines, top to bottom:** power (W, a 3 s average), heart rate (bpm), speed (km/h). Cadence and time are off unless asked for. In folder mode, use `--fields hr,speed,cadence,time` and `--units mph`. The single-clip scripts take `--vars '{"showCadence":true,"units":"mph"}'`.
- **The numbers step once a second,** like a head unit. A stop reads 0 W and 0.0 km/h.
- **A field the FIT doesn't record is left out.** With no heart-rate strap there's no heart-rate line, and the report says so.

## Inputs

A folder holding:
- **The camera's original video files,** not exports from the camera maker's app. The sync uses each clip's recorded start (`creation_time`, UTC).
  - It's tested on the Insta360 GO Ultra. Any camera that records its start time in UTC should work.
  - If the camera's clock is off, use `--offset <seconds>`.
- **The ride's FIT file,** from the bike computer (Karoo, Garmin, Wahoo, and so on) or Strava's "Export Original".
  - Strava only gives a FIT if a device recorded the ride.
  - A phone recording comes out as GPX, with no power or heart rate, and isn't supported.

## Run it on a ride folder (folder mode)

This is the main way in. Do the `--dry-run` first, and tell the user what it found before rendering anything long.

```sh
cd ~/.claude/skills/ride-overlay/scripts
uv run -q --with fitdecode python -I ride_overlay.py "<folder>" --dry-run      # report only
uv run -q --with fitdecode python -I ride_overlay.py "<folder>"                # the hardest 30 s, as a Reel
uv run -q --with fitdecode python -I ride_overlay.py "<folder>" --start 100@764 --seconds 20
uv run -q --with fitdecode python -I ride_overlay.py "<folder>" --square       # a landscape clip on a vertical frame
uv run -q --with fitdecode python -I ride_overlay.py "<folder>" --full         # every clip whole, with the overlay
uv run -q --with fitdecode python -I ride_overlay.py "<folder>" --layer        # transparent layers for an editor
```

- **The report:**
  - For each FIT, what it covers and which fields it records. A missing field is called out, since that line will be left out.
  - For each clip: its shape, length, local start time, whether it has ride data, and the shape it renders as.
  - A clip can be **in the ride**; **during a pause** (the head unit auto-paused and recorded nothing); or **outside every ride** (off the bike, or the camera clock is off, so try `--offset`).
  - With several FITs, each clip is matched to the ride it falls in.
- **Default (no mode): a Reel** of the hardest `--seconds` (30) by average power, across every clip in the ride.
  - A power peak isn't always a good moment. When the user names one, use `--start CLIP@SECONDS`, where CLIP is any unique part of the file name.
- **Framing:**
  - A clip keeps the shape it was shot in, with its own sound, in a Reel and in `--full`. Portrait (taller than wide) fills a 1080×1920 frame. Anything else fills a 3840×2160 frame, centre-cropped if it isn't 16:9, and upscaled if it's smaller: 2.7K footage gains no detail.
  - In a folder of mixed shapes, a Reel takes the shape of whichever clip holds the hardest window. The report says what each clip renders as.
  - 4K is slow: about 4–5× the rendered length, against about 1× for portrait, so a 30 s landscape Reel takes about 2 minutes. `--full` prints an estimate first, so tell the user before a long one.
  - `--square` is for a landscape clip that has to fill a vertical post. It goes in as a square centre crop on a blurred, darkened copy of itself, at 1080×1920, named `<clip>-reel-<start>s-square.mp4`. A plain 9:16 crop of 16:9 footage keeps only the middle third and looks too zoomed in. A portrait clip is unchanged by it, and it can't be combined with `--full` or `--layer`.
  - `--layer` is for landscape clips only (see Editors below); it skips portrait clips.
- **Where things go:** outputs in `<folder>/renders/`. The HyperFrames projects stay in `<folder>/ride-overlay/`, where `npx hyperframes@0.8.207 preview` opens one for live tweaks.
- **Under the hood:**
  - The FIT is read once.
  - Each clip's window is cut with ffmpeg, which applies the camera's rotation and avoids HyperFrames proxying a multi-GB HEVC file.
  - Each project is linted with `hyperframes check` before it renders.
- **Single-clip scripts:** `reel.py <clip> <fit>` and `layer.py <clip> <fit>` do the same for one file. Folder mode calls them.

## Check before calling it done

The script saves three frames per output to `<project>/check/` and prints what the overlay should read in each. Look at every frame and confirm:
1. **The numbers match the printed values.**
2. **The data lines up with the picture.**
   - If the head unit's screen is in shot, it should agree, within a second or so.
   - At night, or with no screen in shot, line up a stop instead: the FIT's auto-pause should match the rider standing still on screen. A clock in frame also works.
3. **The overlay sits clear of the caption band** and reads against the footage behind it.

Then give the user the output path and say what's in the window.

## Gotchas

- **Use `creation_time`, not the file name.** File names are local time, and around a daylight-saving change they can be an hour off while `creation_time` stays right.
- **Auto-pause leaves gaps in the FIT.** `ride_data.py` holds the last value across a gap instead of ramping, so a stop doesn't show the rider creeping along. Clips filmed while stopped get no numbers at all.
- **"FIT has no records inside the clip"** (single-clip scripts) means the wrong FIT, a pause, or an unsynced camera clock. Folder mode reports this per clip instead of stopping.
- **The first HyperFrames run** downloads the pinned package. A render prints an upsell for HyperFrames' desktop app; ignore it.

## Editors: an overlay layer for DaVinci Resolve

For 16:9 videos cut in an editor, HyperFrames renders only the overlay; the editor keeps the footage, cuts, sound and export. A 4K HyperFrames render with the footage in it runs at about 7 frames a second, which is hours for a long ride.

1. **Render the layer:** `ride_overlay.py "<folder>" --layer` does every landscape clip, landing at `<folder>/renders/<clip>-layer.mov`.
   - It covers the whole raw clip at the clip's frame rate, so frame N of the layer is frame N of the clip.
   - It's 4K and transparent, in QuickTime Animation format, which is about 0.5 GB for 7 minutes. ProRes 4444 would be about 3 GB.
2. **Place it in Resolve:** read `scripts/place_layer.py`, fill in `RAW` (the camera original on the timeline) and `LAYER`, and pass the whole text to the Resolve MCP's `run_script` with the edit's timeline current.
   - For every piece of the raw clip on the timeline, it adds the layer on a new top video track with the same source frames, so cuts and trims carry over.
   - It reports any piece whose layer didn't line up, so check that `mismatched` is empty.
   - It doesn't follow speed changes or Transform zooms on the footage.
3. **Check:** for each test time, set the playhead to `piece.GetStart() + src − piece.GetSourceStartFrame()`, where `src = round(clip seconds × frame rate)`. Then `project.ExportCurrentFrameAsStill(path)`, and compare the numbers with the project's `ride.js` at that clip second.

**Resolve gotchas:**
- **If every call returns None or empty** (no current page, imports empty, `CreateProject` failing), Resolve is sitting at a startup dialog or the project manager. Ask the user to clear it; scripts can't.
- **Import with plain path strings:** `ImportMedia(["/path"])`. The `{"FilePath": ...}` form imports nothing.
- **PNG-in-MOV files import as opaque.** QuickTime Animation and ProRes 4444 import with "Straight" alpha.

## Files

- `scripts/ride_overlay.py`: folder mode, the main entry point.
- `scripts/reel.py`: renders one clip or window in a framing (`render()`), plus a single-clip CLI.
- `scripts/layer.py`: the transparent overlay layer (`make_layer()`), plus a single-clip CLI.
- `scripts/place_layer.py`: run inside Resolve; puts the layer above every piece of the raw clip.
- `scripts/ride_data.py`: FIT plus clip into per-second data.
- `template/overlay.html`: the overlay composition.
- `tests/`: checks on the data step and the framing. Run them with `uv run --with fitdecode python -m unittest discover tests`.
