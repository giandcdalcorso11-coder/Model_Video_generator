"""Data model for an extracted editing "template".

A Template describes the structure of the uploaded video in terms Resolve's
timeline can reproduce: an ordered list of clip slots (with in/out points and
basic transform effects), gaps between them, on-screen text overlays, and a
list of "effect notes" for anything detected but not automatable (e.g. a
transition style) that the user needs to apply by hand.

This is deliberately independent of both ffmpeg/scenedetect and the Resolve
API so it can be unit-tested in isolation and serialized to template.json.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class TransformEffect:
    """A basic transform effect, directly scriptable via
    TimelineItem.SetProperty in Resolve (zoom/pan/crop/speed/rotation)."""

    kind: str  # "zoom_in" | "zoom_out" | "pan" | "crop" | "speed" | "rotation"
    # Raw property values understood by resolve_api.timeline_builder, e.g.
    # {"ZoomX": 1.2, "ZoomY": 1.2} or {"Speed": 200.0}
    properties: dict = field(default_factory=dict)
    start_seconds: float = 0.0
    end_seconds: Optional[float] = None


@dataclass
class EffectNote:
    """Something detected in the source video that Resolve's scripting API
    cannot apply automatically (most transitions, color grades, OFX filters).
    Surfaced to the user as a timeline marker so they can apply it manually.
    """

    label: str  # e.g. "cross dissolve", "glitch transition", "vignette"
    at_seconds: float
    confidence: float = 0.0
    source: str = "ai"  # "ai" | "heuristic"


@dataclass
class TextOverlay:
    content: str
    start_seconds: float
    end_seconds: float
    # Normalized 0..1 position within the frame, best-effort from AI/OCR.
    position: dict = field(default_factory=lambda: {"x": 0.5, "y": 0.85})
    style_notes: str = ""


@dataclass
class Gap:
    start_seconds: float
    end_seconds: float


@dataclass
class VoiceSegment:
    """One spoken utterance detected by Whisper's voice-activity detection.
    Becomes its own audio "box" on the dedicated voice track -- one slot per
    intervento parlato, independently replaceable/trimmable."""

    index: int
    start_seconds: float
    end_seconds: float
    transcript: str = ""


@dataclass
class MusicSegment:
    """Whatever isn't detected as speech: the complement of VoiceSegments
    across the whole video, kept as one continuous box unless a possible
    music change was flagged (see EffectNote, source="heuristic")."""

    index: int
    start_seconds: float
    end_seconds: float


@dataclass
class ClipSlot:
    """One shot from the source video, i.e. one slot in the generated
    timeline. `index` is the slot's position (0-based) and is what the
    replace-footage UI and takes_manager address."""

    index: int
    source_in_seconds: float
    source_out_seconds: float
    timeline_start_seconds: float
    transforms: list[TransformEffect] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return self.source_out_seconds - self.source_in_seconds


@dataclass
class Template:
    source_video_path: str
    fps: float
    clips: list[ClipSlot] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    # On-screen graphic text (captions/titles baked into the picture),
    # detected from frames via OCR/vision AI. Rendered as one subtitle track.
    texts: list[TextOverlay] = field(default_factory=list)
    effect_notes: list[EffectNote] = field(default_factory=list)
    # Spoken-word transcript (from Whisper), one entry per VoiceSegment.
    # Deliberately a SEPARATE list from `texts` -- never merged -- so the
    # on-screen-text feature and the dialogue-transcript feature can never
    # clobber each other's data. Rendered as its own, separately named
    # subtitle track.
    dialogue: list[TextOverlay] = field(default_factory=list)
    voice_segments: list[VoiceSegment] = field(default_factory=list)
    music_segments: list[MusicSegment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Template":
        return Template(
            source_video_path=data["source_video_path"],
            fps=data["fps"],
            clips=[
                ClipSlot(
                    index=c["index"],
                    source_in_seconds=c["source_in_seconds"],
                    source_out_seconds=c["source_out_seconds"],
                    timeline_start_seconds=c["timeline_start_seconds"],
                    transforms=[TransformEffect(**t) for t in c.get("transforms", [])],
                )
                for c in data.get("clips", [])
            ],
            gaps=[Gap(**g) for g in data.get("gaps", [])],
            texts=[TextOverlay(**t) for t in data.get("texts", [])],
            effect_notes=[EffectNote(**e) for e in data.get("effect_notes", [])],
            dialogue=[TextOverlay(**t) for t in data.get("dialogue", [])],
            voice_segments=[VoiceSegment(**v) for v in data.get("voice_segments", [])],
            music_segments=[MusicSegment(**m) for m in data.get("music_segments", [])],
        )
