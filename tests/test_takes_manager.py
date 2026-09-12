from unittest.mock import MagicMock

import pytest

from resolve_plugin.resolve_api.takes_manager import list_takes, replace_clip_footage


def test_replace_clip_footage_adds_and_selects_take():
    media_pool = MagicMock()
    replacement_item = MagicMock()
    media_pool.ImportMedia.return_value = [replacement_item]

    timeline_item = MagicMock()
    timeline_item.AddTake.return_value = True
    timeline_item.GetTakesCount.return_value = 2
    timeline_item.SelectTakeByIndex.return_value = True

    clip_items = {0: timeline_item}

    new_index = replace_clip_footage(media_pool, clip_items, 0, "/videos/my_clip.mp4")

    media_pool.ImportMedia.assert_called_once_with(["/videos/my_clip.mp4"])
    timeline_item.AddTake.assert_called_once_with(replacement_item)
    timeline_item.SelectTakeByIndex.assert_called_once_with(2)
    assert new_index == 2


def test_replace_clip_footage_passes_explicit_in_out():
    media_pool = MagicMock()
    media_pool.ImportMedia.return_value = [MagicMock()]
    timeline_item = MagicMock()
    timeline_item.AddTake.return_value = True
    timeline_item.GetTakesCount.return_value = 3
    timeline_item.SelectTakeByIndex.return_value = True

    replace_clip_footage(
        media_pool, {5: timeline_item}, 5, "/videos/clip.mp4", start_frame=10, end_frame=100
    )

    args = timeline_item.AddTake.call_args.args
    assert args[1:] == (10, 100)


def test_replace_clip_footage_unknown_clip_index_raises_key_error():
    with pytest.raises(KeyError):
        replace_clip_footage(MagicMock(), {}, 0, "/videos/clip.mp4")


def test_replace_clip_footage_raises_when_import_fails():
    media_pool = MagicMock()
    media_pool.ImportMedia.return_value = []
    with pytest.raises(RuntimeError, match="could not import"):
        replace_clip_footage(media_pool, {0: MagicMock()}, 0, "/videos/clip.mp4")


def test_replace_clip_footage_raises_when_add_take_refused():
    media_pool = MagicMock()
    media_pool.ImportMedia.return_value = [MagicMock()]
    timeline_item = MagicMock()
    timeline_item.AddTake.return_value = False

    with pytest.raises(RuntimeError, match="refused"):
        replace_clip_footage(media_pool, {0: timeline_item}, 0, "/videos/clip.mp4")


def test_replace_clip_footage_raises_when_select_fails():
    media_pool = MagicMock()
    media_pool.ImportMedia.return_value = [MagicMock()]
    timeline_item = MagicMock()
    timeline_item.AddTake.return_value = True
    timeline_item.GetTakesCount.return_value = 2
    timeline_item.SelectTakeByIndex.return_value = False

    with pytest.raises(RuntimeError, match="could not select"):
        replace_clip_footage(media_pool, {0: timeline_item}, 0, "/videos/clip.mp4")


def test_list_takes_returns_empty_when_no_take_selector():
    timeline_item = MagicMock()
    timeline_item.GetTakesCount.return_value = 0
    result = list_takes({0: timeline_item}, 0)
    assert result == []


def test_list_takes_marks_selected_take():
    timeline_item = MagicMock()
    timeline_item.GetTakesCount.return_value = 2
    timeline_item.GetSelectedTakeIndex.return_value = 2

    original_media = MagicMock()
    original_media.GetName.return_value = "original.mp4"
    replacement_media = MagicMock()
    replacement_media.GetName.return_value = "replacement.mp4"

    def get_take_by_index(i):
        return {1: {"mediaPoolItem": original_media}, 2: {"mediaPoolItem": replacement_media}}[i]

    timeline_item.GetTakeByIndex.side_effect = get_take_by_index

    takes = list_takes({0: timeline_item}, 0)

    assert len(takes) == 2
    assert takes[0].index == 1 and not takes[0].is_selected
    assert takes[0].media_pool_item_name == "original.mp4"
    assert takes[1].index == 2 and takes[1].is_selected
    assert takes[1].media_pool_item_name == "replacement.mp4"


def test_list_takes_unknown_clip_index_raises_key_error():
    with pytest.raises(KeyError):
        list_takes({}, 0)
