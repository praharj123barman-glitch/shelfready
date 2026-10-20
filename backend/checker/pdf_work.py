"""Where PDF work runs: in this process, or in a separate worker process.

PyMuPDF holds Python's global lock (GIL) during long native calls (text
extraction about 1.4 s, barcode render about 1 s on the sample), so running it
in the API process makes the whole server pause. ``ProcessPdfWork`` does every
PyMuPDF step in a worker process instead; the API process only waits for the
result, and keeps answering other requests meanwhile.

Only PDF steps go to the worker: reading the artwork, the code checks (they
measure glyphs), rendering. AI calls stay in the API process as threads, so one
review waiting on the model never holds up another review's PDF work.

The worker keeps its caches between jobs (one open document per file
content), so repeat reviews of the same artwork are fast. With more than one
worker process each has its own cache.

``InlinePdfWork`` does the same steps in the calling process. Tests and the
eval use it; it is also the fallback when REVIEW_PROCESSES=0.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from pydantic import BaseModel

from .ai.prompt_material import panel_crops
from .artwork import PDF_LOCK, read_artwork, render_png, render_print_png
from .content_sheet import ApprovedSpec, read_content_sheet
from .engine import Report, run_checks
from .models import Artwork, BBox
from .rules import RuleSet

log = logging.getLogger(__name__)

PanelCrop = tuple[str, bytes]  # (caption, PNG bytes)


class CheckOutput(BaseModel):
    report: Report
    crops: list[tuple[str, bytes]]  # panel images for the AI ([] when AI is off)
    seconds: dict[str, float]


class PageRenders(BaseModel):
    image_width: int  # pixels, for the UI's PDF-point to pixel scale
    has_print_view: bool
    width: float  # PDF points
    height: float
    panels: dict[str, BBox]


class InlinePdfWork:
    """PDF work in the calling process (holding PDF_LOCK, since PyMuPDF is not thread-safe)."""

    def read(self, artwork_path: Path, sheet_path: Path | None) -> tuple[Artwork, ApprovedSpec | None]:
        with PDF_LOCK:
            art = read_artwork(artwork_path)
        return art, read_content_sheet(sheet_path) if sheet_path else None

    def check(self, art: Artwork, rules: RuleSet, spec: ApprovedSpec | None, with_panels: bool) -> CheckOutput:
        seconds: dict[str, float] = {}
        with PDF_LOCK:
            start = time.perf_counter()
            report = run_checks(art, rules, spec)
            seconds["code_checks"] = round(time.perf_counter() - start, 2)
            start = time.perf_counter()
            crops = panel_crops(art) if with_panels else []
            seconds["render_panels"] = round(time.perf_counter() - start, 2)
        return CheckOutput(report=report, crops=crops, seconds=seconds)

    def render(self, artwork_path: Path, image_path: Path, print_path: Path, dpi: int) -> PageRenders:
        with PDF_LOCK:
            image_width, _ = render_png(artwork_path, image_path, dpi=dpi)
            has_print_view = render_print_png(artwork_path, print_path, dpi=dpi)
            art = read_artwork(artwork_path)
        return PageRenders(image_width=image_width, has_print_view=has_print_view,
                           width=art.width, height=art.height, panels=art.panels)

    def warm_up(self) -> None:
        pass

    def close(self) -> None:
        pass


# The worker process runs these through one module-level InlinePdfWork, so its caches persist between jobs.
_IN_WORKER = InlinePdfWork()


def _read(*args):
    return _IN_WORKER.read(*args)


def _check(*args):
    return _IN_WORKER.check(*args)


def _render(*args):
    return _IN_WORKER.render(*args)


def _warm_up() -> bool:
    # loading this job made the worker import this module, and with it PyMuPDF, zxing and the checks
    return True


class ProcessPdfWork:
    """PDF work in worker processes. Each call blocks the calling thread (not the server) until done."""

    def __init__(self, processes: int = 1) -> None:
        self.processes = processes
        self._lock = threading.Lock()
        self._pool = ProcessPoolExecutor(max_workers=processes)

    def read(self, artwork_path: Path, sheet_path: Path | None) -> tuple[Artwork, ApprovedSpec | None]:
        return self._run(_read, artwork_path, sheet_path)

    def check(self, art: Artwork, rules: RuleSet, spec: ApprovedSpec | None, with_panels: bool) -> CheckOutput:
        return self._run(_check, art, rules, spec, with_panels)

    def render(self, artwork_path: Path, image_path: Path, print_path: Path, dpi: int) -> PageRenders:
        return self._run(_render, artwork_path, image_path, print_path, dpi)

    def warm_up(self) -> None:
        """Start the worker processes now, so the first review does not pay for it."""
        for future in [self._pool.submit(_warm_up) for _ in range(self.processes)]:
            future.result()

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, job, *args):
        try:
            return self._pool.submit(job, *args).result()
        except BrokenProcessPool:
            # a worker died (e.g. a native crash on a malformed PDF): report this request, start fresh for the next
            log.exception("PDF worker process died; starting a new one")
            with self._lock:
                self._pool = ProcessPoolExecutor(max_workers=self.processes)
            raise RuntimeError("The PDF worker stopped unexpectedly while reading this file. Please try again.") from None


PdfWork = InlinePdfWork | ProcessPdfWork
