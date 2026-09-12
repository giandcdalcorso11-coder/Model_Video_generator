"""UIManager-based window: the "drop video + my projects" front end, and the
replace-footage screen, running as a panel launched from Resolve's own
Workspace > Scripts menu.

NOTE for whoever maintains this file: this is the one module in the plugin
that could not be tested against a real DaVinci Resolve instance while
writing it (this dev environment has no Windows/Resolve install). The
widget names and layout follow the standard Fusion UIManager patterns used
across the Resolve scripting community, but double-check them against your
Resolve version's Console if something doesn't render -- see README's
manual test checklist.

UIManager isn't Qt, so there's no drag-and-drop file API to rely on; file
selection goes through `fusion.RequestFile()` (a plain native file dialog),
which is the documented, version-stable way to do this instead of a real
drop-zone widget.
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any, Optional

from resolve_plugin.analysis.pipeline import analyze_video
from resolve_plugin.analysis.template_schema import Template
from resolve_plugin.resolve_api import connection, timeline_builder, takes_manager
from resolve_plugin.storage.project_store import (
    STATUS_ANALYZING,
    STATUS_FAILED,
    STATUS_READY,
    ProjectRecord,
    ProjectStore,
)


class AutoTemplateWindow:
    def __init__(self, bmd: Any):
        self.bmd = bmd
        self.fusion = bmd.scriptapp("Fusion")
        self.ui = self.fusion.UIManager
        self.dispatcher = bmd.UIDispatcher(self.ui)

        self.store = ProjectStore()
        self.clip_items: dict[int, Any] = {}
        self.current_template: Optional[Template] = None
        self.current_project: Optional[ProjectRecord] = None

        self.window = self._build_window()
        self.items = self.window.GetItems()
        self._wire_events()
        self.refresh_projects_list()

    # -- layout -----------------------------------------------------------
    def _build_window(self):
        ui = self.ui
        return self.dispatcher.AddWindow(
            {
                "ID": "AutoTemplateWin",
                "WindowTitle": "Auto Template",
                "Geometry": [100, 100, 640, 560],
            },
            [
                ui.VGroup(
                    {"ID": "root"},
                    [
                        ui.Label({"ID": "SectionProjects", "Text": "I miei progetti"}),
                        ui.Tree({"ID": "ProjectsTree", "Weight": 3}),
                        ui.HGroup(
                            {"Weight": 0},
                            [
                                ui.Button({"ID": "NewProjectBtn", "Text": "Carica video..."}),
                                ui.Button({"ID": "BuildTimelineBtn", "Text": "Costruisci timeline"}),
                                ui.Button({"ID": "RefreshBtn", "Text": "Aggiorna"}),
                            ],
                        ),
                        ui.Label({"ID": "StatusLabel", "Text": "Pronto."}),
                        ui.VGap(10),
                        ui.Label({"ID": "SectionReplace", "Text": "Sostituisci con i miei video"}),
                        ui.Tree({"ID": "ClipsTree", "Weight": 3}),
                        ui.HGroup(
                            {"Weight": 0},
                            [
                                ui.Button({"ID": "AssignFootageBtn", "Text": "Assegna video a questa clip"}),
                            ],
                        ),
                    ],
                )
            ],
        )

    def _wire_events(self):
        win = self.window
        win.On.AutoTemplateWin.Close = self._on_close
        win.On.NewProjectBtn.Clicked = self._on_new_project
        win.On.BuildTimelineBtn.Clicked = self._on_build_timeline
        win.On.RefreshBtn.Clicked = lambda ev: self.refresh_projects_list()
        win.On.ProjectsTree.ItemClicked = self._on_project_selected
        win.On.AssignFootageBtn.Clicked = self._on_assign_footage
        win.On.ClipsTree.ItemClicked = self._on_clip_selected

    # -- projects list ------------------------------------------------------
    def refresh_projects_list(self):
        tree = self.items["ProjectsTree"]
        tree.Clear()
        tree.SetHeaderLabels(["Progetto", "Stato"])
        for record in self.store.list_projects():
            node = tree.NewItem()
            node.Text[0] = record.name
            node.Text[1] = record.status
            node[0] = record.id  # stash id for lookup on click
            tree.AddTopLevelItem(node)
        self._set_status("Pronto.")

    def _selected_project_id(self) -> Optional[str]:
        tree = self.items["ProjectsTree"]
        selected = tree.CurrentItem
        if selected is None:
            return None
        return selected[0]

    def _on_project_selected(self, ev):
        project_id = self._selected_project_id()
        if not project_id:
            return
        self.current_project = self.store.get(project_id)
        self._load_template_if_ready()

    def _load_template_if_ready(self):
        if not self.current_project or self.current_project.status != STATUS_READY:
            return
        if not self.current_project.template_path.exists():
            return
        import json

        data = json.loads(self.current_project.template_path.read_text(encoding="utf-8"))
        self.current_template = Template.from_dict(data)
        self._set_status(
            f"Template caricato: {len(self.current_template.clips)} clip, "
            f"{len(self.current_template.gaps)} spazi vuoti."
        )

    # -- new project / analysis --------------------------------------------
    def _on_new_project(self, ev):
        video_path = self.fusion.RequestFile()
        if not video_path:
            return
        record = self.store.create_project(name=Path(video_path).stem, source_video_path=Path(video_path))
        self.refresh_projects_list()
        self._start_analysis(record)

    def _start_analysis(self, record: ProjectRecord):
        self.store.update_status(record.id, STATUS_ANALYZING)
        self._set_status(f"Analisi in corso per '{record.name}'...")

        def worker():
            try:
                def progress(step, total, message):
                    self._set_status(f"[{record.name}] {message} ({step}/{total})")

                template = analyze_video(str(record.source_video_path), progress_callback=progress)
                record.template_path.write_text(
                    __import__("json").dumps(template.to_dict(), indent=2), encoding="utf-8"
                )
                self.store.update_status(record.id, STATUS_READY)
                self._set_status(f"Analisi completata per '{record.name}'.")
            except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
                traceback.print_exc()
                self.store.update_status(record.id, STATUS_FAILED, error_message=str(exc))
                self._set_status(f"Analisi fallita per '{record.name}': {exc}")

        threading.Thread(target=worker, daemon=True).start()

    # -- build timeline -----------------------------------------------------
    def _on_build_timeline(self, ev):
        if not self.current_project or not self.current_template:
            self._set_status("Seleziona prima un progetto con analisi completata.")
            return
        try:
            handles = connection.connect(self.bmd)
            result = timeline_builder.build_timeline(
                handles, self.current_template, timeline_name=self.current_project.name
            )
            self.clip_items = result.clip_items
            self._refresh_clips_tree()
            self._set_status(f"Timeline '{self.current_project.name}' creata in Resolve.")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._set_status(f"Errore nella creazione della timeline: {exc}")

    # -- replace footage ------------------------------------------------------
    def _refresh_clips_tree(self):
        tree = self.items["ClipsTree"]
        tree.Clear()
        tree.SetHeaderLabels(["Clip #", "Durata (s)"])
        if not self.current_template:
            return
        for clip in self.current_template.clips:
            node = tree.NewItem()
            node.Text[0] = str(clip.index)
            node.Text[1] = f"{clip.duration_seconds:.2f}"
            node[0] = str(clip.index)
            tree.AddTopLevelItem(node)

    def _on_clip_selected(self, ev):
        pass  # selection is read directly from the tree when assigning footage

    def _on_assign_footage(self, ev):
        tree = self.items["ClipsTree"]
        selected = tree.CurrentItem
        if selected is None:
            self._set_status("Seleziona prima una clip nella lista.")
            return
        clip_index = int(selected[0])

        video_path = self.fusion.RequestFile()
        if not video_path:
            return
        try:
            handles = connection.connect(self.bmd)
            takes_manager.replace_clip_footage(
                handles.media_pool, self.clip_items, clip_index, video_path
            )
            self._set_status(f"Clip {clip_index} sostituita con {Path(video_path).name}.")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._set_status(f"Errore nella sostituzione della clip {clip_index}: {exc}")

    # -- misc -----------------------------------------------------------------
    def _set_status(self, message: str):
        self.items["StatusLabel"].Text = message

    def _on_close(self, ev):
        self.dispatcher.ExitLoop()

    def run(self):
        self.window.Show()
        self.dispatcher.RunLoop()
        self.window.Hide()
