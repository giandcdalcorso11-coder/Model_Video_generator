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

  * On-screen text (from ai_classifier/OCR) and spoken dialogue (from
    speech.py, Whisper) are TWO INDEPENDENT subtitle tracks, built from two
    independent Template fields (texts / dialogue) and two independent .srt
    files. They are never merged into the same list or file. Each track is
    renamed right after import (SetTrackName) so they're unmistakable in
    Resolve: "Testo a schermo" vs "Dialogo (trascrizione)". SRT import is
    used instead of scripted Fusion Text+ nodes because Text+ has no direct
    "create a title clip" call in the API; SRT import is a stable,
    documented mechanism that gets exact timing right.

  * Voice/music separation (also from speech.py) produces two more audio
    tracks, "Voce" and "Musica". Both are literal time-slices of the SAME
    mixed source audio (mediaType=2 on the same MediaPoolItem used for
    video) -- not true vocal isolation. Each track is filled contiguously
    (real audio where it applies, a silent placeholder elsewhere) so a
    simple sequential append reproduces correct absolute timing, the same
    trick used for video gaps.

  * Effects/transitions detected by the AI (EffectNote) are NOT scriptable
    (no `AddTransition` in the API) -- they become timeline markers labeled
    with what was detected, so the user can drag the matching effect on
    themselves. Basic transform effects (zoom/pan/crop/speed), if present on
    a ClipSlot, ARE applied directly via TimelineItem.SetProperty.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from resolve_plugin.analysis.template_schema import (
    ClipSlot,
    Gap,
    MusicSegment,
    Template,
    TextOverlay,
    VoiceSegment,
)
from resolve_plugin.media_prep import (
    PlaceholderClipCache as _PlaceholderClipCache,
    SilentAudioPlaceholderCache as _SilentAudioPlaceholderCache,
    seconds_to_frames as _seconds_to_frames,
    write_srt as _write_srt,
)
from resolve_plugin.resolve_api.connection import ResolveHandles

MARKER_COLOR = "Yellow"
MEDIA_TYPE_AUDIO_ONLY = 2

ON_SCREEN_TEXT_TRACK_NAME = "Testo a schermo"
DIALOGUE_TRACK_NAME = "Dialogo (trascrizione)"
VOICE_TRACK_NAME = "Voce"
MUSIC_TRACK_NAME = "Musica"


@dataclass
class BuildResult:
    timeline: Any
    # Maps ClipSlot.index -> the TimelineItem Resolve created for it, so
    # takes_manager can attach alternate takes to the right slot.
    clip_items: dict[int, Any]


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

    # On-screen text and spoken dialogue are independent Template fields,
    # independent .srt files, independent import calls and independently
    # renamed tracks -- kept fully separate on purpose (see module docstring).
    _inject_subtitle_track(timeline, template.texts, work_dir / "on_screen_text.srt", ON_SCREEN_TEXT_TRACK_NAME)
    _inject_subtitle_track(timeline, template.dialogue, work_dir / "dialogue.srt", DIALOGUE_TRACK_NAME)

    _inject_voice_music_tracks(timeline, media_pool, template, source_item, work_dir, fps)

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


def _inject_subtitle_track(timeline: Any, overlays: list[TextOverlay], srt_path: Path, track_name: str) -> None:
    if not _write_srt(overlays, srt_path):
        return
    timeline.ImportIntoTimeline(str(srt_path), {"insertAsSubtitle": True})
    new_track_index = timeline.GetTrackCount("subtitle")
    if new_track_index > 0:
        timeline.SetTrackName("subtitle", new_track_index, track_name)


def _audio_timeline_items(template: Template) -> list[Union[VoiceSegment, MusicSegment]]:
    items: list[Union[VoiceSegment, MusicSegment]] = [*template.voice_segments, *template.music_segments]
    return sorted(items, key=lambda item: item.start_seconds)


def _inject_voice_music_tracks(
    timeline: Any,
    media_pool: Any,
    template: Template,
    source_item: Any,
    work_dir: Path,
    fps: float,
) -> None:
    if not template.voice_segments and not template.music_segments:
        return

    silence_cache = _SilentAudioPlaceholderCache(work_dir)

    timeline.AddTrack("audio")
    voice_track_index = timeline.GetTrackCount("audio")
    timeline.SetTrackName("audio", voice_track_index, VOICE_TRACK_NAME)

    timeline.AddTrack("audio")
    music_track_index = timeline.GetTrackCount("audio")
    timeline.SetTrackName("audio", music_track_index, MUSIC_TRACK_NAME)

    for item in _audio_timeline_items(template):
        is_voice = isinstance(item, VoiceSegment)
        duration = item.end_seconds - item.start_seconds
        if duration <= 0:
            continue

        _append_audio_clip(
            media_pool, source_item, item, fps, target_track_index=voice_track_index,
            as_real_audio=is_voice, silence_cache=silence_cache, duration=duration,
        )
        _append_audio_clip(
            media_pool, source_item, item, fps, target_track_index=music_track_index,
            as_real_audio=not is_voice, silence_cache=silence_cache, duration=duration,
        )


def _append_audio_clip(
    media_pool: Any,
    source_item: Any,
    item: Union[VoiceSegment, MusicSegment],
    fps: float,
    target_track_index: int,
    as_real_audio: bool,
    silence_cache: _SilentAudioPlaceholderCache,
    duration: float,
) -> None:
    if as_real_audio:
        start_frame = _seconds_to_frames(item.start_seconds, fps)
        end_frame = max(start_frame, _seconds_to_frames(item.end_seconds, fps) - 1)
        media_pool.AppendToTimeline([
            {
                "mediaPoolItem": source_item,
                "startFrame": start_frame,
                "endFrame": end_frame,
                "mediaType": MEDIA_TYPE_AUDIO_ONLY,
                "trackIndex": target_track_index,
            }
        ])
    else:
        placeholder_path, _ = silence_cache.get_or_create(duration)
        placeholder_items = media_pool.ImportMedia([str(placeholder_path)])
        if not placeholder_items:
            return
        # Silence clips are plain WAV audio; frame count here is still in
        # terms of the *timeline's* fps, like every other append in this
        # module -- Resolve places audio-only clips using timeline frames.
        end_frame = max(0, _seconds_to_frames(duration, fps) - 1)
        media_pool.AppendToTimeline([
            {
                "mediaPoolItem": placeholder_items[0],
                "startFrame": 0,
                "endFrame": end_frame,
                "trackIndex": target_track_index,
            }
        ])
