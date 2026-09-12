"""Thin wrapper around getting hold of the DaVinci Resolve scripting objects.

When this script runs from Resolve's own Workspace > Scripts menu, Resolve
injects a `bmd` module into the script's global namespace before executing
it (this is documented Resolve behaviour, not something we can import
normally). entry.py passes that `bmd` object in here explicitly so this
module stays importable/testable outside of Resolve too.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ResolveUnavailableError(RuntimeError):
    """Raised when this code is running outside of Resolve (e.g. in tests
    or a plain Python REPL) and no `bmd` object was supplied."""


@dataclass
class ResolveHandles:
    resolve: Any
    project_manager: Any
    project: Any
    media_pool: Any
    media_storage: Any

    @property
    def current_timeline(self) -> Any:
        return self.project.GetCurrentTimeline()


def connect(bmd: Any) -> ResolveHandles:
    """`bmd` is the object Resolve injects into scripts it runs itself.
    Pass it straight from entry.py's global scope -- see README for why we
    can't just `import bmd`."""
    if bmd is None:
        raise ResolveUnavailableError(
            "No `bmd` object provided. This module only works when invoked "
            "from inside DaVinci Resolve's Scripts menu (see entry.py)."
        )

    resolve = bmd.scriptapp("Resolve")
    if resolve is None:
        raise ResolveUnavailableError(
            "bmd.scriptapp('Resolve') returned None. Make sure DaVinci Resolve "
            "is running and that scripting is enabled in "
            "Preferences > System > General."
        )

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    if project is None:
        raise ResolveUnavailableError(
            "No project is currently open in Resolve. Open or create a "
            "project before running Auto Template."
        )

    media_pool = project.GetMediaPool()
    media_storage = resolve.GetMediaStorage()

    return ResolveHandles(
        resolve=resolve,
        project_manager=project_manager,
        project=project,
        media_pool=media_pool,
        media_storage=media_storage,
    )
