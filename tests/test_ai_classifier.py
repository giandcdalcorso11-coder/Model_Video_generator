from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from resolve_plugin.analysis.ai_classifier import (
    FrameClassification,
    GeminiBackend,
    MockBackend,
    OllamaBackend,
    _parse_response_text,
    get_backend,
)
from resolve_plugin.config import AI_BACKEND_GEMINI, AI_BACKEND_MOCK, AI_BACKEND_OLLAMA


def make_frame():
    return Image.new("RGB", (4, 4), color="black")


def test_parse_clean_json():
    result = _parse_response_text('{"text": "hello", "effect_style": "zoom", "notes": "n"}')
    assert result.text == "hello"
    assert result.effect_style == "zoom"
    assert result.notes == "n"
    assert result.confidence > 0


def test_parse_json_wrapped_in_markdown_fence():
    raw = 'Sure, here is the JSON:\n```json\n{"text": "caption", "effect_style": "", "notes": ""}\n```'
    result = _parse_response_text(raw)
    assert result.text == "caption"
    assert result.effect_style == ""


def test_parse_malformed_response_degrades_gracefully():
    result = _parse_response_text("not json at all")
    assert result.text == ""
    assert result.notes == "not json at all"
    assert result.confidence < 0.5


def test_mock_backend_returns_canned_result():
    canned = FrameClassification(text="canned text")
    backend = MockBackend(canned=canned)
    assert backend.classify_frame(make_frame()) is canned


def test_gemini_backend_requires_api_key():
    with pytest.raises(RuntimeError):
        GeminiBackend(api_key="")


def test_ollama_backend_posts_expected_payload_and_parses_response():
    backend = OllamaBackend(host="http://localhost:11434", model="qwen2.5vl", timeout=5)

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"response": '{"text": "hi", "effect_style": "", "notes": ""}'}

    with patch("requests.post", return_value=fake_response) as mock_post:
        result = backend.classify_frame(make_frame())

    assert result.text == "hi"
    args, kwargs = mock_post.call_args
    assert args[0] == "http://localhost:11434/api/generate"
    assert kwargs["json"]["model"] == "qwen2.5vl"
    assert len(kwargs["json"]["images"]) == 1


def test_ollama_backend_raises_readable_error_when_unreachable():
    backend = OllamaBackend(host="http://localhost:11434", model="qwen2.5vl", timeout=5)
    with patch("requests.post", side_effect=ConnectionError("refused")):
        with pytest.raises(RuntimeError, match="ollama pull"):
            backend.classify_frame(make_frame())


def test_gemini_backend_throttles_requests(monkeypatch):
    backend = GeminiBackend(api_key="fake-key")
    backend.max_rpm = 1
    backend._request_times = [__import__("time").monotonic()]

    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"text": "", "effect_style": "", "notes": ""}'}]}}]
    }
    with patch("requests.post", return_value=fake_response):
        backend.classify_frame(make_frame())

    assert len(sleep_calls) == 1


def test_get_backend_selects_by_name():
    assert isinstance(get_backend(AI_BACKEND_MOCK), MockBackend)
    assert isinstance(get_backend(AI_BACKEND_OLLAMA), OllamaBackend)
    with pytest.raises(RuntimeError):
        get_backend(AI_BACKEND_GEMINI)  # no api key configured by default


def test_get_backend_unknown_name_raises():
    with pytest.raises(ValueError):
        get_backend("not-a-real-backend")
