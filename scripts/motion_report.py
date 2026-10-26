"""Measure how much a rendered video moves, and make a contact sheet of mid-scene frames.

    PYTHONPATH=. python scripts/motion_report.py --video generated/<slug>/curious_minds_shorts_9x16.mp4 \
        [--storyboard generated/<slug>/storyboard.json] [--sheet sheet.png]

Metrics (frames sampled at 4 fps, compared 1 s apart, on a 1/4-size greyscale copy):
  pixel change per second   share of pixels that changed by more than 12 grey levels
  static seconds            1-second windows where under 2 % of pixels changed
  events per 2 s            windows where over 8 % of pixels changed (a clearly new visual)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

FPS = 4


def read_frames(video: Path, w: int, h: int) -> np.ndarray:
    cmd = ["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"fps={FPS},scale={w}:{h},format=gray",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def video_size(video: Path) -> tuple:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def motion(video: Path) -> dict:
    W, H = video_size(video)
    w, h = W // 4, H // 4
    f = read_frames(video, w, h)
    changes = np.array([(np.abs(f[i + FPS] - f[i]) > 12).mean() for i in range(len(f) - FPS)])
    secs = len(f) / FPS
    # visual events: a 0.5 s step that changes > 8 % of the frame, counted per 2 s window
    steps = np.array([(np.abs(f[i + 2] - f[i]) > 12).mean() for i in range(len(f) - 2)])
    windows = [steps[k:k + 2 * FPS] for k in range(0, len(steps), 2 * FPS)]
    with_event = sum(1 for win in windows if len(win) and win.max() > 0.08)
    return {"video": str(video), "seconds": round(secs, 1),
            "pixel_change_per_s_median_pct": round(float(np.median(changes)) * 100, 1),
            "pixel_change_per_s_mean_pct": round(float(changes.mean()) * 100, 1),
            "static_1s_windows_pct": round(float((changes < 0.02).mean()) * 100, 1),
            "two_second_windows_with_a_new_visual_pct": round(with_event / max(1, len(windows)) * 100, 1)}


def contact_sheet(video: Path, storyboard: Path, out: Path, at: float = 0.55, cols: int = 7, scale: float = 0.25) -> Path:
    sb = json.loads(storyboard.read_text(encoding="utf-8"))
    W, H = video_size(video)
    tw, th = int(W * scale), int(H * scale)
    t, times = 0.0, []
    for sc in sb["scenes"]:
        times.append(t + sc["duration"] * at)
        t += sc["duration"]
    from PIL import Image
    rows = (len(times) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), "white")
    for i, ts in enumerate(times):
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{ts:.3f}", "-i", str(video), "-frames:v", "1",
                              "-vf", f"scale={tw}:{th}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        img = Image.frombytes("RGB", (tw, th), raw)
        sheet.paste(img, ((i % cols) * tw, (i // cols) * th))
    sheet.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--storyboard")
    ap.add_argument("--sheet")
    ap.add_argument("--at", type=float, default=0.55, help="position inside each scene for the sheet (0-1)")
    a = ap.parse_args()
    rep = motion(Path(a.video))
    print(json.dumps(rep, indent=2))
    if a.sheet and a.storyboard:
        print("sheet:", contact_sheet(Path(a.video), Path(a.storyboard), Path(a.sheet), a.at))
    return 0


if __name__ == "__main__":
    sys.exit(main())
