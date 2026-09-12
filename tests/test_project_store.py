from pathlib import Path

import pytest

from resolve_plugin.storage.project_store import (
    STATUS_FAILED,
    STATUS_NEW,
    STATUS_READY,
    ProjectStore,
)


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "my_video.mp4"
    path.write_bytes(b"fake video bytes")
    return path


def test_create_and_list_project(tmp_path, video_file):
    store = ProjectStore(projects_root=tmp_path / "projects")

    record = store.create_project(name="My Edit", source_video_path=video_file)

    assert record.status == STATUS_NEW
    assert record.source_video_path.exists()
    assert record.source_video_path.read_bytes() == b"fake video bytes"
    assert record.replacements_dir.exists()

    listed = store.list_projects()
    assert len(listed) == 1
    assert listed[0].id == record.id
    assert listed[0].name == "My Edit"


def test_default_name_falls_back_to_filename(tmp_path, video_file):
    store = ProjectStore(projects_root=tmp_path / "projects")
    record = store.create_project(name="", source_video_path=video_file)
    assert record.name == "my_video"


def test_update_status(tmp_path, video_file):
    store = ProjectStore(projects_root=tmp_path / "projects")
    record = store.create_project(name="Test", source_video_path=video_file)

    store.update_status(record.id, STATUS_READY)
    assert store.get(record.id).status == STATUS_READY

    store.update_status(record.id, STATUS_FAILED, error_message="boom")
    reloaded = store.get(record.id)
    assert reloaded.status == STATUS_FAILED
    assert reloaded.error_message == "boom"


def test_delete_project_removes_folder_and_index_entry(tmp_path, video_file):
    store = ProjectStore(projects_root=tmp_path / "projects")
    record = store.create_project(name="ToDelete", source_video_path=video_file)
    assert record.folder.exists()

    store.delete_project(record.id)

    assert not record.folder.exists()
    assert store.get(record.id) is None


def test_get_missing_project_returns_none(tmp_path):
    store = ProjectStore(projects_root=tmp_path / "projects")
    assert store.get("does-not-exist") is None


def test_projects_sorted_newest_first(tmp_path, video_file):
    store = ProjectStore(projects_root=tmp_path / "projects")
    first = store.create_project(name="First", source_video_path=video_file)
    second = store.create_project(name="Second", source_video_path=video_file)

    # created_at is an ISO timestamp string; force a strict ordering even if
    # both projects were created within the same microsecond in CI.
    records = store._read_index()
    for r in records:
        if r["id"] == first.id:
            r["created_at"] = "2020-01-01T00:00:00+00:00"
        else:
            r["created_at"] = "2020-01-02T00:00:00+00:00"
    store._write_index(records)

    listed = store.list_projects()
    assert [r.id for r in listed] == [second.id, first.id]
