import json
from pathlib import Path

import pytest

from resolve_plugin import analyze_cli
from resolve_plugin.analysis.template_schema import ClipSlot, Template
from resolve_plugin.config import TEMPLATE_FILENAME


@pytest.fixture
def fake_video(tmp_path):
    path = tmp_path / "my_video.mp4"
    path.write_bytes(b"fake video bytes")
    return path


def test_wrong_argument_count_returns_usage_error(capsys):
    assert analyze_cli.main([]) == 2
    assert analyze_cli.main(["only-one-arg"]) == 2


def test_missing_video_file_returns_error(tmp_path, capsys):
    project_dir = tmp_path / "project"
    exit_code = analyze_cli.main([str(tmp_path / "does_not_exist.mp4"), str(project_dir)])
    assert exit_code == 1
    assert "non trovato" in capsys.readouterr().err


def test_success_copies_video_and_writes_template(monkeypatch, fake_video, tmp_path, capsys):
    project_dir = tmp_path / "project"

    fake_template = Template(
        source_video_path="unused",
        fps=25.0,
        clips=[ClipSlot(index=0, source_in_seconds=0.0, source_out_seconds=1.0, timeline_start_seconds=0.0)],
    )

    captured_args = {}

    def fake_analyze_video(video_path, progress_callback=None):
        captured_args["video_path"] = video_path
        if progress_callback:
            progress_callback(0, 100, "iniziato")
            progress_callback(100, 100, "fatto")
        return fake_template

    monkeypatch.setattr(analyze_cli, "analyze_video", fake_analyze_video)

    exit_code = analyze_cli.main([str(fake_video), str(project_dir)])

    assert exit_code == 0
    assert (project_dir / "source_video.mp4").read_bytes() == b"fake video bytes"
    assert captured_args["video_path"] == str(project_dir / "source_video.mp4")

    template_path = project_dir / TEMPLATE_FILENAME
    assert template_path.exists()
    data = json.loads(template_path.read_text(encoding="utf-8"))
    assert data["fps"] == 25.0
    assert len(data["clips"]) == 1

    out = capsys.readouterr().out
    assert "[0/100] iniziato" in out
    assert "[100/100] fatto" in out


def test_analysis_failure_returns_error_and_no_template(monkeypatch, fake_video, tmp_path, capsys):
    project_dir = tmp_path / "project"

    def raise_error(video_path, progress_callback=None):
        raise RuntimeError("ffmpeg non disponibile")

    monkeypatch.setattr(analyze_cli, "analyze_video", raise_error)

    exit_code = analyze_cli.main([str(fake_video), str(project_dir)])

    assert exit_code == 1
    assert "ffmpeg non disponibile" in capsys.readouterr().err
    assert not (project_dir / TEMPLATE_FILENAME).exists()
