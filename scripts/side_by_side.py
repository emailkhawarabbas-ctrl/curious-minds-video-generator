"""Put two videos side by side (e.g. classic vs lively) with labels, using the right video's audio.

    python scripts/side_by_side.py --left generated/x_classic/curious_minds_shorts_9x16.mp4 \
        --right generated/x/curious_minds_shorts_9x16.mp4 --out comparison.mp4
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

FONT = Path(__file__).resolve().parents[1] / "assets" / "fonts"


def _font() -> str:
    hits = sorted(FONT.glob("LilitaOne*.ttf")) or sorted(FONT.glob("*.ttf"))
    # ffmpeg filter syntax: escape the drive colon on Windows
    return str(hits[0]).replace("\\", "/").replace(":", "\\:") if hits else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", required=True)
    ap.add_argument("--right", required=True)
    ap.add_argument("--left-label", default="OLD (classic)")
    ap.add_argument("--right-label", default="NEW (lively)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--height", type=int, default=960)
    a = ap.parse_args()
    h = a.height
    font = _font()
    label = (f"drawtext=fontfile='{font}':text='{{t}}':x=(w-text_w)/2:y=24:fontsize={h // 22}:fontcolor=white:"
             f"borderw=5:bordercolor=0x2B2D42")
    fc = (f"[0:v]scale=-2:{h},setsar=1,{label.format(t=a.left_label)}[l];"
          f"[1:v]scale=-2:{h},setsar=1,{label.format(t=a.right_label)}[r];"
          f"[l][r]hstack=inputs=2:shortest=0[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", a.left, "-i", a.right, "-filter_complex", fc,
           "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
