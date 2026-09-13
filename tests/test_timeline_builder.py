from pathlib import Path
from unittest.mock import MagicMock, patch

from resolve_plugin.analysis.template_schema import (
    ClipSlot,
    EffectNote,
    Gap,
    MusicSegment,
    Template,
    TextOverlay,
    VoiceSegment,
)
from resolve_plugin.resolve_api.connection import ResolveHandles
from resolve_plugin.resolve_api.timeline_builder import build_timeline


def _fake_ffmpeg_run(cmd, *args, **kwargs):
    out_path = Path(cmd[-1])
    out_path.write_bytes(b"fake media bytes")
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

    # A newly created Resolve timeline starts with 1 video + 1 audio track
    # and 0 subtitle tracks; AddTrack/ImportIntoTimeline(as subtitle) grow
    # those counts, mirroring real Resolve behaviour closely enough to
    # exercise timeline_builder's track-index bookkeeping.
    track_counts = {"video": 1, "audio": 1, "subtitle": 0}
    timeline.GetTrackCount.side_effect = lambda track_type: track_counts[track_type]
    timeline.AddTrack.side_effect = lambda track_type: track_counts.__setitem__(
        track_type, track_counts[track_type] + 1
    )
    timeline.ImportIntoTimeline.side_effect = lambda *a, **k: track_counts.__setitem__(
        "subtitle", track_counts["subtitle"] + 1
    )

    handles = ResolveHandles(
        resolve=MagicMock(),
        project_manager=MagicMock(),
        project=project,
        media_pool=media_pool,
        media_storage=MagicMock(),
    )
    return handles, timeline, appended_items, track_counts


def make_template(**overrides):
    defaults = dict(
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
    defaults.update(overrides)
    return Template(**defaults)


def test_build_timeline_creates_and_selects_timeline(tmp_path):
    handles, timeline, _, _ = make_handles()
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    handles.media_pool.CreateEmptyTimeline.assert_called_once_with("MyTimeline")
    handles.project.SetCurrentTimeline.assert_called_once_with(timeline)


def test_build_timeline_appends_clips_and_gap_in_chronological_order(tmp_path):
    handles, timeline, appended_items, _ = make_handles()
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        result = build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    calls = handles.media_pool.AppendToTimeline.call_args_list
    assert len(calls) == 3

    first_clip_info = calls[0].args[0][0]
    assert first_clip_info["startFrame"] == 0
    assert first_clip_info["endFrame"] == 49

    gap_info = calls[1].args[0][0]
    assert gap_info["startFrame"] == 0
    assert gap_info["endFrame"] == 24

    second_clip_info = calls[2].args[0][0]
    assert second_clip_info["startFrame"] == 75
    assert second_clip_info["endFrame"] == 124

    assert result.clip_items[0] is appended_items[0]
    assert result.clip_items[1] is appended_items[2]
    assert set(result.clip_items.keys()) == {0, 1}


def test_build_timeline_adds_marker_for_effect_note(tmp_path):
    handles, timeline, _, _ = make_handles()
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    timeline.AddMarker.assert_called_once()
    args = timeline.AddMarker.call_args.args
    assert args[0] == 50  # 2.0s @ 25fps
    assert args[1] == "Yellow"
    assert args[2] == "dissolve"


def test_build_timeline_injects_on_screen_text_as_named_subtitle_track(tmp_path):
    handles, timeline, _, _ = make_handles()
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    timeline.ImportIntoTimeline.assert_called_once()
    srt_path_arg, options = timeline.ImportIntoTimeline.call_args.args
    assert srt_path_arg.endswith("on_screen_text.srt")
    assert options == {"insertAsSubtitle": True}

    srt_content = Path(srt_path_arg).read_text(encoding="utf-8")
    assert "Hi" in srt_content
    assert "00:00:00,500" in srt_content

    timeline.SetTrackName.assert_any_call("subtitle", 1, "Testo a schermo")


def test_build_timeline_skips_srt_when_no_text(tmp_path):
    handles, timeline, _, _ = make_handles()
    template = make_template(texts=[])

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    timeline.ImportIntoTimeline.assert_not_called()


def test_build_timeline_raises_if_create_timeline_fails(tmp_path):
    handles, _, _, _ = make_handles()
    handles.media_pool.CreateEmptyTimeline.return_value = None
    template = make_template()

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        try:
            build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "MyTimeline" in str(exc)


def test_dialogue_and_on_screen_text_use_separate_files_and_tracks(tmp_path):
    """The core non-conflict guarantee the user asked for: on-screen text
    and spoken dialogue must never mix into the same file or track."""
    handles, timeline, _, _ = make_handles()
    template = make_template(
        texts=[TextOverlay(content="ISCRIVITI!", start_seconds=0.0, end_seconds=1.0)],
        dialogue=[TextOverlay(content="ciao a tutti", start_seconds=0.0, end_seconds=1.0)],
    )

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    assert timeline.ImportIntoTimeline.call_count == 2
    srt_paths = [call.args[0] for call in timeline.ImportIntoTimeline.call_args_list]
    assert srt_paths[0].endswith("on_screen_text.srt")
    assert srt_paths[1].endswith("dialogue.srt")

    on_screen_content = Path(srt_paths[0]).read_text(encoding="utf-8")
    dialogue_content = Path(srt_paths[1]).read_text(encoding="utf-8")
    assert "ISCRIVITI!" in on_screen_content
    assert "ciao a tutti" not in on_screen_content
    assert "ciao a tutti" in dialogue_content
    assert "ISCRIVITI!" not in dialogue_content

    timeline.SetTrackName.assert_any_call("subtitle", 1, "Testo a schermo")
    timeline.SetTrackName.assert_any_call("subtitle", 2, "Dialogo (trascrizione)")


def test_build_timeline_adds_no_audio_tracks_when_no_speech_analysis(tmp_path):
    handles, timeline, _, _ = make_handles()
    template = make_template()  # voice_segments/music_segments default to []

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    timeline.AddTrack.assert_not_called()


def test_build_timeline_creates_voice_and_music_tracks(tmp_path):
    handles, timeline, _, track_counts = make_handles()
    template = make_template(
        voice_segments=[VoiceSegment(index=0, start_seconds=0.0, end_seconds=1.0, transcript="ciao")],
        music_segments=[MusicSegment(index=0, start_seconds=1.0, end_seconds=3.0)],
    )

    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        build_timeline(handles, template, "MyTimeline", work_dir=tmp_path)

    assert timeline.AddTrack.call_args_list == [
        (("audio",), {}),
        (("audio",), {}),
    ]
    timeline.SetTrackName.assert_any_call("audio", 2, "Voce")
    timeline.SetTrackName.assert_any_call("audio", 3, "Musica")

    audio_calls = [
        c for c in handles.media_pool.AppendToTimeline.call_args_list
        if "trackIndex" in c.args[0][0]
    ]
    assert len(audio_calls) == 4  # voice+silence for each of the 2 segments

    by_track = {2: [], 3: []}
    for c in audio_calls:
        info = c.args[0][0]
        by_track[info["trackIndex"]].append(info)

    # Voice track: real audio (mediaType=2) for the voice segment, silence for the music segment.
    voice_track_real = [i for i in by_track[2] if i.get("mediaType") == 2]
    voice_track_silence = [i for i in by_track[2] if "mediaType" not in i]
    assert len(voice_track_real) == 1
    assert voice_track_real[0]["startFrame"] == 0
    assert voice_track_real[0]["endFrame"] == 24  # 1.0s @ 25fps
    assert len(voice_track_silence) == 1
    assert voice_track_silence[0]["endFrame"] == 49  # 2.0s music segment duration @ 25fps

    # Music track: mirror image.
    music_track_real = [i for i in by_track[3] if i.get("mediaType") == 2]
    music_track_silence = [i for i in by_track[3] if "mediaType" not in i]
    assert len(music_track_real) == 1
    assert music_track_real[0]["startFrame"] == 25  # 1.0s @ 25fps
    assert music_track_real[0]["endFrame"] == 74  # 3.0s @ 25fps - 1
    assert len(music_track_silence) == 1
    assert music_track_silence[0]["endFrame"] == 24  # 1.0s voice segment duration @ 25fps
