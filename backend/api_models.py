"""Request and response shapes of the HTTP API: the contract with the frontend.

Field names here are mirrored in frontend/src/lib/types.ts; change both together.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from checker.ai.chat import ChatTurn
from checker.compare import Comparison
from checker.models import BBox
from checker.pipeline import ReviewResult

Market = Literal["US", "India"]


class Health(BaseModel):
    ok: bool
    ai_available: bool
    model: str


class SampleSet(BaseModel):
    artwork: str
    content_sheet: str
    rule_files: list[str]


class RunView(BaseModel):
    """Everything about a finished run except the review result itself; stored as view.json so a run
    can be reopened later (GET /api/runs/{id})."""

    run_id: str
    image_url: str
    page_width: float
    page_height: float
    image_scale: float = Field(description="image pixels per PDF point, for drawing evidence boxes")
    comparison: Comparison | None = None  # set when this run is a new proof compared with an earlier run
    previous_image_url: str | None = None
    panels: dict[str, BBox] = Field(default_factory=dict, description="faces and flaps in PDF points, for the 3D carton")
    print_image_url: str | None = Field(default=None, description="render with dieline layers off: what actually prints")


class RunResponse(RunView):
    result: ReviewResult


class ChatRequest(BaseModel):
    finding_id: str
    question: str = Field(min_length=2, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=200)  # only the last few are used


class FeedbackRequest(BaseModel):
    finding_id: str
    decision: Literal["accepted", "false_alarm"]
    reason: str = Field(default="", max_length=1000)
