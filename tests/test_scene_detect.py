import sys
import types
from unittest.mock import MagicMock, patch

from resolve_plugin.analysis import scene_detect


def _fake_completed_process(returncode=0, stdout="", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_probe_duration_and_fps_parses_ffprobe_json():
    ffprobe_json = (
        '{"streams": [{"r_frame_rate": "30000/1001", "duration": "12.5"}], '
        '"format": {"duration": "12.5"}}'
    )
    with patch("subprocess.run", return_value=_fake_completed_process(stdout=ffprobe_json)):
        duration, fps = scene_detect.probe_duration_and_fps("video.mp4")

    assert duration == 12.5
    assert round(fps, 2) == 29.97


def test_probe_duration_and_fps_raises_on_ffprobe_failure():
    with patch("subprocess.run", return_value=_fake_completed_process(returncode=1, stderr="no such file")):
        try:
            scene_detect.probe_duration_and_fps("missing.mp4")
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "no such file" in str(exc)


def test_detect_shots_converts_scene_list(monkeypatch):
    fake_start = MagicMock()
    fake_start.get_seconds.return_value = 0.0
    fake_end = MagicMock()
    fake_end.get_seconds.return_value = 2.0

    fake_scene_manager_instance = MagicMock()
    fake_scene_manager_instance.get_scene_list.return_value = [(fake_start, fake_end)]

    fake_scenedetect_module = types.ModuleType("scenedetect")
    fake_scenedetect_module.open_video = MagicMock(return_value=MagicMock())
    fake_scenedetect_module.SceneManager = MagicMock(return_value=fake_scene_manager_instance)

    fake_detectors_module = types.ModuleType("scenedetect.detectors")
    fake_detectors_module.ContentDetector = MagicMock()

    monkeypatch.setitem(sys.modules, "scenedetect", fake_scenedetect_module)
    monkeypatch.setitem(sys.modules, "scenedetect.detectors", fake_detectors_module)

    shots = scene_detect.detect_shots("video.mp4", threshold=27.0)

    assert len(shots) == 1
    assert shots[0].start_seconds == 0.0
    assert shots[0].end_seconds == 2.0
    assert shots[0].duration_seconds == 2.0


def test_detect_shots_falls_back_to_single_shot_when_no_cuts(monkeypatch):
    fake_scene_manager_instance = MagicMock()
    fake_scene_manager_instance.get_scene_list.return_value = []

    fake_scenedetect_module = types.ModuleType("scenedetect")
    fake_scenedetect_module.open_video = MagicMock(return_value=MagicMock())
    fake_scenedetect_module.SceneManager = MagicMock(return_value=fake_scene_manager_instance)

    fake_detectors_module = types.ModuleType("scenedetect.detectors")
    fake_detectors_module.ContentDetector = MagicMock()

    monkeypatch.setitem(sys.modules, "scenedetect", fake_scenedetect_module)
    monkeypatch.setitem(sys.modules, "scenedetect.detectors", fake_detectors_module)

    with patch.object(scene_detect, "probe_duration_and_fps", return_value=(10.0, 30.0)):
        shots = scene_detect.detect_shots("video.mp4")

    assert len(shots) == 1
    assert shots[0].start_seconds == 0.0
    assert shots[0].end_seconds == 10.0


def test_detect_silences_parses_ffmpeg_stderr():
    stderr = (
        "[silencedetect @ 0x1] silence_start: 1.5\n"
        "[silencedetect @ 0x1] silence_end: 2.75 | silence_duration: 1.25\n"
    )
    with patch("subprocess.run", return_value=_fake_completed_process(stderr=stderr)):
        ranges = scene_detect.detect_silences("video.mp4")

    assert len(ranges) == 1
    assert ranges[0].start_seconds == 1.5
    assert ranges[0].end_seconds == 2.75


def test_detect_black_frames_parses_ffmpeg_stderr():
    stderr = "[blackdetect @ 0x1] black_start:0.0 black_end:0.5 black_duration:0.5\n"
    with patch("subprocess.run", return_value=_fake_completed_process(stderr=stderr)):
        ranges = scene_detect.detect_black_frames("video.mp4")

    assert len(ranges) == 1
    assert ranges[0].start_seconds == 0.0
    assert ranges[0].end_seconds == 0.5
