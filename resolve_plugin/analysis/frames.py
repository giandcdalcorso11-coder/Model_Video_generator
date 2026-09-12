"""Shared helper to grab a single frame from a video at a given timestamp.

Used by both ocr.py and ai_classifier.py so frame extraction (and its ffmpeg
invocation) lives in exactly one place.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def extract_frame(video_path: str, at_seconds: float) -> Image.Image:
    """Extracts the frame closest to `at_seconds` as a PIL Image.

    Uses ffmpeg -ss (input seeking) + a single-frame jpeg output rather than
    decoding the whole video, so sampling many timestamps stays fast even on
    long videos.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "frame.jpg"
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{max(at_seconds, 0.0):.3f}",
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if not out_path.exists():
            raise RuntimeError(
                f"ffmpeg could not extract a frame at {at_seconds}s from {video_path}: "
                f"{proc.stderr}"
            )
        return Image.open(out_path).convert("RGB").copy()


def sample_timestamps_for_shot(
    shot_start: float, shot_end: float, interval_seconds: float
) -> list[float]:
    """Always includes the shot's start; adds further samples every
    `interval_seconds` for shots longer than that, so a 10s shot at a 2s
    interval yields [start, start+2, start+4, start+6, start+8]."""
    timestamps = [shot_start]
    t = shot_start + interval_seconds
    while t < shot_end:
        timestamps.append(t)
        t += interval_seconds
    return timestamps
