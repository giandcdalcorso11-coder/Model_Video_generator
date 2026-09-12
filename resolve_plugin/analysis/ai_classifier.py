"""Pluggable AI vision backends for semantic frame analysis.

All backends implement the same interface -- classify_frame(image) -> a
FrameClassification -- so analysis/pipeline.py never needs to know which
provider is active. Selection happens once, via config.CONFIG.analysis.ai_backend:

  - "ollama" (default): local, free, offline, no API key. Requires Ollama
    installed on the user's machine with a vision model pulled (see README).
  - "gemini": optional, free-tier cloud fallback. Requires an API key and is
    throttled client-side to stay under Google's free-tier rate limit.
  - "mock": deterministic canned output, used in unit tests.

The prompt asks for on-screen text and a short label for any visible
effect/transition style -- the latter only ever becomes an EffectNote
(marker for the user to apply manually), never an auto-applied Resolve
effect, since that's the one thing the scripting API can't do for us.
"""
from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from PIL import Image

from resolve_plugin.config import (
    CONFIG,
    AI_BACKEND_GEMINI,
    AI_BACKEND_MOCK,
    AI_BACKEND_OLLAMA,
)

PROMPT = (
    "You are analyzing a single frame from a short-form video edit template. "
    "Reply with ONLY a compact JSON object, no prose, matching this shape: "
    '{"text": "<any on-screen text/captions visible, verbatim, or empty string">, '
    '"effect_style": "<a short label for any visible transition/filter/effect '
    'style at this moment, e.g. \'cross dissolve\', \'zoom blur\', \'vignette\', '
    'or empty string if none>", '
    '"notes": "<optional extra detail, or empty string>"}'
)


@dataclass
class FrameClassification:
    text: str = ""
    effect_style: str = ""
    notes: str = ""
    confidence: float = 0.0


class VisionBackend(Protocol):
    def classify_frame(self, frame: Image.Image) -> FrameClassification: ...


def _image_to_base64_jpeg(frame: Image.Image) -> str:
    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _parse_response_text(raw_text: str) -> FrameClassification:
    """Models sometimes wrap JSON in markdown fences or add stray text --
    extract the first {...} block before parsing, and never raise: a
    malformed response degrades to an empty classification rather than
    aborting the whole analysis."""
    try:
        start = raw_text.index("{")
        end = raw_text.rindex("}") + 1
        data = json.loads(raw_text[start:end])
        return FrameClassification(
            text=str(data.get("text", "")).strip(),
            effect_style=str(data.get("effect_style", "")).strip(),
            notes=str(data.get("notes", "")).strip(),
            confidence=0.7,
        )
    except (ValueError, json.JSONDecodeError):
        return FrameClassification(notes=raw_text.strip()[:200], confidence=0.2)


class OllamaBackend:
    """Local, free, offline. Talks to a running `ollama serve` instance."""

    def __init__(self, host: Optional[str] = None, model: Optional[str] = None, timeout: Optional[int] = None):
        self.host = host or CONFIG.ollama.host
        self.model = model or CONFIG.ollama.model
        self.timeout = timeout or CONFIG.ollama.timeout_seconds

    def classify_frame(self, frame: Image.Image) -> FrameClassification:
        import requests

        payload = {
            "model": self.model,
            "prompt": PROMPT,
            "images": [_image_to_base64_jpeg(frame)],
            "stream": False,
        }
        try:
            resp = requests.post(
                f"{self.host}/api/generate", json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.host}. Is `ollama serve` running "
                f"and has `ollama pull {self.model}` been run? Original error: {exc}"
            ) from exc

        raw_text = resp.json().get("response", "")
        return _parse_response_text(raw_text)


class GeminiBackend:
    """Optional free-tier cloud backend. Throttled client-side to stay under
    the free tier's requests-per-minute limit; still opt-in, not the default,
    since Google has cut free quotas before and it needs an API key."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or CONFIG.gemini.api_key
        self.model = model or CONFIG.gemini.model
        self.max_rpm = CONFIG.gemini.max_requests_per_minute
        self.timeout = CONFIG.gemini.timeout_seconds
        self._request_times: list[float] = []
        if not self.api_key:
            raise RuntimeError(
                "Gemini backend selected but no API key configured. Set "
                "AUTO_TEMPLATE_GEMINI_API_KEY or resolve_plugin/user_config.json."
            )

    def _throttle(self) -> None:
        now = time.monotonic()
        self._request_times = [t for t in self._request_times if now - t < 60]
        if len(self._request_times) >= self.max_rpm:
            sleep_for = 60 - (now - self._request_times[0]) + 0.1
            time.sleep(max(sleep_for, 0))
        self._request_times.append(time.monotonic())

    def classify_frame(self, frame: Image.Image) -> FrameClassification:
        import requests

        self._throttle()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": _image_to_base64_jpeg(frame),
                            }
                        },
                    ]
                }
            ]
        }
        resp = requests.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        raw_text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        return _parse_response_text(raw_text)


class MockBackend:
    """Deterministic backend for unit tests -- no network, no Ollama."""

    def __init__(self, canned: Optional[FrameClassification] = None):
        self.canned = canned or FrameClassification()

    def classify_frame(self, frame: Image.Image) -> FrameClassification:
        return self.canned


def get_backend(backend_name: Optional[str] = None) -> VisionBackend:
    name = backend_name or CONFIG.analysis.ai_backend
    if name == AI_BACKEND_OLLAMA:
        return OllamaBackend()
    if name == AI_BACKEND_GEMINI:
        return GeminiBackend()
    if name == AI_BACKEND_MOCK:
        return MockBackend()
    raise ValueError(f"Unknown AI backend: {name!r}")
