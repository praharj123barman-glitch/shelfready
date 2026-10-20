"""HTTP API for the artwork checker.

Each endpoint is thin: it opens or creates a ReviewRun (runs.py), hands the
files to ReviewPipeline (checker/pipeline.py), and returns the shapes in
api_models.py. All checking logic lives in the checker package.

Errors: bad input is 400/413, unreadable files 422, unknown runs 404, and the
AI being unavailable 503. Nothing reports success when it did not run.
"""

from __future__ import annotations

import importlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api_models import ChatRequest, FeedbackRequest, Health, Market, RunResponse, RunView, SampleSet
from checker.ai.chat import ChatAnswer, FindingChat
from checker.ai.client import AIError, default_client
from checker.artwork import ArtworkError
from checker.checks.base import CheckContext
from checker.compare import Comparison, compare
from checker.content_sheet import SheetError
from checker.feedback import FeedbackData, FeedbackStore
from checker.pdf_work import InlinePdfWork, PageRenders, ProcessPdfWork
from checker.pipeline import ReviewPipeline, ReviewResult
from checker.rules import RuleError, RuleSet
from monitoring import RequestMonitor, RequestRecord, RequestTimingMiddleware
from runs import ReviewRun, RunInputs, file_url

logging.basicConfig(level=logging.INFO)
importlib.import_module("google.genai.types")  # loaded at startup (0.5 to 1 s) instead of during the first review
ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
RULES = ROOT / "rules"
SAMPLE_V2 = "DancingFish_Granola_Berry_US_Carton_v2_GENERATED.pdf"  # demo second proof, see eval/make_v2_proof.py
RENDER_DPI = 200  # crops in the UI magnify 6pt text, so the page image needs real resolution

# rule files per market: the regulation pack plus the layers that fit that market
MARKET_RULES: dict[str, list[str]] = {
    "US": ["us_fda_food.json", "dancing_fish_company_rulebook.md", "retailer_guidelines_demo.txt"],
    "India": ["india_fssai_food.json", "artwork_approval_core.json"],
}
# used when the user uploads an artwork but no rule files
DEFAULT_RULES: dict[str, list[str]] = {"US": ["us_fda_food.json"], "India": ["india_fssai_food.json", "artwork_approval_core.json"]}
UNREADABLE_INPUT = (ArtworkError, SheetError, RuleError)

LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}

# Every PyMuPDF step runs in this many worker processes (see checker/pdf_work.py), so the
# server never pauses on PDF work. 0 runs it in this process instead (used by the tests).
REVIEW_PROCESSES = int(os.environ.get("REVIEW_PROCESSES", "1"))
# Web app addresses allowed to call this API (comma-separated). Set it to the hosted frontend's URL when deploying.
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

monitor = RequestMonitor()
feedback_store = FeedbackStore()
pdf_work = ProcessPdfWork(REVIEW_PROCESSES) if REVIEW_PROCESSES > 0 else InlinePdfWork()
pipeline = ReviewPipeline(feedback=feedback_store, pdf=pdf_work)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await run_in_threadpool(pdf_work.warm_up)  # start the PDF worker now, not during the first review
    yield
    pdf_work.close()


app = FastAPI(title="Esko AIForge artwork checker", lifespan=lifespan)
app.add_middleware(RequestTimingMiddleware, monitor=monitor)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Request-ID", "Server-Timing"])

# Reviews are slow (PDF work, AI calls), so endpoints run them in worker threads and the
# server keeps answering other requests meanwhile; PDF work itself goes to pdf_work.


# ---------------- info ----------------

@app.get("/api/health", response_model=Health)
def health() -> Health:
    client = default_client()
    return Health(ok=True, ai_available=client.available, model=client.settings.primary_model)


@app.get("/api/metrics/requests", response_model=list[RequestRecord])
def recent_requests(request: Request) -> list[RequestRecord]:
    """The last requests with status and duration. Local callers only: it describes server activity."""
    if (request.client.host if request.client else "") not in LOCAL_CLIENTS:
        raise HTTPException(403, "metrics are only available from this machine")
    return monitor.recent()


@app.get("/api/samples", response_model=SampleSet)
def samples(market: Market = "US") -> SampleSet:
    return sample_set(market)


def sample_set(market: str = "US") -> SampleSet:
    return SampleSet(
        artwork="DancingFish_Granola_Berry_US_Carton.pdf",
        content_sheet="DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx",
        rule_files=MARKET_RULES[market],
    )


# ---------------- reviews ----------------

@app.post("/api/review", response_model=RunResponse)
async def create_review(
    use_samples: bool = Form(False),
    use_ai: bool = Form(True),
    market: Market = Form("US"),
    artwork: UploadFile | None = File(None),
    content_sheet: UploadFile | None = File(None),
    rule_files: list[UploadFile] | None = File(None),
) -> RunResponse:
    with ReviewRun.create().discarded_on_error() as run:
        if use_samples:
            files = sample_set(market)
            art = run.add_copy(SAMPLES / files.artwork)
            sheet = run.add_copy(SAMPLES / files.content_sheet)
            rules = [run.add_copy(RULES / r) for r in files.rule_files]
        else:
            if artwork is None:
                raise HTTPException(400, "Upload an artwork PDF, or choose the sample files")
            art = await run.add_upload(artwork, "artwork")
            sheet = await run.add_upload(content_sheet, "sheet") if content_sheet else None
            rules = [await run.add_upload(f, "rules") for f in rule_files or []]
            rules = rules or [run.add_copy(RULES / r) for r in DEFAULT_RULES[market]]
        result = await run_in_threadpool(_review, art, sheet, rules, use_ai)
        inputs = RunInputs(artwork=art.name, sheet=sheet.name if sheet else None, rules=[r.name for r in rules])
        return await run_in_threadpool(_finish, run, inputs, result)


@app.post("/api/runs/{run_id}/compare", response_model=RunResponse)
async def compare_proof(
    run_id: str,
    use_ai: bool = Form(True),
    use_sample_v2: bool = Form(False),
    artwork: UploadFile | None = File(None),
) -> RunResponse:
    """Review a new proof with the previous run's content sheet and rules, and
    report what changed and which issues it resolved or introduced."""
    previous = ReviewRun.open(run_id)
    with ReviewRun.create().discarded_on_error() as run:
        if use_sample_v2:
            art = run.add_copy(SAMPLES / SAMPLE_V2)
        elif artwork is not None:
            art = await run.add_upload(artwork, "artwork")
        else:
            raise HTTPException(400, "Upload the new proof (PDF), or choose the generated sample v2")
        old_sheet = previous.sheet_path()
        sheet = run.add_copy(old_sheet) if old_sheet else None
        rules = [run.add_copy(r) for r in previous.rule_paths()]
        feedback_store.carry_waivers(previous.artwork_path(), art)  # dismissed false alarms stay dismissed
        result = await run_in_threadpool(_review, art, sheet, rules, use_ai)
        comparison = await run_in_threadpool(_compare_with, previous, art, result)
        inputs = RunInputs(artwork=art.name, sheet=sheet.name if sheet else None,
                           rules=[r.name for r in rules], previous_run=run_id)
        return await run_in_threadpool(_finish, run, inputs, result, comparison)


def _compare_with(previous: ReviewRun, new_artwork: Path, result: ReviewResult) -> Comparison:
    (before, _), (after, _) = pdf_work.read(previous.artwork_path(), None), pdf_work.read(new_artwork, None)
    return compare(before, after, previous.result().report.findings, result.report.findings)


def _review(art: Path, sheet: Path | None, rules: list[Path], use_ai: bool) -> ReviewResult:
    """Run the pipeline; files it cannot read become a 422 with the reader's message."""
    try:
        return pipeline.run(art, sheet, rules, use_ai=use_ai)
    except UNREADABLE_INPUT as exc:
        raise HTTPException(422, str(exc)) from exc


def _finish(run: ReviewRun, inputs: RunInputs, result: ReviewResult, comparison: Comparison | None = None) -> RunResponse:
    """Render the page, save the run, and build the response."""
    page = pdf_work.render(run.folder / inputs.artwork, run.image_path, run.print_image_path, RENDER_DPI)
    view = _view(run, inputs, page, comparison)
    run.save(inputs, result, view)
    return RunResponse(**view.model_dump(), result=result)


def _view(run: ReviewRun, inputs: RunInputs, page: PageRenders, comparison: Comparison | None) -> RunView:
    return RunView(
        run_id=run.run_id, image_url=run.url("artwork.png"),
        page_width=page.width, page_height=page.height, image_scale=page.image_width / page.width,
        comparison=comparison, panels=page.panels,
        print_image_url=run.url("print.png") if page.has_print_view else None,
        previous_image_url=file_url(inputs.previous_run, "artwork.png") if inputs.previous_run else None,
    )


@app.get("/api/runs/{run_id}", response_model=RunResponse)
def open_run(run_id: str) -> RunResponse:
    """A finished review, as it was returned, with today's waivers applied (a waiver may have been added
    or undone since). Lets the UI come back to a review after a page refresh."""
    run = ReviewRun.open(run_id)
    view = run.view()
    if view is None:  # saved before view.json existed: rebuild the page info (renders come from the cache)
        view = _view(run, run.inputs(), pdf_work.render(run.artwork_path(), run.image_path, run.print_image_path, RENDER_DPI), None)
    result = run.result()
    unwaived = [f.model_copy(update={"waiver": None}) for f in result.report.findings]
    report = result.report.with_findings(feedback_store.apply_waivers(unwaived, run.artwork_path()))
    return RunResponse(**view.model_dump(), result=result.model_copy(update={"report": report}))


# ---------------- run images ----------------

@app.get("/api/runs/{run_id}/artwork.png")
def run_image(run_id: str) -> FileResponse:
    return FileResponse(ReviewRun.open(run_id).image_path, media_type="image/png")


@app.get("/api/runs/{run_id}/print.png")
def run_print_image(run_id: str) -> FileResponse:
    path = ReviewRun.open(run_id).print_image_path
    if not path.exists():
        raise HTTPException(404, "this artwork has no dieline layers, so there is no separate print view")
    return FileResponse(path, media_type="image/png")


# ---------------- follow-up questions and feedback ----------------

@app.post("/api/runs/{run_id}/chat", response_model=ChatAnswer)
def chat(run_id: str, req: ChatRequest) -> ChatAnswer:
    run = ReviewRun.open(run_id)
    finding = run.finding(req.finding_id)
    art, spec = pdf_work.read(run.artwork_path(), run.sheet_path())
    ctx = CheckContext.build(art, RuleSet(rules=[]), spec)
    try:
        return FindingChat(ctx, default_client()).ask(finding, req.question, req.history)
    except AIError as exc:
        raise HTTPException(503, f"The assistant is unavailable: {exc}") from exc


@app.post("/api/runs/{run_id}/feedback")
def feedback(run_id: str, fb: FeedbackRequest) -> dict:
    """Accept, or mark a false alarm. A false alarm waives that problem on this
    artwork for later reviews; on an AI finding with a reason it also becomes
    guidance the AI reads next time. The response says exactly what changed."""
    run = ReviewRun.open(run_id)
    finding = run.finding(fb.finding_id)
    if fb.decision == "false_alarm" and finding.verdict.value == "pass":
        raise HTTPException(400, "A passed check cannot be a false alarm")
    with run.feedback_log.open("a", encoding="utf-8") as log_file:
        log_file.write(fb.model_dump_json() + "\n")
    return feedback_store.record(finding, fb.decision, fb.reason, run.artwork_path())


@app.get("/api/feedback", response_model=FeedbackData)
def list_feedback() -> FeedbackData:
    return feedback_store.load()


@app.delete("/api/waivers/{waiver_id}")
def delete_waiver(waiver_id: str) -> dict:
    if not waiver_id.isalnum():
        raise HTTPException(400, "invalid waiver id")
    if not feedback_store.remove_waiver(waiver_id):
        raise HTTPException(404, f"waiver {waiver_id} not found")
    return {"removed": True}
