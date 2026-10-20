"""Regressions from the pre-submission debugging pass."""

import time
from pathlib import Path

import pymupdf
import pytest

from checker.artwork import ArtworkError, read_artwork
from checker.feedback import FeedbackStore
from checker.pipeline import ReviewPipeline

ROOT = Path(__file__).resolve().parents[2]
FDA = [ROOT / "rules" / "us_fda_food.json"]


def review(pdf: Path, tmp_path: Path):
    return ReviewPipeline(feedback=FeedbackStore(tmp_path / "fb.json")).run(pdf, None, FDA, use_ai=False)


def flat_label(path: Path, pages: int = 1) -> Path:
    """A simple label: live text, no dieline layers, optionally extra pages."""
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    y = 40
    for text, size in [("GRANOLA BITES", 22), ("NET WT 8 OZ (227g)", 12), ("INGREDIENTS: Oats, Honey, Almonds.", 9),
                       ("Nutrition Facts", 14), ("Calories 120", 10), ("Total Fat 5g", 8),
                       ("Distributed by Acme Foods, Austin, TX 78701", 7)]:
        page.insert_text((30, y), text, fontsize=size)
        y += size + 14
    for _ in range(pages - 1):
        doc.new_page()
    doc.save(path)
    return path


def test_label_without_dieline_is_its_own_front_panel(tmp_path):
    art = read_artwork(flat_label(tmp_path / "label.pdf"))
    assert list(art.panels) == ["front"]
    report = review(art_path := tmp_path / "label.pdf", tmp_path).report
    checks = {f.check: f.verdict.value for f in report.findings}
    assert checks.get("identity") == "pass"  # was a false alarm: "missing from the front panel"
    assert "net_quantity_pdp" not in checks  # the declaration is on the only panel there is
    assert art_path.exists()


def test_extra_pages_are_reported_not_skipped_silently(tmp_path):
    result = review(flat_label(tmp_path / "two.pdf", pages=2), tmp_path)
    assert "page 1 of 2" in (result.ai_note or "")


def test_artwork_on_a_later_page_is_named_not_called_unreadable(tmp_path):
    doc = pymupdf.open()
    doc.new_page()  # empty first page
    doc.insert_pdf(pymupdf.open(flat_label(tmp_path / "label.pdf")))
    doc.save(tmp_path / "cover_then_art.pdf")
    with pytest.raises(ArtworkError) as err:
        read_artwork(tmp_path / "cover_then_art.pdf")
    assert "page 2 does" in str(err.value) and "OCR" not in str(err.value)


def test_missing_serving_size_is_named_plainly(tmp_path):
    report = review(flat_label(tmp_path / "label.pdf"), tmp_path).report
    assert any(f.title == "No serving size declared" for f in report.findings)


def test_damaged_pdf_error_does_not_reveal_server_paths(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")
    with pytest.raises(ArtworkError) as err:
        read_artwork(bad)
    assert str(tmp_path) not in str(err.value) and "damaged or not a PDF" in str(err.value)


def test_cached_reads_are_independent_copies():
    pdf = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
    a, b = read_artwork(pdf), read_artwork(pdf)
    a.lines[0].text = "changed by a caller"
    assert b.lines[0].text != "changed by a caller"


def test_same_bytes_at_a_new_path_reuse_the_reading_but_report_the_new_path(tmp_path):
    first = tmp_path / "run1" / "carton.pdf"
    second = tmp_path / "run2" / "copy.pdf"
    for p in (first, second):
        p.parent.mkdir()
        p.write_bytes(flat_label(tmp_path / "src.pdf").read_bytes())
    a = read_artwork(first)
    started = time.perf_counter()
    b = read_artwork(second)
    assert time.perf_counter() - started < 0.2  # not parsed again
    assert (b.file_name, b.path) == ("copy.pdf", str(second))
    assert [ln.text for ln in a.lines] == [ln.text for ln in b.lines]


def test_rewritten_file_is_read_again(tmp_path):
    path = flat_label(tmp_path / "label.pdf")
    first = {l.text for l in read_artwork(path).lines}
    doc = pymupdf.open()
    doc.new_page().insert_text((30, 40), "SOMETHING NEW", fontsize=20)
    doc.save(path)  # same path, new content: the cache must not serve the old version
    assert "SOMETHING NEW" in {l.text for l in read_artwork(path).lines} - first
