import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from resolve_plugin.analysis import speech
from resolve_plugin.analysis.speech import RawSpeechSegment
from resolve_plugin.analysis.template_schema import MusicSegment, VoiceSegment


def test_transcribe_speech_raises_readable_error_when_faster_whisper_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(RuntimeError, match="faster-whisper"):
        speech.transcribe_speech("video.mp4")


def test_transcribe_speech_returns_segments_from_whisper(monkeypatch):
    fake_segment = MagicMock(start=1.0, end=2.5, text="  ciao mondo  ")
    fake_model_instance = MagicMock()
    fake_model_instance.transcribe.return_value = ([fake_segment], MagicMock())

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = MagicMock(return_value=fake_model_instance)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    result = speech.transcribe_speech("video.mp4", model_size="base")

    assert result == [RawSpeechSegment(start_seconds=1.0, end_seconds=2.5, text="ciao mondo")]
    fake_module.WhisperModel.assert_called_once_with("base", device="auto", compute_type="int8")
    fake_model_instance.transcribe.assert_called_once_with("video.mp4", vad_filter=True)


def test_derive_voice_and_music_segments_basic_tiling():
    speech_segments = [
        RawSpeechSegment(start_seconds=1.0, end_seconds=2.0, text="uno"),
        RawSpeechSegment(start_seconds=5.0, end_seconds=6.0, text="due"),
    ]

    voice, music = speech.derive_voice_and_music_segments(speech_segments, total_duration=8.0, min_gap_seconds=0.6)

    assert [(v.start_seconds, v.end_seconds, v.transcript) for v in voice] == [
        (1.0, 2.0, "uno"),
        (5.0, 6.0, "due"),
    ]
    assert [(m.start_seconds, m.end_seconds) for m in music] == [
        (0.0, 1.0),
        (2.0, 5.0),
        (6.0, 8.0),
    ]


def test_derive_voice_and_music_segments_merges_close_segments():
    speech_segments = [
        RawSpeechSegment(start_seconds=1.0, end_seconds=2.0, text="uno"),
        RawSpeechSegment(start_seconds=2.2, end_seconds=3.0, text="due"),  # 0.2s gap < 0.6s
    ]

    voice, music = speech.derive_voice_and_music_segments(speech_segments, total_duration=4.0, min_gap_seconds=0.6)

    assert len(voice) == 1
    assert voice[0].start_seconds == 1.0
    assert voice[0].end_seconds == 3.0
    assert voice[0].transcript == "uno due"
    assert [(m.start_seconds, m.end_seconds) for m in music] == [(0.0, 1.0), (3.0, 4.0)]


def test_derive_voice_and_music_segments_no_speech_is_all_music():
    voice, music = speech.derive_voice_and_music_segments([], total_duration=10.0)
    assert voice == []
    assert len(music) == 1
    assert music[0].start_seconds == 0.0
    assert music[0].end_seconds == 10.0


def test_derive_voice_and_music_segments_speech_covers_whole_video():
    speech_segments = [RawSpeechSegment(start_seconds=0.0, end_seconds=10.0, text="tutto parlato")]
    voice, music = speech.derive_voice_and_music_segments(speech_segments, total_duration=10.0)
    assert len(voice) == 1
    assert music == []


def test_dialogue_text_overlays_skips_empty_transcripts():
    voice_segments = [
        VoiceSegment(index=0, start_seconds=0.0, end_seconds=1.0, transcript="ciao"),
        VoiceSegment(index=1, start_seconds=1.0, end_seconds=2.0, transcript=""),
    ]
    overlays = speech.dialogue_text_overlays(voice_segments)
    assert len(overlays) == 1
    assert overlays[0].content == "ciao"
    assert overlays[0].start_seconds == 0.0
    assert overlays[0].end_seconds == 1.0


def _loud_then_quiet_pcm(sample_rate=16000, seconds=6):
    n = sample_rate * seconds
    signal = np.zeros(n, dtype=np.float32)
    half = n // 2
    signal[:half] = 0.9  # loud
    signal[half:] = 0.01  # quiet
    return signal


def test_detect_music_change_notes_finds_loudness_jump(monkeypatch):
    music_segments = [MusicSegment(index=0, start_seconds=0.0, end_seconds=6.0)]
    monkeypatch.setattr(speech, "_read_pcm_mono16k", lambda video_path: _loud_then_quiet_pcm())

    notes = speech.detect_music_change_notes(
        "video.mp4", music_segments, rms_jump_db=10.0, min_segment_seconds=3.0
    )

    assert len(notes) >= 1
    assert notes[0].label == "possibile cambio musica"
    assert notes[0].source == "heuristic"
    assert 2.0 <= notes[0].at_seconds <= 4.0


def test_detect_music_change_notes_skips_short_segments():
    music_segments = [MusicSegment(index=0, start_seconds=0.0, end_seconds=1.0)]
    notes = speech.detect_music_change_notes(
        "video.mp4", music_segments, min_segment_seconds=3.0
    )
    assert notes == []


def test_detect_music_change_notes_returns_empty_when_audio_extraction_fails(monkeypatch):
    music_segments = [MusicSegment(index=0, start_seconds=0.0, end_seconds=6.0)]

    def raise_error(video_path):
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(speech, "_read_pcm_mono16k", raise_error)
    notes = speech.detect_music_change_notes("video.mp4", music_segments, min_segment_seconds=3.0)
    assert notes == []


def test_analyze_speech_and_music_end_to_end(monkeypatch):
    monkeypatch.setattr(
        speech,
        "transcribe_speech",
        lambda video_path: [RawSpeechSegment(start_seconds=0.0, end_seconds=1.0, text="ciao")],
    )
    monkeypatch.setattr(speech, "_read_pcm_mono16k", lambda video_path: _loud_then_quiet_pcm())

    voice_segments, music_segments, dialogue, notes = speech.analyze_speech_and_music("video.mp4", 10.0)

    assert len(voice_segments) == 1
    assert voice_segments[0].transcript == "ciao"
    assert len(music_segments) == 1
    assert music_segments[0].start_seconds == 1.0
    assert dialogue[0].content == "ciao"
