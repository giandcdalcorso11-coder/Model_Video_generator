"""Filesystem-only helpers for preparing the media/subtitle assets a Resolve
timeline needs: black placeholder clips for gaps, silent placeholder audio
for the voice/music tracks, and .srt subtitle files.

Deliberately independent of the Resolve API (no `resolve`/`fusion` objects
anywhere in this module) so it can run from a plain Python process -- used
by both:
  - `lua_codegen.py` (the current default path: a plain Python process,
    outside Resolve, prepares everything on disk and emits a Lua script
    that just references the resulting file paths), and
  - `resolve_api/timeline_builder.py` (the legacy Python-inside-Resolve
    path, only reachable on Resolve Studio where Scripts-menu Python still
    runs).

Why this split exists: DaVinci Resolve's Lua scripting environment (as run
from the Scripts menu / Console) has no working `io` library and no
`os.execute` -- confirmed interactively against a real Resolve 21 install,
see README. A Lua script cannot write or read a single file, so it cannot
generate these assets itself; a plain Python process has no such
restriction, which is exactly why file/media prep moved here.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from resolve_plugin.analysis.template_schema import TextOverlay


def seconds_to_frames(seconds: float, fps: float) -> int:
    return max(0, round(seconds * fps))


def seconds_to_srt_timestamp(seconds: float) -> str:
    millis_total = round(seconds * 1000)
    hours, rem = divmod(millis_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(overlays: list[TextOverlay], out_path: Path) -> bool:
    """Returns False (and writes nothing) if there's no text to inject."""
    lines = []
    for i, overlay in enumerate(overlays, start=1):
        if not overlay.content.strip():
            continue
        lines.append(str(i))
        lines.append(
            f"{seconds_to_srt_timestamp(overlay.start_seconds)} --> "
            f"{seconds_to_srt_timestamp(overlay.end_seconds)}"
        )
        lines.append(overlay.content.strip())
        lines.append("")
    if not lines:
        return False
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return True


class PlaceholderClipCache:
    """Generates (and reuses) black placeholder video files for gaps, one
    per rounded-up duration so we don't re-run ffmpeg for every gap."""

    def __init__(self, work_dir: Path, fps: float):
        self.work_dir = work_dir
        self.fps = fps
        self._by_duration_ceil: dict[int, Path] = {}

    def get_or_create(self, min_duration_seconds: float) -> tuple[Path, float]:
        ceil_seconds = max(1, int(min_duration_seconds) + 1)
        if ceil_seconds in self._by_duration_ceil:
            return self._by_duration_ceil[ceil_seconds], ceil_seconds

        out_path = self.work_dir / f"placeholder_{ceil_seconds}s.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s=1920x1080:r={self.fps}:d={ceil_seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if not out_path.exists():
            raise RuntimeError(f"Could not generate placeholder clip: {proc.stderr}")
        self._by_duration_ceil[ceil_seconds] = out_path
        return out_path, ceil_seconds


class SilentAudioPlaceholderCache:
    """Generates (and reuses) silent audio files, used to fill the "Voce" and
    "Musica" tracks contiguously wherever they don't have real content --
    the same tiling trick PlaceholderClipCache uses for video gaps."""

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self._by_duration_ceil: dict[int, Path] = {}

    def get_or_create(self, min_duration_seconds: float) -> tuple[Path, float]:
        ceil_seconds = max(1, int(min_duration_seconds) + 1)
        if ceil_seconds in self._by_duration_ceil:
            return self._by_duration_ceil[ceil_seconds], ceil_seconds

        out_path = self.work_dir / f"silence_{ceil_seconds}s.wav"
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-t", str(ceil_seconds),
            "-c:a", "pcm_s16le",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if not out_path.exists():
            raise RuntimeError(f"Could not generate silent placeholder audio: {proc.stderr}")
        self._by_duration_ceil[ceil_seconds] = out_path
        return out_path, ceil_seconds
