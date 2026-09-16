"""Command-line entry point: analyzes a video and writes a ready-to-run Lua
script directly into Resolve's Scripts/Edit folder.

Usage:
    python -m resolve_plugin.build_project <video_path>

Why this exists instead of having Lua drive the process (see lua_codegen.py
and README for the full story): Resolve's Lua scripting sandbox has no
working `io` library and no `os.execute` -- confirmed interactively in
Resolve's own Console -- so a script running inside Resolve cannot itself
launch Python or read/write files. This command does the reverse: it's a
plain Python process (unrestricted), so it runs the whole analysis,
prepares every media/subtitle asset on disk, and writes the finished Lua
script straight into Resolve's own Scripts folder. Go into Resolve
afterwards and run it from Workspace > Scripts > Edit.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from resolve_plugin.analysis.pipeline import analyze_video
from resolve_plugin.lua_codegen import generate_lua_script


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "progetto"


def _print_progress(step: int, total: int, message: str) -> None:
    print(f"[{step}/{total}] {message}", flush=True)


def _fusion_scripts_edit_dir() -> Path:
    appdata = Path(os.environ.get("APPDATA", str(Path.home())))
    return appdata / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Edit"


def _projects_root() -> Path:
    return Path.home() / "AutoTemplateProjects"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: python -m resolve_plugin.build_project <video_path>", file=sys.stderr)
        return 2

    video_path = Path(argv[0])
    if not video_path.exists():
        print(f"Errore: file video non trovato: {video_path}", file=sys.stderr)
        return 1

    stem = _sanitize_filename(video_path.stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_name = f"{stem}_{timestamp}"
    project_dir = _projects_root() / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    local_video_path = project_dir / f"source_video{video_path.suffix}"
    shutil.copy2(video_path, local_video_path)

    try:
        template = analyze_video(str(local_video_path), progress_callback=_print_progress)
    except Exception as exc:  # noqa: BLE001 - surface any failure with a clear message and exit code
        print(f"Errore durante l'analisi: {exc}", file=sys.stderr)
        return 1

    lua_source = generate_lua_script(template, timeline_name=stem, work_dir=project_dir)

    scripts_edit_dir = _fusion_scripts_edit_dir()
    scripts_edit_dir.mkdir(parents=True, exist_ok=True)
    script_basename = f"Auto Template - {project_name}"
    script_path = scripts_edit_dir / f"{script_basename}.lua"
    script_path.write_text(lua_source, encoding="utf-8")

    print()
    print(f'Fatto! In Resolve vai su Workspace > Scripts > Edit > "{script_basename}"')
    print("(riapri il menu Script se non lo vedi subito).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
