"""E0.7: OCR of a scanned page with Ukrainian text (needs tesseract with `ukr`; skipped where it is missing)."""

import glob
import shutil
import subprocess

import pytest

from app.prozorro_functionality.prozorro import ocr_pdf


def _has_ukrainian_tesseract() -> bool:
    if not shutil.which("tesseract"):
        return False
    languages = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout
    return "ukr" in languages.split()


def _cyrillic_font():
    candidates = glob.glob("/usr/share/fonts/**/DejaVuSans.ttf", recursive=True) + glob.glob("C:/Windows/Fonts/arial.ttf")
    return candidates[0] if candidates else None


@pytest.mark.skipif(not _has_ukrainian_tesseract(), reason="tesseract with the ukr language is not installed")
def test_a_scanned_page_with_ukrainian_text_is_recognised(tmp_path):
    fitz = pytest.importorskip("fitz")
    from PIL import Image, ImageDraw, ImageFont

    font_path = _cyrillic_font()
    if not font_path:
        pytest.skip("no font with Cyrillic letters")
    image = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, 56)
    draw.text((30, 30), "Посвідчення про перевірку знань", fill="black", font=font)
    draw.text((30, 140), "Бланк накопичувальна картка 8000", fill="black", font=font)
    scan = tmp_path / "scan.pdf"
    image.save(scan, resolution=200)

    out = tmp_path / "ocr.pdf"
    ocr_pdf(str(scan), str(out))
    text = fitz.open(out)[0].get_text().lower()
    assert "перевірку знань" in text
    assert "накопичувальна картка" in text
