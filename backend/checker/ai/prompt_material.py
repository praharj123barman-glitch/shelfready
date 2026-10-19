"""What the AI is shown about one review: text lines, the approved sheet, panel images.

Every AI feature (rule judging, marks, chat) builds its prompt from the same
material, so the model always sees the real extracted text with line ids it
can cite, and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..artwork import render_panel_png
from ..checks.base import CheckContext
from .client import GeminiClient

# faces first, then flaps that carry artwork; more images cost quota for little gain
MAX_IMAGES = 9
# at 110 dpi the model misread the recycling mark as "PAP 21"; small print needs more pixels
IMAGE_DPI = 160
PANEL_ORDER = ["front", "back", "left", "right", "top", "bottom", "other"]


@dataclass
class PromptMaterial:
    ctx: CheckContext
    client: GeminiClient

    def text_lines(self) -> str:
        """Every visible line as '[L013] text', grouped by panel, plus hidden text marked as such."""
        rows: list[str] = []
        for panel in PANEL_ORDER:
            lines = self.ctx.art.copy_lines(panel)
            if lines:
                rows.append(f"## {panel} panel")
                rows += [f"[{ln.id}] {ln.text}" for ln in sorted(lines, key=lambda l: (l.bbox.y0, l.bbox.x0))]
        hidden = [ln for ln in self.ctx.art.lines if ln.hidden and ln.role == "copy"]
        if hidden:
            rows.append("## hidden (covered by other artwork, not visible)")
            rows += [f"[{ln.id}] {ln.text}" for ln in hidden]
        return "\n".join(rows)

    def approved_sheet(self) -> str:
        if self.ctx.spec is None:
            return "(no approved content sheet supplied)"
        return "\n".join(f"[{f.cell}] {f.label}: {f.value}" for f in self.ctx.spec.fields.values())

    def market(self) -> str:
        return (self.ctx.spec.value("country_of_market") if self.ctx.spec else None) or "unknown"

    def panel_images(self) -> list:
        """Alternating caption and image parts, faces before flaps."""
        art = self.ctx.art
        if not art.path:
            return []
        parts: list = []
        names = sorted(art.content_panels or art.panels, key=lambda n: (" " in n, n))[:MAX_IMAGES]
        for name in names:
            kind = "flap (folds over or under when the carton is closed, not a face)" if " " in name else "face"
            png = render_panel_png(art.path, art.panels[name], dpi=IMAGE_DPI)
            parts += [f"IMAGE: '{name}' ({kind})", self.client.image_part(png)]
        return parts
