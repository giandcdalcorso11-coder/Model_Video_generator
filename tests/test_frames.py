from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from resolve_plugin.analysis.frames import extract_frame, sample_timestamps_for_shot


def test_sample_timestamps_always_includes_shot_start():
    timestamps = sample_timestamps_for_shot(shot_start=10.0, shot_end=10.5, interval_seconds=2.0)
    assert timestamps == [10.0]


def test_sample_timestamps_covers_long_shot_at_interval():
    timestamps = sample_timestamps_for_shot(shot_start=0.0, shot_end=7.0, interval_seconds=2.0)
    assert timestamps == [0.0, 2.0, 4.0, 6.0]


def test_extract_frame_returns_pil_image(monkeypatch):
    def fake_run(cmd, *args, **kwargs):
        out_path = Path(cmd[-1])
        Image.new("RGB", (2, 2), color="red").save(out_path, format="JPEG")
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    frame = extract_frame("video.mp4", 1.23)

    assert frame.size == (2, 2)
    assert frame.mode == "RGB"


def test_extract_frame_raises_when_ffmpeg_produces_nothing(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: MagicMock(returncode=1, stderr="boom")
    )
    try:
        extract_frame("video.mp4", 0.0)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "boom" in str(exc)
