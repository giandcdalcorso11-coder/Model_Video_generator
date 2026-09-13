from unittest.mock import patch

from PIL import Image

from resolve_plugin.analysis import pipeline, scene_detect
from resolve_plugin.analysis.ai_classifier import FrameClassification, MockBackend
from resolve_plugin.analysis.template_schema import ClipSlot, EffectNote, Gap, MusicSegment, TextOverlay, VoiceSegment


def test_shots_and_gaps_splits_mostly_black_shots_into_gaps():
    shots = [
        scene_detect.Shot(0.0, 2.0),   # normal shot
        scene_detect.Shot(2.0, 3.0),   # mostly black -> gap
        scene_detect.Shot(3.0, 5.0),   # normal shot
    ]
    black_ranges = [scene_detect.TimeRange(2.0, 3.0)]

    clips, gaps = pipeline._shots_and_gaps(shots, black_ranges)

    assert [c.source_in_seconds for c in clips] == [0.0, 3.0]
    assert [c.index for c in clips] == [0, 1]  # gap doesn't consume an index
    assert len(gaps) == 1
    assert gaps[0].start_seconds == 2.0
    assert gaps[0].end_seconds == 3.0


def test_shots_and_gaps_keeps_partially_black_shot_as_clip():
    shots = [scene_detect.Shot(0.0, 4.0)]
    # Only 25% overlap with black -> below the 60% threshold, stays a clip.
    black_ranges = [scene_detect.TimeRange(0.0, 1.0)]

    clips, gaps = pipeline._shots_and_gaps(shots, black_ranges)

    assert len(clips) == 1
    assert len(gaps) == 0


def _fake_frame():
    return Image.new("RGB", (2, 2), color="black")


def test_classify_clip_skips_very_short_clips():
    clip = ClipSlot(index=0, source_in_seconds=0.0, source_out_seconds=0.1, timeline_start_seconds=0.0)
    backend = MockBackend()

    texts, notes = pipeline._classify_clip("video.mp4", clip, backend)

    assert texts == []
    assert notes == []


def test_classify_clip_collects_text_and_effect_notes(monkeypatch):
    clip = ClipSlot(index=0, source_in_seconds=0.0, source_out_seconds=4.0, timeline_start_seconds=0.0)
    backend = MockBackend(
        canned=FrameClassification(text="Subscribe!", effect_style="zoom blur", confidence=0.9)
    )

    monkeypatch.setattr(pipeline, "extract_frame", lambda video_path, ts: _fake_frame())
    monkeypatch.setattr(pipeline, "detect_text", lambda frame: "")  # force fallback to AI text
    monkeypatch.setattr(
        pipeline,
        "sample_timestamps_for_shot",
        lambda start, end, interval: [0.0, 2.0],
    )

    texts, notes = pipeline._classify_clip("video.mp4", clip, backend)

    assert len(texts) == 1
    assert texts[0].content == "Subscribe!"
    assert texts[0].start_seconds == 0.0
    assert texts[0].end_seconds == 4.0  # merged across both identical samples
    assert len(notes) == 2  # one effect note per sampled frame
    assert all(n.label == "zoom blur" for n in notes)


def _patch_common_video_analysis(monkeypatch):
    monkeypatch.setattr(
        pipeline.scene_detect, "probe_duration_and_fps", lambda path: (5.0, 30.0)
    )
    monkeypatch.setattr(
        pipeline.scene_detect,
        "detect_shots",
        lambda path, threshold: [scene_detect.Shot(0.0, 2.0), scene_detect.Shot(2.0, 5.0)],
    )
    monkeypatch.setattr(
        pipeline.scene_detect, "detect_black_frames", lambda path: []
    )
    monkeypatch.setattr(pipeline, "extract_frame", lambda video_path, ts: _fake_frame())
    monkeypatch.setattr(pipeline, "detect_text", lambda frame: "")


def test_analyze_video_end_to_end_with_mocks(monkeypatch):
    _patch_common_video_analysis(monkeypatch)
    monkeypatch.setattr(pipeline.CONFIG.analysis, "enable_speech_analysis", False)

    backend = MockBackend(canned=FrameClassification())
    progress_events = []

    template = pipeline.analyze_video(
        "video.mp4",
        ai_backend=backend,
        progress_callback=lambda step, total, msg: progress_events.append((step, total, msg)),
    )

    assert template.fps == 30.0
    assert len(template.clips) == 2
    assert len(template.gaps) == 0
    assert progress_events[0][0] == 0
    assert progress_events[-1] == (100, 100, "Done.")


def test_analyze_video_wires_in_voice_music_and_dialogue(monkeypatch):
    _patch_common_video_analysis(monkeypatch)
    monkeypatch.setattr(pipeline.CONFIG.analysis, "enable_speech_analysis", True)

    voice_segments = [VoiceSegment(index=0, start_seconds=0.0, end_seconds=1.0, transcript="ciao")]
    music_segments = [MusicSegment(index=0, start_seconds=1.0, end_seconds=5.0)]
    dialogue = [TextOverlay(content="ciao", start_seconds=0.0, end_seconds=1.0)]
    music_notes = [EffectNote(label="possibile cambio musica", at_seconds=3.0, source="heuristic")]

    monkeypatch.setattr(
        pipeline.speech,
        "analyze_speech_and_music",
        lambda video_path, duration: (voice_segments, music_segments, dialogue, music_notes),
    )

    backend = MockBackend(canned=FrameClassification())
    template = pipeline.analyze_video("video.mp4", ai_backend=backend)

    assert template.voice_segments == voice_segments
    assert template.music_segments == music_segments
    assert template.dialogue == dialogue
    assert music_notes[0] in template.effect_notes
    # On-screen text (from the vision backend/OCR) must stay untouched by
    # the speech pipeline -- it's a separate field, populated separately.
    assert all(overlay not in template.texts for overlay in dialogue)


def test_analyze_video_degrades_gracefully_when_speech_analysis_unavailable(monkeypatch):
    _patch_common_video_analysis(monkeypatch)
    monkeypatch.setattr(pipeline.CONFIG.analysis, "enable_speech_analysis", True)

    def raise_error(video_path, duration):
        raise RuntimeError("faster-whisper non è installato.")

    monkeypatch.setattr(pipeline.speech, "analyze_speech_and_music", raise_error)

    backend = MockBackend(canned=FrameClassification())
    progress_events = []

    template = pipeline.analyze_video(
        "video.mp4",
        ai_backend=backend,
        progress_callback=lambda step, total, msg: progress_events.append((step, total, msg)),
    )

    # The rest of the analysis still completes normally.
    assert len(template.clips) == 2
    assert template.voice_segments == []
    assert any("skipped" in msg for _, _, msg in progress_events)
