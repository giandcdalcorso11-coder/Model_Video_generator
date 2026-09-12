"""Translates a Template into a real DaVinci Resolve timeline.

Design choices and why (see plan / README for the full rationale):

  * Clips are placed with the same source in/out points detected by
    analysis.pipeline, appended in chronological order on one track -- since
    the detected shots+gaps are contiguous and cover the whole source video,
    appending them in order reproduces the original absolute timing exactly.

  * Gaps become a rendered black placeholder clip of the right duration
    (via ffmpeg's lavfi color source) instead of literal empty timeline
    space. There's no clean documented scripting call for "leave N frames
    blank on this track", and a placeholder clip is arguably *better* UX
    here: it's a selectable, double-click-to-replace slot, which is exactly
    the CapCut-style "empty template slot" the user asked for.

  * On-screen text is injected as a subtitle track via
    `Timeline.ImportIntoTimeline(srt_path, {"insertAsSubtitle": True})`
    rather than scripted Fusion Text+ nodes. Text+ has no direct "create a
    title clip" call in the API (it requires building a Fusion node graph,
    which is fragile and version-dependent); SRT import is a stable,
    documented mechanism that gets exact timing right. The user can restyle
    or convert individual entries to Text+ manually in Resolve afterwards.

  * Effects/transitions detected by the AI (EffectNote) are NOT scriptable
    (no `AddTransition` in the API) -- they become timeline markers labeled
    with what was detected, so the user can drag the matching effect on
    themselves. Basic transform effects (zoom/pan/crop/speed), if present on
    a ClipSlot, ARE applied directly via TimelineItem.SetProperty.
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from resolve_plugin.analysis.template_schema import ClipSlot, Gap, Template
from resolve_plugin.resolve_api.connection import ResolveHandles

MARKER_COLOR = "Yellow"


@dataclass
class BuildResult:
    timeline: Any
    # Maps ClipSlot.index -> the TimelineItem Resolve created for it, so
    # takes_manager can attach alternate takes to the right slot.
    clip_items: dict[int, Any]


def _seconds_to_frames(seconds: float, fps: float) -> int:
    return max(0, round(seconds * fps))


def _seconds_to_srt_timestamp(seconds: float) -> str:
    millis_total = round(seconds * 1000)
    hours, rem = divmod(millis_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(template: Template, out_path: Path) -> bool:
    """Returns False (and writes nothing) if there's no text to inject."""
    if not template.texts:
        return False
    lines = []
    for i, overlay in enumerate(template.texts, start=1):
        if not overlay.content.strip():
            continue
        lines.append(str(i))
        lines.append(
            f"{_seconds_to_srt_timestamp(overlay.start_seconds)} --> "
            f"{_seconds_to_srt_timestamp(overlay.end_seconds)}"
        )
        lines.append(overlay.content.strip())
        lines.append("")
    if not lines:
        return False
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return True


class _PlaceholderClipCache:
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


def _timeline_items(template: Template) -> list[Union[ClipSlot, Gap]]:
    items: list[Union[ClipSlot, Gap]] = [*template.clips, *template.gaps]
    return sorted(items, key=lambda item: (
        item.source_in_seconds if isinstance(item, ClipSlot) else item.start_seconds
    ))


def build_timeline(
    handles: ResolveHandles,
    template: Template,
    timeline_name: str,
    work_dir: Optional[Path] = None,
) -> BuildResult:
    media_pool = handles.media_pool
    project = handles.project
    fps = template.fps

    timeline = media_pool.CreateEmptyTimeline(timeline_name)
    if timeline is None:
        raise RuntimeError(f"Resolve refused to create timeline '{timeline_name}'.")
    project.SetCurrentTimeline(timeline)

    source_items = media_pool.ImportMedia([template.source_video_path])
    if not source_items:
        raise RuntimeError(f"Resolve could not import {template.source_video_path}.")
    source_item = source_items[0]

    work_dir = work_dir or Path(tempfile.mkdtemp(prefix="auto_template_"))
    placeholder_cache = _PlaceholderClipCache(work_dir, fps)

    clip_items: dict[int, Any] = {}

    for item in _timeline_items(template):
        if isinstance(item, ClipSlot):
            start_frame = _seconds_to_frames(item.source_in_seconds, fps)
            end_frame = max(start_frame, _seconds_to_frames(item.source_out_seconds, fps) - 1)
            appended = media_pool.AppendToTimeline([
                {
                    "mediaPoolItem": source_item,
                    "startFrame": start_frame,
                    "endFrame": end_frame,
                }
            ])
            if appended:
                clip_items[item.index] = appended[0]
                _apply_transforms(appended[0], item)
        else:  # Gap -> placeholder clip
            duration = item.end_seconds - item.start_seconds
            if duration <= 0:
                continue
            placeholder_path, placeholder_duration = placeholder_cache.get_or_create(duration)
            placeholder_items = media_pool.ImportMedia([str(placeholder_path)])
            if not placeholder_items:
                continue
            end_frame = max(0, _seconds_to_frames(duration, fps) - 1)
            media_pool.AppendToTimeline([
                {
                    "mediaPoolItem": placeholder_items[0],
                    "startFrame": 0,
                    "endFrame": end_frame,
                }
            ])

    _add_effect_markers(timeline, template, fps)
    _inject_text_track(timeline, template, work_dir)

    return BuildResult(timeline=timeline, clip_items=clip_items)


def _apply_transforms(timeline_item: Any, clip: ClipSlot) -> None:
    for transform in clip.transforms:
        for key, value in transform.properties.items():
            timeline_item.SetProperty(key, value)


def _add_effect_markers(timeline: Any, template: Template, fps: float) -> None:
    for note in template.effect_notes:
        frame_id = _seconds_to_frames(note.at_seconds, fps)
        timeline.AddMarker(
            frame_id,
            MARKER_COLOR,
            note.label or "Detected effect",
            f"Auto-detected ({note.source}, confidence={note.confidence:.2f}). "
            f"Apply the matching effect/transition manually here.",
            1,
        )


def _inject_text_track(timeline: Any, template: Template, work_dir: Path) -> None:
    srt_path = work_dir / "detected_text.srt"
    if _write_srt(template, srt_path):
        timeline.ImportIntoTimeline(str(srt_path), {"insertAsSubtitle": True})
