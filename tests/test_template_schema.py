from resolve_plugin.analysis.template_schema import (
    ClipSlot,
    EffectNote,
    Gap,
    Template,
    TextOverlay,
    TransformEffect,
)


def test_round_trip_to_dict_from_dict():
    template = Template(
        source_video_path="/videos/source.mp4",
        fps=30.0,
        clips=[
            ClipSlot(
                index=0,
                source_in_seconds=0.0,
                source_out_seconds=2.5,
                timeline_start_seconds=0.0,
                transforms=[TransformEffect(kind="zoom_in", properties={"ZoomX": 1.2})],
            ),
            ClipSlot(index=1, source_in_seconds=3.0, source_out_seconds=5.0, timeline_start_seconds=3.0),
        ],
        gaps=[Gap(start_seconds=2.5, end_seconds=3.0)],
        texts=[TextOverlay(content="Hello", start_seconds=0.5, end_seconds=1.5)],
        effect_notes=[EffectNote(label="cross dissolve", at_seconds=2.5, confidence=0.8)],
    )

    data = template.to_dict()
    restored = Template.from_dict(data)

    assert restored.source_video_path == template.source_video_path
    assert restored.fps == template.fps
    assert len(restored.clips) == 2
    assert restored.clips[0].transforms[0].kind == "zoom_in"
    assert restored.clips[0].transforms[0].properties == {"ZoomX": 1.2}
    assert restored.gaps[0].start_seconds == 2.5
    assert restored.texts[0].content == "Hello"
    assert restored.effect_notes[0].label == "cross dissolve"


def test_clip_slot_duration():
    clip = ClipSlot(index=0, source_in_seconds=1.0, source_out_seconds=4.5, timeline_start_seconds=1.0)
    assert clip.duration_seconds == 3.5
