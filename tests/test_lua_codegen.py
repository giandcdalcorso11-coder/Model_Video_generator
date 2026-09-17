import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from resolve_plugin.analysis.template_schema import (
    ClipSlot,
    EffectNote,
    Gap,
    MusicSegment,
    Template,
    TextOverlay,
    TransformEffect,
    VoiceSegment,
)
from resolve_plugin.lua_codegen import _lua_literal, _lua_long_string, generate_lua_script


def _fake_ffmpeg_run(cmd, *args, **kwargs):
    Path(cmd[-1]).write_bytes(b"fake media bytes")
    return MagicMock(returncode=0, stderr="")


def test_lua_long_string_basic():
    assert _lua_long_string("hello") == "[[hello]]"


def test_lua_long_string_escalates_when_value_contains_closer():
    value = "some ]] text"
    result = _lua_long_string(value)
    assert result == "[=[some ]] text]=]"


def test_lua_literal_types():
    assert _lua_literal(True) == "true"
    assert _lua_literal(False) == "false"
    assert _lua_literal(1.5) == "1.5"
    assert _lua_literal("hi") == "[[hi]]"


def make_template(**overrides):
    defaults = dict(
        source_video_path="/videos/source.mp4",
        fps=25.0,
        clips=[
            ClipSlot(index=0, source_in_seconds=0.0, source_out_seconds=2.0, timeline_start_seconds=0.0),
            ClipSlot(index=1, source_in_seconds=3.0, source_out_seconds=5.0, timeline_start_seconds=3.0),
        ],
        gaps=[Gap(start_seconds=2.0, end_seconds=3.0)],
        texts=[TextOverlay(content="ISCRIVITI", start_seconds=0.5, end_seconds=1.0)],
        dialogue=[TextOverlay(content="ciao a tutti", start_seconds=0.0, end_seconds=1.0)],
        effect_notes=[EffectNote(label="dissolve", at_seconds=2.0, confidence=0.6, source="ai")],
        voice_segments=[VoiceSegment(index=0, start_seconds=0.0, end_seconds=1.0, transcript="ciao a tutti")],
        music_segments=[MusicSegment(index=0, start_seconds=1.0, end_seconds=5.0)],
    )
    defaults.update(overrides)
    return Template(**defaults)


def test_generate_lua_script_never_uses_io_or_os_execute(tmp_path):
    """The whole point of code generation: the emitted script must not rely
    on Lua's `io` library or `os.execute`, both confirmed disabled in
    Resolve's real scripting sandbox."""
    template = make_template()
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        src = generate_lua_script(template, "TestTimeline", tmp_path)

    assert "io." not in src
    assert "os.execute" not in src
    assert "bmd.readfile" not in src
    assert "bmd.writefile" not in src


def test_generate_lua_script_is_syntactically_plausible_and_complete(tmp_path):
    template = make_template()
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        src = generate_lua_script(template, "TestTimeline", tmp_path)

    assert 'mediaPool:CreateEmptyTimeline([[TestTimeline]])' in src
    assert "startFrame = 0, endFrame = 49" in src  # clip 0: 0-2s @ 25fps
    assert "startFrame = 75, endFrame = 124" in src  # clip 1: 3-5s @ 25fps
    assert "endFrame = 24" in src  # 1s gap placeholder @ 25fps
    assert 'timeline:AddMarker(50, "Yellow", [[dissolve]]' in src
    assert "Testo a schermo" in src
    assert "Dialogo (trascrizione)" in src
    assert "ISCRIVITI" not in src  # goes into the .srt file, not inline in the script
    assert 'timeline:SetTrackName("audio", voiceTrackIndex, [[Voce]])' in src
    assert 'timeline:SetTrackName("audio", musicTrackIndex, [[Musica]])' in src

    on_screen_srt = (tmp_path / "on_screen_text.srt").read_text(encoding="utf-8")
    assert "ISCRIVITI" in on_screen_srt
    dialogue_srt = (tmp_path / "dialogue.srt").read_text(encoding="utf-8")
    assert "ciao a tutti" in dialogue_srt


def test_generate_lua_script_pins_voice_and_music_appends_to_absolute_record_frame(tmp_path):
    """Regression test: AppendToTimeline lands at the end of the whole
    timeline's current duration regardless of trackIndex (confirmed on a
    real Resolve install -- Voice/Music tracks ended up appended after the
    video instead of aligned in time with it). Every voice/music append,
    real or silence filler, must pin an explicit recordFrame so it lands at
    the segment's actual absolute position instead. recordFrame is also
    floored at 1 (never literal 0): a real Resolve install placed a
    recordFrame=0 item at the end of the timeline instead of the start."""
    template = make_template()  # voice: 0.0-1.0s, music: 1.0-5.0s @ 25fps
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        src = generate_lua_script(template, "TestTimeline", tmp_path)

    assert src.count("mediaType = 2, trackIndex = voiceTrackIndex, recordFrame = 1") == 1  # voice clip
    assert src.count("trackIndex = musicTrackIndex, recordFrame = 1") == 1  # its music-track silence filler
    assert src.count("mediaType = 2, trackIndex = musicTrackIndex, recordFrame = 25") == 1  # music clip
    assert src.count("trackIndex = voiceTrackIndex, recordFrame = 25") == 1  # its voice-track silence filler
    assert "recordFrame = 0" not in src

    # Regression: separate AppendToTimeline calls (one per item) did not
    # reliably honor recordFrame on a real Resolve install, even after the
    # 0-vs-1 fix above. Every item needing a specific position must go
    # through table.insert(positionedClips, ...) and get placed by a SINGLE
    # batched AppendToTimeline(positionedClips) call instead.
    assert src.count("table.insert(positionedClips") >= 4  # voice+filler, music+filler
    assert src.count("mediaPool:AppendToTimeline(positionedClips)") == 1


def test_generate_lua_script_applies_transforms(tmp_path):
    template = make_template(
        clips=[
            ClipSlot(
                index=0, source_in_seconds=0.0, source_out_seconds=2.0, timeline_start_seconds=0.0,
                transforms=[TransformEffect(kind="zoom_in", properties={"ZoomX": 1.2, "ZoomGang": True})],
            ),
        ],
        gaps=[],
    )
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        src = generate_lua_script(template, "TestTimeline", tmp_path)

    assert 'appended[1]:SetProperty([[ZoomX]], 1.2)' in src
    assert 'appended[1]:SetProperty([[ZoomGang]], true)' in src


def test_generate_lua_script_skips_empty_sections(tmp_path):
    template = make_template(texts=[], dialogue=[], voice_segments=[], music_segments=[], effect_notes=[])
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        src = generate_lua_script(template, "TestTimeline", tmp_path)

    assert "ImportIntoTimeline" not in src
    assert "AddTrack" not in src
    assert "AddMarker" not in src
    assert not (tmp_path / "on_screen_text.srt").exists()
    assert not (tmp_path / "dialogue.srt").exists()


def test_generate_lua_script_skips_zero_duration_gap(tmp_path):
    template = make_template(
        gaps=[Gap(start_seconds=2.0, end_seconds=2.0)],
        voice_segments=[],
        music_segments=[],
    )
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run) as mock_run:
        generate_lua_script(template, "TestTimeline", tmp_path)
    mock_run.assert_not_called()


def _find_lua_interpreter():
    for name in ("lua5.1", "lua", "luajit"):
        path = shutil.which(name)
        if path:
            return path
    return None


LUA_INTERPRETER = _find_lua_interpreter()


@pytest.mark.skipif(LUA_INTERPRETER is None, reason="no Lua 5.1-compatible interpreter on PATH")
def test_generated_script_runs_correctly_against_resolve_stub_with_sandbox_enforced(tmp_path):
    """End-to-end proof, not just a string search: run the generated script
    through an actual Lua interpreter with `io`/`os.execute` forced to nil
    (matching Resolve's real sandbox) against stub Resolve objects, and
    check the exact sequence of API calls it makes."""
    template = make_template()
    with patch("subprocess.run", side_effect=_fake_ffmpeg_run):
        src = generate_lua_script(template, "TestTimeline", tmp_path)

    script_path = tmp_path / "generated.lua"
    script_path.write_text(src, encoding="utf-8")

    harness_path = Path(__file__).parent / "lua_stub_harness.lua"
    proc = subprocess.run(
        [LUA_INTERPRETER, str(harness_path), str(script_path)],
        capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr

    assert "SCRIPT ERROR" not in output, output
    assert "MediaPool:CreateEmptyTimeline(TestTimeline)" in output
    assert "MediaPool:AppendToTimeline(0, 49" in output  # clip 0: 0-2s @ 25fps
    assert "MediaPool:AppendToTimeline(75, 124" in output  # clip 1: 3-5s @ 25fps
    assert "Timeline:AddMarker(50, Yellow, dissolve" in output

    # Voice (0-1s) and music (1-5s) appends must carry an explicit recordFrame
    # (last arg) so they land at their real timeline position instead of
    # wherever AppendToTimeline's own end-of-timeline pointer happens to be.
    # recordFrame is floored at 1 (never literal 0, see lua_codegen.py).
    assert "MediaPool:AppendToTimeline(0, 24, 2, 2, 1)" in output  # voice clip, recordFrame=1 (floored)
    assert "MediaPool:AppendToTimeline(25, 124, 2, 3, 25)" in output  # music clip, recordFrame=25
    assert "Timeline:SetTrackName(subtitle" in output
    assert "Voce" in output
    assert "Musica" in output
