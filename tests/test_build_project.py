from pathlib import Path

import pytest

from resolve_plugin import build_project
from resolve_plugin.analysis.template_schema import ClipSlot, Template


@pytest.fixture
def fake_video(tmp_path):
    path = tmp_path / "my_video.mp4"
    path.write_bytes(b"fake video bytes")
    return path


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    projects_root = tmp_path / "projects"
    scripts_dir = tmp_path / "scripts_edit"
    monkeypatch.setattr(build_project, "_projects_root", lambda: projects_root)
    monkeypatch.setattr(build_project, "_fusion_scripts_edit_dir", lambda: scripts_dir)
    return projects_root, scripts_dir


def test_wrong_argument_count_returns_usage_error():
    assert build_project.main([]) == 2
    assert build_project.main(["a", "b"]) == 2


def test_missing_video_returns_error(tmp_path, capsys):
    exit_code = build_project.main([str(tmp_path / "missing.mp4")])
    assert exit_code == 1
    assert "non trovato" in capsys.readouterr().err


def test_success_writes_lua_script_into_scripts_edit_dir(monkeypatch, fake_video, isolated_dirs, capsys):
    projects_root, scripts_dir = isolated_dirs

    fake_template = Template(
        source_video_path="unused",
        fps=25.0,
        clips=[ClipSlot(index=0, source_in_seconds=0.0, source_out_seconds=1.0, timeline_start_seconds=0.0)],
    )
    monkeypatch.setattr(build_project, "analyze_video", lambda video_path, progress_callback=None: fake_template)

    exit_code = build_project.main([str(fake_video)])

    assert exit_code == 0
    lua_files = list(scripts_dir.glob("*.lua"))
    assert len(lua_files) == 1
    assert lua_files[0].name.startswith("Auto Template - my_video_")

    content = lua_files[0].read_text(encoding="utf-8")
    assert "mediaPool:CreateEmptyTimeline" in content
    assert "io." not in content
    assert "os.execute" not in content

    project_dirs = list(projects_root.iterdir())
    assert len(project_dirs) == 1
    assert (project_dirs[0] / "source_video.mp4").read_bytes() == b"fake video bytes"

    out = capsys.readouterr().out
    assert "Fatto!" in out


def test_analysis_failure_returns_error_and_writes_no_script(monkeypatch, fake_video, isolated_dirs, capsys):
    projects_root, scripts_dir = isolated_dirs

    def raise_error(video_path, progress_callback=None):
        raise RuntimeError("ffmpeg non disponibile")

    monkeypatch.setattr(build_project, "analyze_video", raise_error)

    exit_code = build_project.main([str(fake_video)])

    assert exit_code == 1
    assert "ffmpeg non disponibile" in capsys.readouterr().err
    assert not scripts_dir.exists() or not list(scripts_dir.glob("*.lua"))
