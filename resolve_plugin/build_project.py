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
from pathlib import Path

from resolve_plugin.analysis.pipeline import analyze_video
from resolve_plugin.analysis.scene_detect import probe_duration_and_fps
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


def _next_project_name(stem: str, scripts_edit_dir: Path, projects_root: Path) -> str:
    """Picks "<stem>" for the first analysis of a given video, or
    "<stem>_2", "<stem>_3", ... for later ones -- so the script/project name
    stays readable (the video's own name) instead of a timestamp, while
    still never colliding with a previous run's script or project folder."""
    candidate = stem
    version = 1
    while (scripts_edit_dir / f"Auto Template - {candidate}.lua").exists() or (
        projects_root / candidate
    ).exists():
        version += 1
        candidate = f"{stem}_{version}"
    return candidate


def _print_result_summary(template, video_path: str) -> None:
    """Prints a plain-language summary of what the analysis produced --
    counts and time ranges for every part of the template -- so it's clear
    from the terminal alone what to expect on the generated timeline,
    without needing to open Resolve first to find out."""
    source_duration, _ = probe_duration_and_fps(video_path)
    reconstructed_duration = sum(c.duration_seconds for c in template.clips) + sum(
        g.end_seconds - g.start_seconds for g in template.gaps
    )

    def _range(items, label: str) -> None:
        if not items:
            print(f"  {label}: nessuno")
            return
        starts = [i.start_seconds for i in items]
        ends = [i.end_seconds for i in items]
        print(f"  {label}: {len(items)} elemento/i, da {min(starts):.2f}s a {max(ends):.2f}s")

    print()
    print("--- Riepilogo risultati analisi ---")
    print(f"  Durata video sorgente (ffprobe): {source_duration:.2f}s")
    print(f"  Durata timeline ricostruita (clip + gap in sequenza): {reconstructed_duration:.2f}s")
    print(f"  Traccia video: {len(template.clips)} clip, {len(template.gaps)} spazi vuoti/gap")
    _range(template.texts, "Testo a schermo")
    _range(template.dialogue, "Dialogo (trascrizione)")
    _range(template.voice_segments, "Voce")
    _range(template.music_segments, "Musica")
    print(f"  Effetti/transizioni segnalati (marker gialli): {len(template.effect_notes)}")
    print("------------------------------------")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: python -m resolve_plugin.build_project <video_path>", file=sys.stderr)
        return 2

    video_path = Path(argv[0])
    if not video_path.exists():
        print(f"Errore: file video non trovato: {video_path}", file=sys.stderr)
        return 1

    stem = _sanitize_filename(video_path.stem)
    scripts_edit_dir = _fusion_scripts_edit_dir()
    project_name = _next_project_name(stem, scripts_edit_dir, _projects_root())
    project_dir = _projects_root() / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    local_video_path = project_dir / f"source_video{video_path.suffix}"
    shutil.copy2(video_path, local_video_path)

    try:
        template = analyze_video(str(local_video_path), progress_callback=_print_progress)
    except Exception as exc:  # noqa: BLE001 - surface any failure with a clear message and exit code
        print(f"Errore durante l'analisi: {exc}", file=sys.stderr)
        return 1

    try:
        _print_result_summary(template, str(local_video_path))
    except Exception as exc:  # noqa: BLE001 - the summary must never abort a real build
        print(f"  (riepilogo non disponibile: {exc})")

    lua_source = generate_lua_script(template, timeline_name=stem, work_dir=project_dir)

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
