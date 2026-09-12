import sys
import types

from PIL import Image

from resolve_plugin.analysis.ocr import detect_text


def make_frame():
    return Image.new("RGB", (4, 4), color="white")


def test_detect_text_returns_empty_string_when_pytesseract_missing(monkeypatch):
    # Simulate the "not installed" case regardless of what's actually
    # available in the environment running the tests.
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    assert detect_text(make_frame()) == ""


def test_detect_text_strips_and_returns_ocr_output(monkeypatch):
    fake_pytesseract = types.ModuleType("pytesseract")
    fake_pytesseract.image_to_string = lambda frame: "  Hello World  \n"
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    assert detect_text(make_frame()) == "Hello World"


def test_detect_text_swallows_backend_errors(monkeypatch):
    fake_pytesseract = types.ModuleType("pytesseract")

    def raise_error(frame):
        raise RuntimeError("tesseract binary not found")

    fake_pytesseract.image_to_string = raise_error
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    assert detect_text(make_frame()) == ""
