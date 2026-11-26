"""Guards for E0.5a: the OCR call matches the installed ocrmypdf API, and the scraper tests
are marked `live` / skipped as agreed (no network is used by these tests)."""

import inspect
import subprocess
import sys
from pathlib import Path

import ocrmypdf

from app.prozorro_functionality import prozorro

BACKEND = Path(__file__).resolve().parents[1]
SCRAPER_TESTS = BACKEND.parent / "scraper" / "tests"


def test_ocr_pdf_call_matches_the_installed_ocrmypdf_signature(monkeypatch):
    """ocrmypdf 17 renamed the first parameter to `input_file_or_options`; calling it with
    `input_file=` raised TypeError and silently disabled OCR. Bind the real call to the real
    signature without running tesseract."""
    signature = inspect.signature(ocrmypdf.ocr)
    bound = {}

    def fake_ocr(*args, **kwargs):
        bound["arguments"] = signature.bind(*args, **kwargs).arguments  # raises TypeError on mismatch

    monkeypatch.setattr(ocrmypdf, "ocr", fake_ocr)
    prozorro.ocr_pdf("in.pdf", "out.pdf")

    assert bound["arguments"]["input_file_or_options"] == "in.pdf"
    assert bound["arguments"]["output_file"] == "out.pdf"
    assert bound["arguments"]["language"] == "ukr+eng"


def run_pytest(*args) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(SCRAPER_TESTS), "-p", "no:cacheprovider", *args],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout + result.stderr


def test_not_live_deselects_every_scraper_test():
    assert "14 deselected" in run_pytest("-m", "not live", "-q")


def test_the_nine_stale_info_product_tests_are_skipped_with_a_reason():
    output = run_pytest("-k", "test_info_product", "-q", "-rs")
    assert "9 skipped" in output
    assert "E2.2" in output
