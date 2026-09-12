"""Deterministic, AI-free detection: shot cuts, silences and black frames.

These are the "precise, free" half of the hybrid analysis described in the
plan -- PySceneDetect for cuts, ffmpeg's silencedetect/blackdetect filters
for gaps. Nothing here calls an AI model, so it's cheap, fast and fully
testable without network access.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class Shot:
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass
class TimeRange:
    start_seconds: float
    end_seconds: float


def probe_duration_and_fps(video_path: str) -> tuple[float, float]:
    """Uses ffprobe to get (duration_seconds, fps). Raises RuntimeError with
    ffprobe's stderr on failure so callers get an actionable message."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {video_path}: {proc.stderr}")

    import json as _json

    data = _json.loads(proc.stdout)
    duration = float(data.get("format", {}).get("duration", 0.0))
    fps = 30.0
    streams = data.get("streams", [])
    if streams:
        rate = streams[0].get("r_frame_rate", "30/1")
        num, _, den = rate.partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            fps = 30.0
        if streams[0].get("duration"):
            duration = max(duration, float(streams[0]["duration"]))
    return duration, fps


def detect_shots(video_path: str, threshold: float = 27.0) -> list[Shot]:
    """Detects hard cuts using PySceneDetect's ContentDetector and returns
    contiguous shots covering the whole video (no gaps between them --
    silence/black gaps are detected separately and subtracted later by the
    pipeline)."""
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()

    if not scene_list:
        duration, _ = probe_duration_and_fps(video_path)
        return [Shot(0.0, duration)]

    return [
        Shot(start.get_seconds(), end.get_seconds()) for start, end in scene_list
    ]


_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


def detect_silences(
    video_path: str, noise_db: str = "-35dB", min_duration: float = 0.4
) -> list[TimeRange]:
    """Runs ffmpeg's silencedetect audio filter and parses stderr for
    silence_start/silence_end pairs. Returns [] if the video has no audio
    stream (ffmpeg reports this on stderr rather than raising)."""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=noise={noise_db}:d={min_duration}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stderr = proc.stderr

    starts = [float(m) for m in _SILENCE_START_RE.findall(stderr)]
    ends = [float(m) for m in _SILENCE_END_RE.findall(stderr)]

    ranges = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else start
        ranges.append(TimeRange(start, end))
    return ranges


_BLACK_RE = re.compile(
    r"black_start:([0-9.]+)\s+black_end:([0-9.]+)"
)


def detect_black_frames(
    video_path: str, min_duration: float = 0.3, pic_th: float = 0.98
) -> list[TimeRange]:
    """Runs ffmpeg's blackdetect video filter to find black-frame gaps
    (common at the start/end of templates or between segments)."""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"blackdetect=d={min_duration}:pic_th={pic_th}",
        "-an", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return [
        TimeRange(float(start), float(end))
        for start, end in _BLACK_RE.findall(proc.stderr)
    ]
