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

import hashlib
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel

from api_models import RunView
from checker.models import Finding
from checker.pipeline import ReviewResult

RUNS_DIR = Path(__file__).resolve().parent / "runs"
MAX_UPLOAD_MB = 25
RESERVED_NAMES = {"result.json", "inputs.json", "view.json", "artwork.png", "print.png", "feedback.jsonl"}  # the run's own files
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
        path = self._free_name(Path(name).name.replace(" ", "_"))  # .name drops any directory part
        path.write_bytes(data)
        return path

    def _free_name(self, name: str) -> Path:
        """A path in the run folder that is not taken: two uploads with the same name (or one named like
        the run's own files, e.g. inputs.json) must not overwrite each other."""
        stem, suffix = Path(name).stem, Path(name).suffix
        path, n = self.folder / name, 2
        while path.exists() or path.name.lower() in RESERVED_NAMES:
            path, n = self.folder / f"{stem}_{n}{suffix}", n + 1
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

    def view(self) -> RunView | None:
        """Page info and comparison saved with the run (None for runs saved before view.json existed)."""
        path = self.folder / "view.json"
        return RunView.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def save(self, inputs: RunInputs, result: ReviewResult, view: RunView | None = None) -> None:
        (self.folder / "inputs.json").write_text(inputs.model_dump_json(), encoding="utf-8")
        if view is not None:
            (self.folder / "view.json").write_text(view.model_dump_json(), encoding="utf-8")
        self.result_path.write_text(result.model_dump_json(), encoding="utf-8")  # last: its presence marks a finished run
        share_identical_files(self.folder)

    def url(self, file_name: str) -> str:
        return file_url(self.run_id, file_name)


def file_url(run_id: str, file_name: str) -> str:
    """Where the API serves a run's file."""
    return f"/api/runs/{run_id}/{file_name}"


# ---------------- disk use ----------------
#
# Reviewing the same artwork again stores the same inputs and the same 4 MB page renders
# again. Identical files are kept once in runs/_blobs and hard-linked into each run folder:
# every folder still holds all its files, but the bytes are on disk once. Run folders are
# never written after saving, so sharing is safe; the appendable feedback log is skipped.

# feedback.jsonl is appended to; result.json and inputs.json stay plain files because a hard link
# carries the first copy's modification time, and runs are ordered by when they were saved
NOT_SHARED = {"feedback.jsonl", "result.json", "inputs.json", "view.json"}
SHARE_MIN_BYTES = 64 * 1024  # small files are not worth a link


def blobs_dir() -> Path:
    return RUNS_DIR / "_blobs"


def share_identical_files(folder: Path) -> int:
    """Replace files in `folder` with hard links to one shared copy. Returns bytes saved."""
    store = blobs_dir()
    store.mkdir(parents=True, exist_ok=True)
    saved = 0
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name in NOT_SHARED or path.stat().st_size < SHARE_MIN_BYTES:
            continue
        blob = store / (hashlib.sha256(path.read_bytes()).hexdigest() + path.suffix.lower())
        try:
            if not blob.exists():
                os.link(path, blob)  # first copy: the blob is this file
                continue
            if os.path.samefile(path, blob):
                continue
            tmp = path.with_name(path.name + ".linking")
            os.link(blob, tmp)
            tmp.replace(path)  # atomic: the run file is never missing
            saved += blob.stat().st_size
        except OSError:  # e.g. a filesystem without hard links: keep the plain copy
            continue
    return saved
