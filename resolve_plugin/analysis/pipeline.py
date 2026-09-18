"""Orchestrates video -> Template.

Order of operations:
  1. Deterministic pass (free, no AI): shot/cut detection + black-frame gap
     detection via analysis.scene_detect.
  2. Any shot that's mostly black becomes a Gap instead of a ClipSlot -- this
     is what preserves "empty spaces" from a template.
  3. Semantic pass (AI, pluggable backend): for each remaining ClipSlot,
     sample a handful of frames (first frame of the shot + every
     `in_shot_sample_interval_seconds`) and run OCR + the configured vision
     backend to fill in on-screen text and effect/transition notes.

The generated Template places every clip at the same timestamp it had in the
source video (a 1:1 layout), so gaps fall out naturally as the ranges no
ClipSlot covers -- no manual offset bookkeeping needed.
"""
from __future__ import annotations

from typing import Callable, Optional

from resolve_plugin.analysis import scene_detect, speech
from resolve_plugin.analysis.ai_classifier import VisionBackend, get_backend
from resolve_plugin.analysis.frames import extract_frame, sample_timestamps_for_shot
from resolve_plugin.analysis.ocr import detect_text
from resolve_plugin.analysis.template_schema import (
    ClipSlot,
    EffectNote,
    Gap,
    Template,
    TextOverlay,
)
from resolve_plugin.config import CONFIG

ProgressCallback = Callable[[int, int, str], None]


def _overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _shots_and_gaps(
    shots: list[scene_detect.Shot], black_ranges: list[scene_detect.TimeRange]
) -> tuple[list[ClipSlot], list[Gap]]:
    clips: list[ClipSlot] = []
    gaps: list[Gap] = []
    next_index = 0

    for shot in shots:
        black_overlap = sum(
            _overlap_seconds(shot.start_seconds, shot.end_seconds, b.start_seconds, b.end_seconds)
            for b in black_ranges
        )
        if shot.duration_seconds > 0 and black_overlap / shot.duration_seconds > 0.6:
            gaps.append(Gap(shot.start_seconds, shot.end_seconds))
            continue

        clips.append(
            ClipSlot(
                index=next_index,
                source_in_seconds=shot.start_seconds,
                source_out_seconds=shot.end_seconds,
                timeline_start_seconds=shot.start_seconds,
            )
        )
        next_index += 1

    return clips, gaps


def _classify_clip(
    video_path: str,
    clip: ClipSlot,
    backend: VisionBackend,
) -> tuple[list[TextOverlay], list[EffectNote]]:
    texts: list[TextOverlay] = []
    notes: list[EffectNote] = []

    if clip.duration_seconds < CONFIG.analysis.min_shot_seconds_for_ai:
        return texts, notes

    timestamps = sample_timestamps_for_shot(
        clip.source_in_seconds,
        clip.source_out_seconds,
        CONFIG.analysis.in_shot_sample_interval_seconds,
    )

    current_text: Optional[str] = None
    current_text_start: Optional[float] = None
    last_ts = clip.source_out_seconds

    def flush_text(end_at: float) -> None:
        if current_text:
            texts.append(
                TextOverlay(
                    content=current_text,
                    start_seconds=current_text_start,
                    end_seconds=end_at,
                )
            )

    for ts in timestamps:
        frame = extract_frame(video_path, ts)
        ocr_text = detect_text(frame)
        classification = backend.classify_frame(frame)
        text = ocr_text or classification.text

        if text != current_text:
            flush_text(ts)
            current_text = text or None
            current_text_start = ts if current_text else None

        if classification.effect_style:
            notes.append(
                EffectNote(
                    label=classification.effect_style,
                    at_seconds=ts,
                    confidence=classification.confidence,
                    source="ai",
                )
            )
        last_ts = ts

    flush_text(clip.source_out_seconds)
    return texts, notes


def analyze_video(
    video_path: str,
    ai_backend: Optional[VisionBackend] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Template:
    def report(step: int, total: int, message: str) -> None:
        if progress_callback:
            progress_callback(step, total, message)

    backend = ai_backend or get_backend()
    backend_model = getattr(backend, "model", None)
    backend_label = f"{CONFIG.analysis.ai_backend}" + (f" ({backend_model})" if backend_model else "")

    report(0, 100, f"Modello per testo a schermo/effetti: {backend_label}")
    report(0, 100, "Reading video metadata...")
    duration, fps = scene_detect.probe_duration_and_fps(video_path)
    report(1, 100, f"Video: {duration:.2f}s a {fps:.2f} fps")

    report(5, 100, "Detecting cuts...")
    shots = scene_detect.detect_shots(
        video_path,
        CONFIG.analysis.scene_detect_threshold,
        fps=fps,
        min_scene_len_seconds=CONFIG.analysis.scene_detect_min_scene_len_seconds,
    )
    report(
        18,
        100,
        f"Rilevati {len(shots)} shot (soglia sensibilita' tagli: "
        f"{CONFIG.analysis.scene_detect_threshold})",
    )

    report(20, 100, "Detecting empty/black spaces...")
    black_ranges = scene_detect.detect_black_frames(video_path)

    clips, gaps = _shots_and_gaps(shots, black_ranges)
    report(
        29,
        100,
        f"Struttura video: {len(clips)} clip, {len(gaps)} spazi vuoti/gap",
    )

    template = Template(source_video_path=video_path, fps=fps, clips=clips, gaps=gaps)

    if CONFIG.analysis.enable_speech_analysis:
        report(
            30,
            100,
            f"Transcribing voice & separating music... (modello Whisper: "
            f"{CONFIG.analysis.whisper_model_size})",
        )
        try:
            voice_segments, music_segments, dialogue, music_notes = speech.analyze_speech_and_music(
                video_path, duration
            )
            template.voice_segments = voice_segments
            template.music_segments = music_segments
            template.dialogue = dialogue
            template.effect_notes.extend(music_notes)
            report(
                39,
                100,
                f"Parlato: {len(voice_segments)} interventi vocali, "
                f"{len(music_segments)} segmenti musicali, {len(dialogue)} righe trascritte",
            )
        except RuntimeError as exc:
            # Optional feature: missing faster-whisper (or a failed ffmpeg
            # audio extraction) shouldn't abort the rest of the analysis.
            report(30, 100, f"Voice/music analysis skipped: {exc}")
    else:
        report(30, 100, "Analisi vocale disattivata (enable_speech_analysis=false)")

    total_clips = max(len(clips), 1)
    for i, clip in enumerate(clips):
        report(
            40 + int(55 * i / total_clips),
            100,
            f"Analyzing clip {i + 1}/{len(clips)} (text & effects)...",
        )
        texts, notes = _classify_clip(video_path, clip, backend)
        template.texts.extend(texts)
        template.effect_notes.extend(notes)

    report(
        99,
        100,
        f"Testo a schermo: {len(template.texts)} elemento/i trovati, "
        f"{len(template.effect_notes)} effetto/i o transizione segnalati",
    )
    report(100, 100, "Done.")
    return template
