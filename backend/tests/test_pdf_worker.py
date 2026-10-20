"""PDF work in a separate process gives the same review as in-process, and survives a dead worker."""

import os
from pathlib import Path

import pytest

from checker.feedback import FeedbackStore
from checker.pdf_work import InlinePdfWork, ProcessPdfWork
from checker.pipeline import ReviewPipeline

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
XLSX = ROOT / "samples" / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"
RULES = [ROOT / "rules" / "us_fda_food.json", ROOT / "rules" / "dancing_fish_company_rulebook.md"]


@pytest.fixture(scope="module")
def worker():
    pdf = ProcessPdfWork(processes=1)
    pdf.warm_up()
    yield pdf
    pdf.close()


def findings(pdf, tmp_path):
    result = ReviewPipeline(feedback=FeedbackStore(tmp_path / "fb.json"), pdf=pdf).run(PDF, XLSX, RULES, use_ai=False)
    return [(f.id, f.check, f.verdict, f.title) for f in result.report.findings]


def test_worker_process_gives_the_same_review(worker, tmp_path):
    assert findings(worker, tmp_path) == findings(InlinePdfWork(), tmp_path)


def test_renders_in_the_worker(worker, tmp_path):
    page = worker.render(PDF, tmp_path / "a.png", tmp_path / "p.png", 72)
    assert page.has_print_view and page.image_width > 0 and "front" in page.panels
    assert (tmp_path / "a.png").stat().st_size > 0


def test_a_dead_worker_fails_one_request_then_recovers(worker):
    with pytest.raises(RuntimeError, match="stopped unexpectedly"):
        worker._run(os._exit, 1)  # the worker process exits mid-job
    art, _ = worker.read(PDF, None)  # the next request gets a fresh worker
    assert art.file_name == PDF.name
