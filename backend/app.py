"""HTTP API for the artwork checker.

Each review is stored as a run folder (inputs + result JSON + rendered page),
so the UI can draw evidence boxes and ask follow-up questions later.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from checker.ai.chat import ChatAnswer, ChatTurn, answer_question
from checker.ai.client import AIError, ai_available, model_name
from checker.artwork import ArtworkError, read_artwork, render_png, render_print_png
from checker.checks.base import CheckContext
from checker.compare import Comparison, compare
from checker.models import BBox
from checker.content_sheet import SheetError, read_content_sheet
from checker.feedback import FeedbackStore, carry_waivers, record, remove_waiver
from checker.feedback import load as load_feedback
from checker.pipeline import ReviewResult, review
from checker.rules import RuleError, RuleSet

logging.basicConfig(level=logging.INFO)
ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(__file__).resolve().parent / "runs"
SAMPLES = ROOT / "samples"
RULES = ROOT / "rules"
MAX_UPLOAD_MB = 25
SAMPLE_V2 = "DancingFish_Granola_Berry_US_Carton_v2_GENERATED.pdf"  # demo second proof, see eval/make_v2_proof.py
RENDER_DPI = 200  # crops in the UI magnify 6pt text, so the page image needs real resolution
ALLOWED = {"artwork": {".pdf"}, "sheet": {".xlsx"}, "rules": {".json", ".md", ".txt"}}

app = FastAPI(title="Esko AIForge artwork checker")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


class Health(BaseModel):
    ok: bool
    ai_available: bool
    model: str


class SampleSet(BaseModel):
    artwork: str
    content_sheet: str
    rule_files: list[str]


class RunResponse(BaseModel):
    run_id: str
    image_url: str
    page_width: float
    page_height: float
    image_scale: float = Field(description="image pixels per PDF point, for drawing evidence boxes")
    result: ReviewResult
    comparison: Comparison | None = None  # set when this run is a new proof compared with an earlier run
    previous_image_url: str | None = None
    panels: dict[str, BBox] = Field(default_factory=dict, description="faces and flaps in PDF points, for the 3D carton")
    print_image_url: str | None = Field(default=None, description="render with dieline layers off: what actually prints")


class ChatRequest(BaseModel):
    finding_id: str
    question: str = Field(min_length=2, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list)


class Feedback(BaseModel):
    finding_id: str
    decision: Literal["accepted", "false_alarm"]
    reason: str = Field(default="", max_length=1000)


Market = Literal["US", "India"]
# rule files per market: the regulation pack plus the layers that fit that market
MARKET_RULES: dict[str, list[str]] = {
    "US": ["us_fda_food.json", "dancing_fish_company_rulebook.md", "retailer_guidelines_demo.txt"],
    "India": ["india_fssai_food.json", "artwork_approval_core.json"],
}
DEFAULT_RULES: dict[str, list[str]] = {"US": ["us_fda_food.json"], "India": ["india_fssai_food.json", "artwork_approval_core.json"]}


def _sample_files(market: str = "US") -> SampleSet:
    return SampleSet(
        artwork="DancingFish_Granola_Berry_US_Carton.pdf",
        content_sheet="DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx",
        rule_files=MARKET_RULES[market],
    )


async def _save(upload: UploadFile, kind: str, folder: Path) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED[kind]:
        raise HTTPException(400, f"{upload.filename}: expected {', '.join(sorted(ALLOWED[kind]))} for {kind}")
    data = await upload.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"{upload.filename} is larger than {MAX_UPLOAD_MB} MB")
    if not data:
        raise HTTPException(400, f"{upload.filename} is empty")
    safe = Path(upload.filename).name.replace(" ", "_")
    path = folder / safe
    path.write_bytes(data)
    return path


def _run_dir(run_id: str) -> Path:
    if not run_id.isalnum():
        raise HTTPException(400, "invalid run id")
    folder = RUNS / run_id
    if not (folder / "result.json").exists():
        raise HTTPException(404, f"run {run_id} not found")
    return folder


@app.get("/api/health", response_model=Health)
def health() -> Health:
    return Health(ok=True, ai_available=ai_available(), model=model_name())


@app.get("/api/samples", response_model=SampleSet)
def samples(market: Market = "US") -> SampleSet:
    return _sample_files(market)


@app.post("/api/review", response_model=RunResponse)
async def create_review(
    use_samples: bool = Form(False),
    use_ai: bool = Form(True),
    market: Market = Form("US"),
    artwork: UploadFile | None = File(None),
    content_sheet: UploadFile | None = File(None),
    rule_files: list[UploadFile] | None = File(None),
) -> RunResponse:
    run_id = uuid.uuid4().hex[:12]
    folder = RUNS / run_id
    folder.mkdir(parents=True)
    try:
        if use_samples:
            s = _sample_files(market)
            art_path = Path(shutil.copy(SAMPLES / s.artwork, folder))
            sheet_path = Path(shutil.copy(SAMPLES / s.content_sheet, folder))
            rule_paths = [Path(shutil.copy(RULES / r, folder)) for r in s.rule_files]
        else:
            if artwork is None:
                raise HTTPException(400, "Upload an artwork PDF, or choose the sample files")
            art_path = await _save(artwork, "artwork", folder)
            sheet_path = await _save(content_sheet, "sheet", folder) if content_sheet else None
            rule_paths = [await _save(f, "rules", folder) for f in rule_files or []]
            if not rule_paths:  # the market's built-in packs when the user supplies no rules
                rule_paths = [Path(shutil.copy(RULES / r, folder)) for r in DEFAULT_RULES[market]]
        result = review(art_path, sheet_path, rule_paths, use_ai=use_ai)
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except (ArtworkError, SheetError, RuleError) as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, str(exc)) from exc

    return _save_run(run_id, folder, art_path, sheet_path, rule_paths, result)


def _save_run(run_id, folder, art_path, sheet_path, rule_paths, result, comparison=None, previous=None) -> RunResponse:
    """Persist a finished review (inputs, result, rendered page) and build the response."""
    width, _ = render_png(art_path, folder / "artwork.png", dpi=RENDER_DPI)
    has_print = render_print_png(art_path, folder / "print.png", dpi=RENDER_DPI)
    art = read_artwork(art_path)
    (folder / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
    (folder / "inputs.json").write_text(json.dumps({
        "artwork": art_path.name, "sheet": sheet_path.name if sheet_path else None,
        "rules": [p.name for p in rule_paths], "previous_run": previous,
    }), encoding="utf-8")
    return RunResponse(
        run_id=run_id, image_url=f"/api/runs/{run_id}/artwork.png", page_width=art.width, page_height=art.height,
        image_scale=width / art.width, result=result, comparison=comparison, panels=art.panels,
        print_image_url=f"/api/runs/{run_id}/print.png" if has_print else None,
        previous_image_url=f"/api/runs/{previous}/artwork.png" if previous else None,
    )


@app.post("/api/runs/{run_id}/compare", response_model=RunResponse)
async def compare_proof(
    run_id: str,
    use_ai: bool = Form(True),
    use_sample_v2: bool = Form(False),
    artwork: UploadFile | None = File(None),
) -> RunResponse:
    """Review a new proof with the previous run's content sheet and rules, and
    report what changed and which issues it resolved or introduced."""
    prev = _run_dir(run_id)
    inputs = json.loads((prev / "inputs.json").read_text(encoding="utf-8"))
    new_id = uuid.uuid4().hex[:12]
    folder = RUNS / new_id
    folder.mkdir(parents=True)
    try:
        if use_sample_v2:
            art_path = Path(shutil.copy(SAMPLES / SAMPLE_V2, folder))
        elif artwork is not None:
            art_path = await _save(artwork, "artwork", folder)
        else:
            raise HTTPException(400, "Upload the new proof (PDF), or choose the generated sample v2")
        sheet_path = Path(shutil.copy(prev / inputs["sheet"], folder)) if inputs["sheet"] else None
        rule_paths = [Path(shutil.copy(prev / r, folder)) for r in inputs["rules"]]
        carry_waivers(prev / inputs["artwork"], art_path)  # dismissed false alarms stay dismissed on the new proof
        result = review(art_path, sheet_path, rule_paths, use_ai=use_ai)
        before = ReviewResult.model_validate_json((prev / "result.json").read_text(encoding="utf-8"))
        comparison = compare(read_artwork(prev / inputs["artwork"]), read_artwork(art_path),
                             before.report.findings, result.report.findings)
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except (ArtworkError, SheetError, RuleError) as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, str(exc)) from exc
    return _save_run(new_id, folder, art_path, sheet_path, rule_paths, result, comparison=comparison, previous=run_id)


@app.get("/api/runs/{run_id}/artwork.png")
def run_image(run_id: str):
    return FileResponse(_run_dir(run_id) / "artwork.png", media_type="image/png")


@app.get("/api/runs/{run_id}/print.png")
def run_print_image(run_id: str):
    path = _run_dir(run_id) / "print.png"
    if not path.exists():
        raise HTTPException(404, "this artwork has no dieline layers, so there is no separate print view")
    return FileResponse(path, media_type="image/png")


@app.post("/api/runs/{run_id}/chat", response_model=ChatAnswer)
def chat(run_id: str, req: ChatRequest) -> ChatAnswer:
    folder = _run_dir(run_id)
    result = ReviewResult.model_validate_json((folder / "result.json").read_text(encoding="utf-8"))
    finding = next((f for f in result.report.findings if f.id == req.finding_id), None)
    if finding is None:
        raise HTTPException(404, f"finding {req.finding_id} not in run {run_id}")
    inputs = json.loads((folder / "inputs.json").read_text(encoding="utf-8"))
    art = read_artwork(folder / inputs["artwork"])
    spec = read_content_sheet(folder / inputs["sheet"]) if inputs["sheet"] else None
    ctx = CheckContext.build(art, RuleSet(rules=[]), spec)
    try:
        return answer_question(ctx, finding, req.question, req.history)
    except AIError as exc:
        raise HTTPException(503, f"The assistant is unavailable: {exc}") from exc


@app.post("/api/runs/{run_id}/feedback")
def feedback(run_id: str, fb: Feedback) -> dict:
    """Accept, or mark a false alarm. A false alarm waives that problem on this
    artwork for later reviews; on an AI finding with a reason it also becomes
    guidance the AI reads next time. The response says exactly what changed."""
    folder = _run_dir(run_id)
    result = ReviewResult.model_validate_json((folder / "result.json").read_text(encoding="utf-8"))
    finding = next((f for f in result.report.findings if f.id == fb.finding_id), None)
    if finding is None:
        raise HTTPException(404, f"finding {fb.finding_id} not in run {run_id}")
    if fb.decision == "false_alarm" and finding.verdict.value == "pass":
        raise HTTPException(400, "A passed check cannot be a false alarm")
    inputs = json.loads((folder / "inputs.json").read_text(encoding="utf-8"))
    with (folder / "feedback.jsonl").open("a", encoding="utf-8") as fh:  # audit trail per run
        fh.write(fb.model_dump_json() + "\n")
    return record(finding, fb.decision, fb.reason, folder / inputs["artwork"])


@app.get("/api/feedback", response_model=FeedbackStore)
def list_feedback() -> FeedbackStore:
    return load_feedback()


@app.delete("/api/waivers/{waiver_id}")
def delete_waiver(waiver_id: str) -> dict:
    if not waiver_id.isalnum():
        raise HTTPException(400, "invalid waiver id")
    if not remove_waiver(waiver_id):
        raise HTTPException(404, f"waiver {waiver_id} not found")
    return {"removed": True}
