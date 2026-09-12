from unittest.mock import MagicMock

import pytest

from resolve_plugin.resolve_api.connection import ResolveUnavailableError, connect


def test_connect_raises_when_bmd_is_none():
    with pytest.raises(ResolveUnavailableError):
        connect(None)


def test_connect_raises_when_resolve_app_unavailable():
    bmd = MagicMock()
    bmd.scriptapp.return_value = None
    with pytest.raises(ResolveUnavailableError):
        connect(bmd)


def test_connect_raises_when_no_project_open():
    bmd = MagicMock()
    resolve = MagicMock()
    bmd.scriptapp.return_value = resolve
    resolve.GetProjectManager.return_value.GetCurrentProject.return_value = None

    with pytest.raises(ResolveUnavailableError):
        connect(bmd)


def test_connect_returns_handles_on_success():
    bmd = MagicMock()
    resolve = MagicMock()
    bmd.scriptapp.return_value = resolve
    project = MagicMock()
    resolve.GetProjectManager.return_value.GetCurrentProject.return_value = project

    handles = connect(bmd)

    assert handles.resolve is resolve
    assert handles.project is project
    assert handles.media_pool is project.GetMediaPool.return_value
    assert handles.media_storage is resolve.GetMediaStorage.return_value
    assert handles.current_timeline is project.GetCurrentTimeline.return_value
