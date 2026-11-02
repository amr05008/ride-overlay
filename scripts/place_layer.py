"""Place the overlay layer above its raw clip on the current Resolve timeline.

Runs inside the Resolve MCP's run_script, where `resolve` is pre-injected and os/sys are blocked:
read this file, fill in RAW and LAYER, and pass the text as the script. For every piece of RAW on
the timeline's video tracks (so cuts and trims carry over), it adds the layer on a new top video
track with the same source frames at the same record frame; the layer was rendered against the
whole raw clip (layer.py), so frame N of one is frame N of the other. A new track means titles
already on V2 are left alone. It doesn't follow speed changes or Transform zooms on the footage.
"""
RAW = "/path/to/VID_....mp4"  # the camera original on the timeline
LAYER = "/path/to/VID_....-layer.mov"  # from layer.py

proj = resolve.GetProjectManager().GetCurrentProject()
mp = proj.GetMediaPool()
tl = proj.GetCurrentTimeline()


def clips(folder):
    for c in folder.GetClipList() or []:
        yield c
    for sub in folder.GetSubFolderList() or []:
        yield from clips(sub)


def find(path):
    return next((c for c in clips(mp.GetRootFolder()) if c.GetClipProperty("File Path") == path), None)


def span(item):
    return {"start": item.GetStart(), "end": item.GetEnd(), "src": [item.GetSourceStartFrame(), item.GetSourceEndFrame()]}


# Import with a plain path string: the dict form ({"FilePath": ...}) imports nothing here.
layer = find(LAYER) or (mp.ImportMedia([LAYER]) or [None])[0]
pieces = []
for t in range(1, tl.GetTrackCount("video") + 1):
    for item in tl.GetItemListInTrack("video", t) or []:
        mpi = item.GetMediaPoolItem()
        if mpi and mpi.GetClipProperty("File Path") == RAW:
            pieces.append(item)

if layer is None or not pieces:
    result = {"error": "layer not imported" if layer is None else "no pieces of RAW on this timeline", "timeline": tl.GetName()}
else:
    tl.AddTrack("video")
    track = tl.GetTrackCount("video")
    tl.SetTrackName("video", track, "ride overlay")
    placed, mismatched = [], []
    for item in pieces:
        new = mp.AppendToTimeline(
            [
                {
                    "mediaPoolItem": layer,
                    "startFrame": item.GetSourceStartFrame(),
                    "endFrame": item.GetSourceEndFrame(),
                    "trackIndex": track,
                    "recordFrame": item.GetStart(),
                    "mediaType": 1,
                }
            ]
        )
        got = span(new[0]) if new else None
        placed.append({"footage": span(item), "layer": got})
        if got != span(item):
            mismatched.append(placed[-1])
    result = {"timeline": tl.GetName(), "track": track, "pieces": len(pieces), "placed": placed, "mismatched": mismatched}
