""""Replace with my own footage" workflow, built on Resolve's native Takes.

Calling TimelineItem.AddTake() on a plain clip auto-initializes a take
selector for it the first time (the original clip becomes take 1), so we
never have to manage that ourselves -- we only ever add the user's
replacement as a new take and select it, which preserves the slot's
position, duration and any transform effects/markers already on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TakeInfo:
    index: int
    is_selected: bool
    media_pool_item_name: str


def replace_clip_footage(
    media_pool: Any,
    clip_items: dict[int, Any],
    clip_index: int,
    replacement_media_path: str,
    start_frame: Optional[int] = None,
    end_frame: Optional[int] = None,
) -> int:
    """Adds `replacement_media_path` as a new take on the timeline item for
    `clip_index` (as produced by timeline_builder.build_timeline) and
    selects it. Returns the new take's 1-based index.

    start_frame/end_frame are the replacement clip's OWN in/out points
    (defaults to its full extent) -- they are unrelated to the original
    slot's duration, which Resolve keeps fixed regardless of the take's
    native length.
    """
    timeline_item = clip_items.get(clip_index)
    if timeline_item is None:
        raise KeyError(f"No timeline item recorded for clip slot {clip_index}.")

    imported = media_pool.ImportMedia([replacement_media_path])
    if not imported:
        raise RuntimeError(f"Resolve could not import {replacement_media_path}.")
    replacement_item = imported[0]

    if start_frame is not None and end_frame is not None:
        added = timeline_item.AddTake(replacement_item, start_frame, end_frame)
    else:
        added = timeline_item.AddTake(replacement_item)

    if not added:
        raise RuntimeError(
            f"Resolve refused to add {replacement_media_path} as a take for clip {clip_index}."
        )

    new_index = timeline_item.GetTakesCount()
    if not timeline_item.SelectTakeByIndex(new_index):
        raise RuntimeError(f"Added the take but could not select it (index {new_index}).")
    return new_index


def list_takes(clip_items: dict[int, Any], clip_index: int) -> list[TakeInfo]:
    timeline_item = clip_items.get(clip_index)
    if timeline_item is None:
        raise KeyError(f"No timeline item recorded for clip slot {clip_index}.")

    count = timeline_item.GetTakesCount()
    if count == 0:
        return []

    selected = timeline_item.GetSelectedTakeIndex()
    takes = []
    for i in range(1, count + 1):
        info = timeline_item.GetTakeByIndex(i)
        media_pool_item = info.get("mediaPoolItem") if info else None
        name = media_pool_item.GetName() if media_pool_item else "?"
        takes.append(TakeInfo(index=i, is_selected=(i == selected), media_pool_item_name=name))
    return takes
