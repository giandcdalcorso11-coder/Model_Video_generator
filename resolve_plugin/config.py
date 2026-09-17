"""Central configuration for the Auto Template plugin.

Everything here is meant to be edited by hand (or overridden via environment
variables) by the person installing the plugin -- there is no cloud service
and no account system, so all state lives under PROJECTS_ROOT on the local
disk.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Where "my projects" (source video, template.json, thumbnails, replacement
# footage references) are stored. Defaults to a folder under the user's
# home directory; override with AUTO_TEMPLATE_PROJECTS_ROOT if needed.
DEFAULT_PROJECTS_ROOT = Path(
    os.environ.get(
        "AUTO_TEMPLATE_PROJECTS_ROOT",
        str(Path.home() / "AutoTemplateProjects"),
    )
)

# Name of the JSON file that indexes all local projects (see storage/project_store.py).
PROJECTS_INDEX_FILENAME = "projects_index.json"

# Name of the extracted-template file saved inside each project folder.
TEMPLATE_FILENAME = "template.json"

# Supported AI vision backends for analysis/ai_classifier.py.
AI_BACKEND_OLLAMA = "ollama"
AI_BACKEND_GEMINI = "gemini"
AI_BACKEND_MOCK = "mock"


@dataclass
class OllamaConfig:
    """Local, free, offline vision backend (default)."""

    host: str = os.environ.get("AUTO_TEMPLATE_OLLAMA_HOST", "http://localhost:11434")
    # qwen2.5vl is a good default for text-heavy frames (multilingual OCR);
    # switch to "moondream" on low-VRAM machines.
    model: str = os.environ.get("AUTO_TEMPLATE_OLLAMA_MODEL", "qwen2.5vl")
    timeout_seconds: int = 120


@dataclass
class GeminiConfig:
    """Optional free-tier cloud backend. Subject to Google's free-tier quotas
    (rate limited, and quotas have been cut before) -- kept as an opt-in
    alternative, not the default.
    """

    api_key: str = os.environ.get("AUTO_TEMPLATE_GEMINI_API_KEY", "")
    model: str = os.environ.get("AUTO_TEMPLATE_GEMINI_MODEL", "gemini-2.5-flash")
    # Free tier is ~10 requests/minute; stay comfortably under that.
    max_requests_per_minute: int = 8
    timeout_seconds: int = 60


@dataclass
class AnalysisConfig:
    # Which backend classify_frame() calls should use by default.
    ai_backend: str = os.environ.get("AUTO_TEMPLATE_AI_BACKEND", AI_BACKEND_OLLAMA)
    # Seconds between sampled frames inside a single shot (in addition to
    # always sampling the first frame of every detected shot).
    in_shot_sample_interval_seconds: float = 2.0
    # Skip AI classification for shots shorter than this (still gets cut
    # detection + OCR, just not a full AI pass) to keep runtime/cost sane.
    min_shot_seconds_for_ai: float = 0.3
    scene_detect_threshold: float = 27.0  # PySceneDetect ContentDetector default-ish
    # PySceneDetect's own default min_scene_len is 15 FRAMES (~0.5s at 30fps)
    # -- any cut closer than that to the previous one gets silently merged
    # away, regardless of how strong the content change is. Confirmed on a
    # real fast-paced TikTok/Reels-style template (jump cuts every ~0.1-0.15s):
    # PySceneDetect returned only 2 shots for a video with ~64 real cuts,
    # because virtually every cut was closer together than 0.5s. This value
    # is in SECONDS (converted to frames using the video's real fps at
    # detection time) rather than frames, since it needs to stay meaningful
    # across videos with different frame rates.
    scene_detect_min_scene_len_seconds: float = 0.08

    # Voice/music separation (see analysis/speech.py). Uses Whisper for
    # speech detection + transcription -- CPU-only, no GPU needed, and
    # independent of the ai_backend used for the vision classifier above.
    enable_speech_analysis: bool = os.environ.get("AUTO_TEMPLATE_ENABLE_SPEECH", "1") != "0"
    # faster-whisper model size: tiny/base/small/medium/large-v3. "base" is a
    # good accuracy/speed balance on CPU; multilingual, auto-detects language.
    whisper_model_size: str = os.environ.get("AUTO_TEMPLATE_WHISPER_MODEL", "base")
    # Voice segments separated by a gap shorter than this are merged into one
    # continuous voice box instead of creating a sliver of "music" between them.
    min_gap_to_split_voice_seconds: float = 0.6
    # Heuristic-only "possible music change" flag: a sustained RMS loudness
    # jump bigger than this (in dB) inside a music segment gets a marker for
    # the user to review -- it is never auto-split, since reliable song-change
    # detection needs real audio fingerprinting, not a loudness heuristic.
    music_change_rms_jump_db: float = 10.0
    music_change_min_segment_seconds: float = 3.0


@dataclass
class PluginConfig:
    projects_root: Path = field(default_factory=lambda: DEFAULT_PROJECTS_ROOT)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)

    def ensure_projects_root(self) -> Path:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        return self.projects_root


def load_config() -> PluginConfig:
    """Loads defaults, then overlays a user config.json if present next to
    this file (lets users tweak settings without editing Python)."""
    cfg = PluginConfig()
    override_path = Path(__file__).parent / "user_config.json"
    if override_path.exists():
        data = json.loads(override_path.read_text(encoding="utf-8"))
        if "projects_root" in data:
            cfg.projects_root = Path(data["projects_root"])
        if "ai_backend" in data:
            cfg.analysis.ai_backend = data["ai_backend"]
        if "ollama" in data:
            for k, v in data["ollama"].items():
                setattr(cfg.ollama, k, v)
        if "gemini" in data:
            for k, v in data["gemini"].items():
                setattr(cfg.gemini, k, v)
    return cfg


CONFIG = load_config()
