"""Offline, always-available on-screen text detection via Tesseract.

This runs regardless of which AI backend is configured: it's free, needs no
network, and gives the AI classifier's text field a sanity-check fallback
(if pytesseract finds nothing and the AI backend also finds nothing, we
don't emit a TextOverlay for that frame).

Requires the Tesseract OCR binary to be installed separately (see README);
pytesseract is just a thin wrapper around it.
"""
from __future__ import annotations

from PIL import Image


def detect_text(frame: Image.Image) -> str:
    """Returns stripped OCR text for a frame, or "" if pytesseract/Tesseract
    isn't available or found nothing. Never raises -- OCR is a best-effort
    fallback, not a hard dependency of the pipeline."""
    try:
        import pytesseract
    except ImportError:
        return ""

    try:
        text = pytesseract.image_to_string(frame)
    except Exception:
        # Covers TesseractNotFoundError and any other backend failure --
        # missing the binary shouldn't crash the whole analysis pipeline.
        return ""

    return text.strip()
