"""Voice/music separation.

Uses Whisper (via faster-whisper, local/free/CPU-friendly, no GPU or API
key needed) for voice-activity detection + transcription. This is a
DELIBERATELY SEPARATE module and data path from analysis/ai_classifier.py's
on-screen text detection:

  - ai_classifier.py reads text baked into the PICTURE (captions/graphics)
    from sampled video frames -> feeds Template.texts.
  - speech.py reads what is SPOKEN in the audio -> feeds Template.dialogue,
    Template.voice_segments, Template.music_segments.

These two never merge into the same list, file, or Resolve track -- see
resolve_api/timeline_builder.py, which renders them as two independently
labeled subtitle tracks precisely so they can't be confused with each other.

Honesty about what this can and can't do:
  - Voice vs. music separation here is TEMPORAL, not spectral: both the
    "voice" and "music" tracks are slices of the exact same mixed source
    audio, just for different time ranges (speech-detected vs. not). If
    someone talks over background music, that music is still audible under
    the voice segment -- this is not true vocal isolation (that would need
    a much heavier model like Demucs, which doesn't fit the "free, light,
    local" brief).
  - "Possible music change" is a loudness-jump heuristic, not real song
    detection. It only ever adds a marker for the user to check by ear; it
    never auto-splits a music segment, because a wrong automatic cut would
    be worse than no cut at all.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional

from resolve_plugin.analysis.template_schema import EffectNote, MusicSegment, TextOverlay, VoiceSegment
from resolve_plugin.config import CONFIG


@dataclass
class RawSpeechSegment:
    start_seconds: float
    end_seconds: float
    text: str


def transcribe_speech(video_path: str, model_size: Optional[str] = None) -> list[RawSpeechSegment]:
    """Runs faster-whisper with VAD filtering to get speech-only segments and
    their transcript. Raises RuntimeError with an actionable message if
    faster-whisper isn't installed, so callers can degrade gracefully
    instead of crashing the whole analysis pipeline over an optional
    feature.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper non è installato. Esegui `pip install faster-whisper` "
            "per abilitare la separazione voce/musica, oppure disattiva "
            "enable_speech_analysis in user_config.json."
        ) from exc

    model = WhisperModel(
        model_size or CONFIG.analysis.whisper_model_size, device="auto", compute_type="int8"
    )
    segments, _info = model.transcribe(video_path, vad_filter=True)
    return [
        RawSpeechSegment(start_seconds=seg.start, end_seconds=seg.end, text=seg.text.strip())
        for seg in segments
    ]


def derive_voice_and_music_segments(
    speech_segments: list[RawSpeechSegment],
    total_duration: float,
    min_gap_seconds: float = 0.6,
) -> tuple[list[VoiceSegment], list[MusicSegment]]:
    """Merges speech segments separated by a short gap (a natural pause
    inside a sentence, not a real music break) into one voice box, then
    turns every remaining gap between/around them into a music segment.
    Together voice_segments + music_segments always tile [0, total_duration]
    with no overlap -- the same contiguous-tiling trick ClipSlots+Gaps use
    for the video track, which is what lets the timeline builder place both
    with simple sequential appends and still get correct absolute timing.
    """
    merged: list[RawSpeechSegment] = []
    for seg in sorted(speech_segments, key=lambda s: s.start_seconds):
        if merged and seg.start_seconds - merged[-1].end_seconds <= min_gap_seconds:
            prev = merged[-1]
            merged[-1] = RawSpeechSegment(
                start_seconds=prev.start_seconds,
                end_seconds=max(prev.end_seconds, seg.end_seconds),
                text=f"{prev.text} {seg.text}".strip(),
            )
        else:
            merged.append(seg)

    voice_segments = [
        VoiceSegment(
            index=i,
            start_seconds=s.start_seconds,
            end_seconds=s.end_seconds,
            transcript=s.text,
        )
        for i, s in enumerate(merged)
    ]

    music_segments: list[MusicSegment] = []
    cursor = 0.0
    for v in voice_segments:
        if v.start_seconds - cursor > 1e-6:
            music_segments.append(
                MusicSegment(index=len(music_segments), start_seconds=cursor, end_seconds=v.start_seconds)
            )
        cursor = max(cursor, v.end_seconds)
    if total_duration - cursor > 1e-6:
        music_segments.append(
            MusicSegment(index=len(music_segments), start_seconds=cursor, end_seconds=total_duration)
        )

    return voice_segments, music_segments


def dialogue_text_overlays(voice_segments: list[VoiceSegment]) -> list[TextOverlay]:
    """One TextOverlay per voice segment with a transcript, timed
    identically to it. Feeds Template.dialogue -- kept separate from
    Template.texts (on-screen graphic text) by construction."""
    return [
        TextOverlay(content=v.transcript, start_seconds=v.start_seconds, end_seconds=v.end_seconds)
        for v in voice_segments
        if v.transcript
    ]


def _read_pcm_mono16k(video_path: str):
    import numpy as np

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-f", "s16le", "-ar", "16000", "-ac", "1",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if not proc.stdout:
        stderr = proc.stderr.decode(errors="ignore") if proc.stderr else ""
        raise RuntimeError(f"ffmpeg could not extract audio from {video_path}: {stderr}")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def detect_music_change_notes(
    video_path: str,
    music_segments: list[MusicSegment],
    rms_jump_db: Optional[float] = None,
    min_segment_seconds: Optional[float] = None,
    sample_rate: int = 16000,
    window_seconds: float = 1.0,
) -> list[EffectNote]:
    """Best-effort heuristic: inside each sufficiently long music segment,
    look for a sustained jump in RMS loudness and flag it with a marker
    ("possibile cambio musica") for the user to check by ear. Never
    auto-splits the segment. Never raises -- if audio extraction fails, we
    simply skip this optional heuristic rather than fail the whole
    analysis."""
    import numpy as np

    rms_jump_db = rms_jump_db if rms_jump_db is not None else CONFIG.analysis.music_change_rms_jump_db
    min_segment_seconds = (
        min_segment_seconds
        if min_segment_seconds is not None
        else CONFIG.analysis.music_change_min_segment_seconds
    )

    long_segments = [s for s in music_segments if s.end_seconds - s.start_seconds >= min_segment_seconds]
    if not long_segments:
        return []

    try:
        pcm = _read_pcm_mono16k(video_path)
    except RuntimeError:
        return []

    window_samples = max(1, int(window_seconds * sample_rate))
    notes: list[EffectNote] = []

    for segment in long_segments:
        start_sample = int(segment.start_seconds * sample_rate)
        end_sample = int(segment.end_seconds * sample_rate)
        chunk = pcm[start_sample:end_sample]
        n_windows = chunk.size // window_samples
        if n_windows < 2:
            continue

        rms_per_window = [
            float(np.sqrt(np.mean(chunk[i * window_samples:(i + 1) * window_samples] ** 2)) + 1e-9)
            for i in range(n_windows)
        ]

        for i in range(1, len(rms_per_window)):
            prev_db = 20 * np.log10(rms_per_window[i - 1])
            curr_db = 20 * np.log10(rms_per_window[i])
            if abs(curr_db - prev_db) >= rms_jump_db:
                notes.append(
                    EffectNote(
                        label="possibile cambio musica",
                        at_seconds=segment.start_seconds + i * window_seconds,
                        confidence=0.3,
                        source="heuristic",
                    )
                )

    return notes


def analyze_speech_and_music(
    video_path: str, total_duration: float
) -> tuple[list[VoiceSegment], list[MusicSegment], list[TextOverlay], list[EffectNote]]:
    """Top-level entry point used by analysis/pipeline.py."""
    speech_segments = transcribe_speech(video_path)
    voice_segments, music_segments = derive_voice_and_music_segments(
        speech_segments, total_duration, CONFIG.analysis.min_gap_to_split_voice_seconds
    )
    dialogue = dialogue_text_overlays(voice_segments)
    music_notes = detect_music_change_notes(video_path, music_segments)
    return voice_segments, music_segments, dialogue, music_notes
