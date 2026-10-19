"""One review stored on disk, so the UI can come back to it.

A run folder holds the inputs (artwork, content sheet, rule files), the result,
and two renders of the page (as drawn, and print-only). Chat, feedback and
"compare a new proof" all start by opening an existing run.

    run = ReviewRun.create()
    pdf = await run.add_upload(file, "artwork")
    ...
    run.save(inputs, result)
    later = ReviewRun.open(run.run_id)
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel

from checker.models import Finding
from checker.pipeline import ReviewResult

RUNS_DIR = Path(__file__).resolve().parent / "runs"
MAX_UPLOAD_MB = 25
ALLOWED_SUFFIXES = {"artwork": {".pdf"}, "sheet": {".xlsx"}, "rules": {".json", ".md", ".txt"}}


class RunInputs(BaseModel):
    """File names inside the run folder."""

    artwork: str
    sheet: str | None
    rules: list[str]
    previous_run: str | None = None  # set when this run is a new proof compared with an earlier one


class ReviewRun:
    def __init__(self, run_id: str, folder: Path) -> None:
        self.run_id = run_id
        self.folder = folder

    # ---------------- creating and opening ----------------

    @classmethod
    def create(cls) -> "ReviewRun":
        run_id = uuid.uuid4().hex[:12]
        folder = RUNS_DIR / run_id
        folder.mkdir(parents=True)
        return cls(run_id, folder)

    @classmethod
    def open(cls, run_id: str) -> "ReviewRun":
        """An existing, finished run; 400 for a malformed id, 404 if it does not exist."""
        if not run_id.isalnum():  # also blocks path tricks such as '../'
            raise HTTPException(400, "invalid run id")
        run = cls(run_id, RUNS_DIR / run_id)
        if not run.result_path.exists():
            raise HTTPException(404, f"run {run_id} not found")
        return run

    def discard(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    @contextmanager
    def discarded_on_error(self) -> Iterator["ReviewRun"]:
        """Delete the run folder if anything inside the block fails, so no half-written runs stay on disk."""
        try:
            yield self
        except BaseException:
            self.discard()
            raise

    # ---------------- adding input files ----------------

    async def add_upload(self, upload: UploadFile, kind: str) -> Path:
        """Validate and store an uploaded file ('artwork', 'sheet' or 'rules')."""
        name = upload.filename or ""
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES[kind]:
            raise HTTPException(400, f"{name}: expected {', '.join(sorted(ALLOWED_SUFFIXES[kind]))} for {kind}")
        data = await upload.read()
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"{name} is larger than {MAX_UPLOAD_MB} MB")
        if not data:
            raise HTTPException(400, f"{name} is empty")
        path = self.folder / Path(name).name.replace(" ", "_")  # .name drops any directory part
        path.write_bytes(data)
        return path

    def add_copy(self, source: Path) -> Path:
        return Path(shutil.copy(source, self.folder))

    # ---------------- stored files ----------------

    @property
    def result_path(self) -> Path:
        return self.folder / "result.json"

    @property
    def image_path(self) -> Path:
        return self.folder / "artwork.png"

    @property
    def print_image_path(self) -> Path:
        return self.folder / "print.png"

    @property
    def feedback_log(self) -> Path:
        return self.folder / "feedback.jsonl"  # audit trail of reviewer decisions on this run

    def inputs(self) -> RunInputs:
        return RunInputs.model_validate_json((self.folder / "inputs.json").read_text(encoding="utf-8"))

    def artwork_path(self) -> Path:
        return self.folder / self.inputs().artwork

    def sheet_path(self) -> Path | None:
        sheet = self.inputs().sheet
        return self.folder / sheet if sheet else None

    def rule_paths(self) -> list[Path]:
        return [self.folder / r for r in self.inputs().rules]

    def result(self) -> ReviewResult:
        return ReviewResult.model_validate_json(self.result_path.read_text(encoding="utf-8"))

    def finding(self, finding_id: str) -> Finding:
        found = next((f for f in self.result().report.findings if f.id == finding_id), None)
        if found is None:
            raise HTTPException(404, f"finding {finding_id} not in run {self.run_id}")
        return found

    def save(self, inputs: RunInputs, result: ReviewResult) -> None:
        (self.folder / "inputs.json").write_text(inputs.model_dump_json(), encoding="utf-8")
        self.result_path.write_text(result.model_dump_json(), encoding="utf-8")

    def url(self, file_name: str) -> str:
        return file_url(self.run_id, file_name)


def file_url(run_id: str, file_name: str) -> str:
    """Where the API serves a run's file."""
    return f"/api/runs/{run_id}/{file_name}"
