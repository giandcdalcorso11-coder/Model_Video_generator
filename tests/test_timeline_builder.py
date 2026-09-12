from pathlib import Path
from unittest.mock import MagicMock, patch

from resolve_plugin.analysis.template_schema import ClipSlot, EffectNote, Gap, Template, TextOverlay
from resolve_plugin.resolve_api.connection import ResolveHandles
from resolve_plugin.resolve_api.timeline_builder import build_timeline


def _fake_ffmpeg_run(cmd, *args, **kwargs):
    out_path = Path(cmd[-1])
    out_path.write_bytes(b"fake mp4 bytes")
    return MagicMock(returncode=0, stderr="")


def make_handles():
    media_pool = MagicMock()
    project = MagicMock()
    timeline = MagicMock()
    media_pool.CreateEmptyTimeline.return_value = timeline

    appended_items = []

    def fake_append(clip_infos):
        item = MagicMock(name=f"timeline-item-{len(appended_items)}")
        appended_items.append(item)
        return [item]

    media_pool.AppendToTimeline.side_effect = fake_append

    def fake_import_media(paths):
        return [MagicMock(name=f"media-item-for-{paths[0]}")]

    media_pool.ImportMedia.side_effect = fake_import_media

    handles = ResolveHandles(
        resolve=MagicMock(),
        project_manager=MagicMock(),
        project=project,
        media_pool=media_pool,
        media_storage=MagicMock(),
    )
    return handles, timeline, appended_items


def make_template():
    return Template(
        source_video_path="/videos/source.mp4",
        fps=25.0,
        clips=[
            ClipSlot(index=0, source_in_seconds=0.0, source_out_seconds=2.0, timeline_start_seconds=0.0),
            ClipSlot(index=1, source_in_seconds=3.0, source_out_seconds=5.0, timeline_start_seconds=3.0),
        ],
        gaps=[Gap(start_seconds=2.0, end_seconds=3.0)],
        texts=[TextOverlay(content="Hi", start_seconds=0.5, end_seconds=1.0)],
        effect_notes=[EffectNote(label="dissolve", at_seconds=2.0, confidence=0.6, source="ai")],
    )


def test_build_timeline_creates_and_selects_timeline(tmp_path):
    handles, timeline, _ = make_handles()
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    handles.media_pool.CreateEmptyTimeline.assert_called_once_with("MyTimeline")
    handles.project.SetCurrentTimeline.assert_called_once_with(timeline)


def test_build_timeline_appends_clips_and_gap_in_chronological_order(tmp_path):
    handles, timeline, appended_items = make_handles()
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        result = build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    calls = handles.media_pool.AppendToTimeline.call_args_list
    assert len(calls) == 3

    # Clip 0: seconds 0.0 - 2.0 @ 25fps -> frames 0..49
    first_clip_info = calls[0].args[0][0]
    assert first_clip_info["startFrame"] == 0
    assert first_clip_info["endFrame"] == 49

    # Gap: 1.0s duration -> frames 0..24 on the placeholder clip
    gap_info = calls[1].args[0][0]
    assert gap_info["startFrame"] == 0
    assert gap_info["endFrame"] == 24

    # Clip 1: seconds 3.0 - 5.0 @ 25fps -> frames 75..124
    second_clip_info = calls[2].args[0][0]
    assert second_clip_info["startFrame"] == 75
    assert second_clip_info["endFrame"] == 124

    assert result.clip_items[0] is appended_items[0]
    assert result.clip_items[1] is appended_items[2]
    assert set(result.clip_items.keys()) == {0, 1}


def test_build_timeline_adds_marker_for_effect_note(tmp_path):
    handles, timeline, _ = make_handles()
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    timeline.AddMarker.assert_called_once()
    args = timeline.AddMarker.call_args.args
    assert args[0] == 50  # 2.0s @ 25fps
    assert args[1] == "Yellow"
    assert args[2] == "dissolve"


def test_build_timeline_injects_srt_subtitle_track(tmp_path):
    handles, timeline, _ = make_handles()
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    timeline.ImportIntoTimeline.assert_called_once()
    srt_path_arg, options = timeline.ImportIntoTimeline.call_args.args
    assert srt_path_arg.endswith(".srt")
    assert options == {"insertAsSubtitle": True}

    srt_content = Path(srt_path_arg).read_text(encoding="utf-8")
    assert "Hi" in srt_content
    assert "00:00:00,500" in srt_content


def test_build_timeline_skips_srt_when_no_text(tmp_path):
    handles, timeline, _ = make_handles()
    template = make_template()
    template.texts = []

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    timeline.ImportIntoTimeline.assert_not_called()


def test_build_timeline_raises_if_create_timeline_fails(tmp_path):
    handles, _, _ = make_handles()
    handles.media_pool.CreateEmptyTimeline.return_value = None
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        try:
            build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "MyTimeline" in str(exc)
