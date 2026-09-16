from pathlib import Path
from unittest.mock import MagicMock, patch

from resolve_plugin.analysis.template_schema import TextOverlay
from resolve_plugin.media_prep import (
    PlaceholderClipCache,
    SilentAudioPlaceholderCache,
    seconds_to_frames,
    seconds_to_srt_timestamp,
    write_srt,
)


def test_seconds_to_frames():
    assert seconds_to_frames(2.0, 25.0) == 50
    assert seconds_to_frames(0.0, 30.0) == 0
    assert seconds_to_frames(-1.0, 30.0) == 0


def test_seconds_to_srt_timestamp():
    assert seconds_to_srt_timestamp(0.5) == "00:00:00,500"
    assert seconds_to_srt_timestamp(3661.234) == "01:01:01,234"


def test_write_srt_returns_false_when_no_text(tmp_path):
    out_path = tmp_path / "out.srt"
    assert write_srt([], out_path) is False
    assert not out_path.exists()

    assert write_srt([TextOverlay(content="   ", start_seconds=0.0, end_seconds=1.0)], out_path) is False


def test_write_srt_writes_expected_content(tmp_path):
    out_path = tmp_path / "out.srt"
    overlays = [
        TextOverlay(content="Ciao", start_seconds=0.5, end_seconds=1.0),
        TextOverlay(content="Mondo", start_seconds=1.5, end_seconds=2.0),
    ]
    assert write_srt(overlays, out_path) is True
    content = out_path.read_text(encoding="utf-8")
    assert "Ciao" in content
    assert "Mondo" in content
    assert "00:00:00,500 --> 00:00:01,000" in content


def _fake_ffmpeg_run(cmd, *args, **kwargs):
    out_path = Path(cmd[-1])
    out_path.write_bytes(b"fake media bytes")
    return MagicMock(returncode=0, stderr="")


def test_placeholder_clip_cache_creates_and_reuses(tmp_path):
    cache = PlaceholderClipCache(tmp_path, fps=25.0)
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run) as mock_run:
        path1, ceil1 = cache.get_or_create(1.5)
        path2, ceil2 = cache.get_or_create(1.9)  # same ceil(1)+1 = 2s bucket

    assert path1 == path2
    assert ceil1 == ceil2 == 2
    assert path1.exists()
    mock_run.assert_called_once()  # second call reused the cache


def test_placeholder_clip_cache_raises_when_ffmpeg_fails(tmp_path):
    cache = PlaceholderClipCache(tmp_path, fps=25.0)
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="boom")):
        try:
            cache.get_or_create(1.0)
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "boom" in str(exc)


def test_silent_audio_placeholder_cache_creates_and_reuses(tmp_path):
    cache = SilentAudioPlaceholderCache(tmp_path)
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run) as mock_run:
        path1, _ = cache.get_or_create(2.0)
        path2, _ = cache.get_or_create(2.0)

    assert path1 == path2
    assert path1.suffix == ".wav"
    mock_run.assert_called_once()
