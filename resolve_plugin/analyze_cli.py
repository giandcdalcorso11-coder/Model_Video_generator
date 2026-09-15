"""Command-line entry point for the analysis pipeline.

Resolve 21.1 moved Scripts-menu Python execution to Studio-only, so the
Resolve-facing half of this plugin is now a Lua script (see lua/Auto
Template.lua) instead of a Python one. Lua can still shell out to an
external process, so this file is what it calls: it never touches the
Resolve API itself (this module has no dependency on resolve_plugin.resolve_api),
it just runs analysis.pipeline.analyze_video on a video file and writes the
resulting template.json where the Lua script expects it.

Usage:
    python -m resolve_plugin.analyze_cli <video_path> <project_dir>

<project_dir> is created if missing. The source video is copied into it (so
analysis has a stable local file to work from even if the original moves),
and template.json is written alongside it once analysis completes.
Progress is printed to stdout, one line per step, so it's visible if the
caller captures output; exits non-zero with an error message on failure.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from resolve_plugin.analysis.pipeline import analyze_video
from resolve_plugin.config import TEMPLATE_FILENAME


def _print_progress(step: int, total: int, message: str) -> None:
    print(f"[{step}/{total}] {message}", flush=True)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python -m resolve_plugin.analyze_cli <video_path> <project_dir>", file=sys.stderr)
        return 2

    video_path = Path(argv[0])
    project_dir = Path(argv[1])

    if not video_path.exists():
        print(f"Errore: file video non trovato: {video_path}", file=sys.stderr)
        return 1

    project_dir.mkdir(parents=True, exist_ok=True)
    local_video_path = project_dir / f"source_video{video_path.suffix}"
    if local_video_path.resolve() != video_path.resolve():
        shutil.copy2(video_path, local_video_path)

    try:
        template = analyze_video(str(local_video_path), progress_callback=_print_progress)
    except Exception as exc:  # noqa: BLE001 - surface any failure with a clear message and exit code
        print(f"Errore durante l'analisi: {exc}", file=sys.stderr)
        return 1

    template_path = project_dir / TEMPLATE_FILENAME
    template_path.write_text(json.dumps(template.to_dict(), indent=2), encoding="utf-8")
    print(f"Template scritto in: {template_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
