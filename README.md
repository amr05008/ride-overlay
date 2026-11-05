# ride-overlay

Put ride data on your bike videos! 

This skill extracts data from your rides FIT file (you can get this from [Strava](http://strava.com/) or from your Bike computer) and renders power, heart rate and speed (by default) on your action camera footage using [HyperFrames](https://github.com/heygen-com/hyperframes) (HeyGen's open-source HTML-to-video renderer). You can customize what data fields appear in your overlays beyond the defaults and make further changes right from [Claude Code](https://claude.com/claude-code).

I built this to replace the stats overlay I was making by hand in Insta360 Studio. Now I drop a ride's clips and its FIT file in a folder and can prompt my way into getting ride data onto the right cuts of ride footage. 

Everything runs on your machine. HyperFrames renders locally with its telemetry turned off, and you don't need a HeyGen account.

## What's here

| file | what it is |
| --- | --- |
| `SKILL.md` | The Claude Code skill: how Claude runs the scripts, checks the output and handles the gotchas |
| `scripts/ride_overlay.py` | Folder mode, the front door: point it at a ride folder |
| `scripts/reel.py` | Renders one clip or window with the overlay (portrait, square on blur, or 4K landscape) |
| `scripts/layer.py` | Renders the overlay alone as a transparent 4K layer for an editor |
| `scripts/place_layer.py` | Puts that layer above your clips in DaVinci Resolve, through Resolve's MCP |
| `scripts/ride_data.py` | Lines the FIT up with each clip and turns it into one reading per second |
| `template/overlay.html` | The overlay itself: plain HTML and CSS, so you can restyle it |
| `tests/` | Checks on the data step and the framing |

## What you need

- macOS or Linux.
- [ffmpeg](https://ffmpeg.org) (`brew install ffmpeg` on a Mac).
- [uv](https://docs.astral.sh/uv/), which runs the Python scripts and fetches their one dependency, [fitdecode](https://github.com/polyvertex/fitdecode).
- [Node.js](https://nodejs.org), for `npx`. HyperFrames installs itself on first run, pinned to version 0.8.207.
- Claude Code, if you want to ask for videos in plain English. The scripts also run on their own.
- A ride:
  - **The camera's original video files**, not exports from the camera maker's app. Each clip records when it started, and that's how the overlay lines up with your ride.
    - I've tested this with an Insta360 GO Ultra. Any camera that records its start time in UTC should work.
    - Set the camera's clock before you ride. On the GO Ultra, connecting it to the Insta360 app does it.
    - If the clock was off, `--offset` corrects it.
  - **The ride's FIT file**, from your bike computer (I use a Hammerhead Karoo 2; Garmin and Wahoo files work the same way), or from Strava's **Export Original**.
    - Strava only gives you a FIT if a device recorded the ride. A ride recorded on the Strava phone app exports as GPX, with no power or heart rate, so it won't work.

One tip from my own rides: bike computers auto-pause when you stop, and record nothing while paused. Clips you film while standing still get no numbers, so roll while you're riding.

## Install

```sh
git clone https://github.com/amr05008/ride-overlay.git ~/repos/ride-overlay
mkdir -p ~/.claude/skills
ln -s ~/repos/ride-overlay ~/.claude/skills/ride-overlay
```

The symlink is what makes it a Claude Code skill. Skip it if you only want the scripts.

## Start here: one folder, one prompt

Put your clips and the FIT in one folder, then ask Claude Code:

> Make a Reel of my hardest 30 seconds from ~/Rides/prospect-park

Or run it yourself, starting with a report of what's in the folder:

```sh
cd ~/repos/ride-overlay/scripts
uv run --with fitdecode python -I ride_overlay.py ~/Rides/prospect-park --dry-run
```

The report looks like this (an illustration, not a real ride):

```
FIT  prospect-park.fit: 09:02:11 EST to 10:14:40 EST (1:12:29)
     records power, heart rate, cadence, speed
Clips (3):
  VID_20261103_091544_101.mp4      landscape 2688x1520     6:12  starts 09:15:44 EST  in the ride; renders as 16:9 (3840x2160)
  VID_20261103_093010_102.mp4      portrait  1520x2688     0:48  starts 09:30:10 EST  in the ride; renders as 9:16 (1080x1920)
  VID_20261103_101900_103.mp4      portrait  1520x2688     0:20  starts 10:19:00 EST  outside every ride (filmed off the bike, or the camera clock is off: try --offset)
Lines: power, heart rate, speed (any the FIT lacks are left out)
```

Then drop `--dry-run` to render. With no other options you get a Reel of your hardest 30 seconds by average power, across every clip. It's written to `renders/` inside your folder, along with three check frames and the numbers each one should show.

## Options

| option | what it does |
| --- | --- |
| *(none)* | The hardest 30 seconds across all your clips, in the shape you shot it: 1080×1920 for portrait, 4K 16:9 for landscape |
| `--start 102@15` | You pick the moment: clip 102, from 15 seconds in. Any unique part of the file name works |
| `--seconds 20` | Reel length |
| `--square` | Put a landscape clip on a 1080×1920 vertical frame, as a square crop over a blurred copy of itself |
| `--full` | Every clip, whole, with the overlay, each in its own shape |
| `--layer` | A transparent 4K overlay layer for each landscape clip, for your editor |
| `--fields hr,speed,cadence,time` | Which lines show under power (default `hr,speed`) |
| `--units mph` | Speed in mph instead of km/h |
| `--offset -3600` | Seconds to add to every clip's start time, if the camera clock was wrong |
| `--dry-run` | Report what's in the folder and stop |

## The default overlay

A stack of numbers in a serif font, bottom-left, white with a dark outline and no box behind it: power, then heart rate, then speed. The numbers update once a second, like a bike computer. Power is a 3-second average.

It sits where a vertical video's caption won't cover it. On a 16:9 frame it's in the middle third, so the numbers survive if you crop the video for Instagram later.

If your FIT is missing something (no heart-rate strap, no power meter), that line is simply left out.

**How a clip gets framed:**
- **Every clip keeps the shape you shot it in.** Portrait clips fill a 1080×1920 frame, and landscape clips fill a 4K 16:9 frame. The report tells you which you'll get before anything renders.
- **A landscape clip that has to fill a vertical post** can use `--square`, which makes it a square crop on a blurred copy of itself. A straight 9:16 crop keeps only the middle third of a 16:9 frame, and it looks too zoomed in.

To restyle it:
- Ask Claude ("make the numbers bigger", "switch to mph", "add cadence").
- Or edit `template/overlay.html`; it's ordinary HTML and CSS.
- To watch changes live, open any render's project in HyperFrames' preview:

```sh
cd ~/Rides/prospect-park/ride-overlay/<project> && npx hyperframes@0.8.207 preview
```

## How it works

1. `ride_data.py` reads the FIT file and lines it up with each clip using the clip's recorded start time. It produces one reading per second of video.
2. ffmpeg cuts the part of the clip you asked for, which also applies the camera's rotation.
3. The script writes a small HyperFrames project (your footage plus `template/overlay.html`), checks it with `hyperframes check`, and renders it.
4. It saves three frames from the result and prints what the overlay should read in each, so you can check the sync. If your bike computer's screen is in the shot, the two should agree.

## Using an editor instead

If you cut your videos in an editor, `--layer` renders just the overlay, transparent, for the full length of each raw clip. Put it on the track above the clip with the same in and out points and the numbers stay in sync through your cuts.

- **The file:** 4K QuickTime Animation, about 0.5 GB for 7 minutes, which DaVinci Resolve reads with its transparency intact.
- **In Resolve:** `scripts/place_layer.py` does the placement through Resolve's MCP. `SKILL.md` has the steps.
- **One limit:** the layer doesn't follow speed ramps or zooms you add in the editor.

## Speed

Timed on an M3 Pro MacBook:

| render | time |
| --- | --- |
| A 30-second Reel from a portrait clip | about 30–55 seconds |
| A 30-second Reel from a 16:9 clip at 4K | about 2 minutes |
| A transparent 4K layer | about real time |
| A whole 16:9 clip at 4K with the footage | about 4–5× the clip's length |

The full-length 4K render is the slow one. HyperFrames draws every frame in a browser, and 4K footage is a lot of pixels to push.

## Known limits

- Tested with an Insta360 GO Ultra and a Hammerhead Karoo 2. Other cameras and head units should work, but I haven't tried them.
- No route map yet. I built one and took it out; the numbers alone read better.
- A clip filmed during an auto-pause gets no data.

## Tests

```sh
cd ~/repos/ride-overlay
uv run --with fitdecode python -m unittest discover tests
```

## Credits

[HyperFrames](https://github.com/heygen-com/hyperframes) by HeyGen does the rendering (Apache-2.0). [fitdecode](https://github.com/polyvertex/fitdecode) reads the FIT files. The overlay uses EB Garamond, which ships with HyperFrames.

## License

MIT
