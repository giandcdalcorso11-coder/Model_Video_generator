"""Local, single-user project registry.

No database and no cloud: "my projects" is a folder per project under
CONFIG.projects_root, plus a flat JSON index file so the UI can list them
without scanning the disk every time.

    <projects_root>/
      projects_index.json
      <project_id>/
        source_video.<ext>       (copy of the uploaded video)
        template.json            (extracted template, once analysis finishes)
        thumbnail.jpg            (optional, for the projects list UI)
        replacements/            (user's own footage assigned per clip slot)
"""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from resolve_plugin.config import CONFIG, PROJECTS_INDEX_FILENAME, TEMPLATE_FILENAME

STATUS_NEW = "new"
STATUS_ANALYZING = "analyzing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


@dataclass
class ProjectRecord:
    id: str
    name: str
    created_at: str
    status: str = STATUS_NEW
    source_video_filename: str = ""
    error_message: str = ""

    @property
    def folder(self) -> Path:
        return CONFIG.projects_root / self.id

    @property
    def source_video_path(self) -> Path:
        return self.folder / self.source_video_filename

    @property
    def template_path(self) -> Path:
        return self.folder / TEMPLATE_FILENAME

    @property
    def thumbnail_path(self) -> Path:
        return self.folder / "thumbnail.jpg"

    @property
    def replacements_dir(self) -> Path:
        return self.folder / "replacements"


class ProjectStore:
    """Reads/writes projects_index.json. Not process-safe for concurrent
    writers, which is fine: this plugin is single-user and single-window."""

    def __init__(self, projects_root: Optional[Path] = None):
        self.projects_root = projects_root or CONFIG.projects_root
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.projects_root / PROJECTS_INDEX_FILENAME
        if not self.index_path.exists():
            self._write_index([])

    def _read_index(self) -> list[dict]:
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _write_index(self, records: list[dict]) -> None:
        self.index_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    def list_projects(self) -> list[ProjectRecord]:
        records = [ProjectRecord(**r) for r in self._read_index()]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records

    def get(self, project_id: str) -> Optional[ProjectRecord]:
        for r in self.list_projects():
            if r.id == project_id:
                return r
        return None

    def create_project(self, name: str, source_video_path: Path) -> ProjectRecord:
        """Copies the uploaded video into a fresh project folder and
        registers it in the index with status=new."""
        project_id = uuid.uuid4().hex[:12]
        record = ProjectRecord(
            id=project_id,
            name=name or source_video_path.stem,
            created_at=datetime.now(timezone.utc).isoformat(),
            status=STATUS_NEW,
            source_video_filename=f"source_video{source_video_path.suffix}",
        )
        record.folder.mkdir(parents=True, exist_ok=True)
        record.replacements_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_video_path, record.source_video_path)

        records = self._read_index()
        records.append(asdict(record))
        self._write_index(records)
        return record

    def update_status(self, project_id: str, status: str, error_message: str = "") -> None:
        records = self._read_index()
        for r in records:
            if r["id"] == project_id:
                r["status"] = status
                r["error_message"] = error_message
        self._write_index(records)

    def delete_project(self, project_id: str) -> None:
        record = self.get(project_id)
        if record is None:
            return
        if record.folder.exists():
            shutil.rmtree(record.folder)
        records = [r for r in self._read_index() if r["id"] != project_id]
        self._write_index(records)
