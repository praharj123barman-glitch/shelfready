"""Read the approved product content sheet (Excel) into labelled fields.

The sheet is a form, not a table: labels sit in column A or D with the value
to their right and a reviewer note after that. We read every label/value pair
with its cell address, so findings can point at the exact approved cell.
"""

from __future__ import annotations

import re
from pathlib import Path

import openpyxl
from pydantic import BaseModel, Field

# (label column, value column, note column) layouts used on the sheet
FIELD_LAYOUTS = [("A", "B", "C"), ("D", "E", "F")]


class SheetError(ValueError):
    """The content sheet is missing or not in the expected form."""


class SheetField(BaseModel):
    label: str
    value: str
    cell: str
    note: str | None = None


class SheetNutrient(BaseModel):
    name: str
    amount: str
    dv: str | None
    cell: str


class ApprovedSpec(BaseModel):
    file_name: str
    sheet_name: str
    fields: dict[str, SheetField]
    nutrition_basis: str | None = None
    nutrition: list[SheetNutrient] = Field(default_factory=list)

    def get(self, key: str) -> SheetField | None:
        return self.fields.get(key)

    def value(self, key: str) -> str | None:
        f = self.fields.get(key)
        return f.value if f else None


def field_key(label: str) -> str:
    """'Legal Name / Statement of Identity' -> 'legal_name_statement_of_identity'."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _cell_text(ws, ref: str) -> str | None:
    v = ws[ref].value
    if v is None:
        return None
    text = str(v).strip()
    for dash in ("—", "–", "�"):  # the sheet mixes dash glyphs
        text = text.replace(dash, "-")
    return text or None


def _read_fields(ws, stop_row: int) -> dict[str, SheetField]:
    fields: dict[str, SheetField] = {}
    for row in range(1, stop_row):
        for lab_col, val_col, note_col in FIELD_LAYOUTS:
            label = _cell_text(ws, f"{lab_col}{row}")
            value = _cell_text(ws, f"{val_col}{row}")
            if not label or value is None:
                continue
            key = field_key(label)
            if key in {"field"}:  # table header rows
                continue
            fields[key] = SheetField(label=label, value=value, cell=f"{val_col}{row}", note=_cell_text(ws, f"{note_col}{row}"))
    return fields


def _find_row(ws, text: str) -> int | None:
    for row in range(1, ws.max_row + 1):
        if (_cell_text(ws, f"A{row}") or "").lower() == text.lower():
            return row
    return None


def _read_nutrition(ws, header_row: int) -> tuple[str | None, list[SheetNutrient]]:
    """Nutrient rows below the header: name in A, first basis amount in B, %DV in C."""
    basis = _cell_text(ws, f"B{header_row}")
    rows: list[SheetNutrient] = []
    for row in range(header_row + 1, ws.max_row + 1):
        name = _cell_text(ws, f"A{row}")
        amount = _cell_text(ws, f"B{row}")
        if not name or amount is None:
            break
        dv = _cell_text(ws, f"C{row}")
        rows.append(SheetNutrient(name=name, amount=amount, dv=None if dv in {None, "-"} else dv, cell=f"B{row}"))
    return basis, rows


def read_content_sheet(path: str | Path) -> ApprovedSpec:
    path = Path(path)
    if not path.exists():
        raise SheetError(f"Content sheet not found: {path.name}")
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as exc:
        raise SheetError(f"Could not open {path.name} as an Excel workbook: {exc}") from exc
    ws = wb.worksheets[0]

    nutrition_row = _find_row(ws, "Nutrient Composition")
    fields = _read_fields(ws, nutrition_row or ws.max_row + 1)
    if not fields:
        raise SheetError(f"{path.name} has no label/value fields in columns A:B or D:E")
    basis, nutrition = _read_nutrition(ws, nutrition_row) if nutrition_row else (None, [])
    return ApprovedSpec(
        file_name=path.name, sheet_name=ws.title, fields=fields, nutrition_basis=basis, nutrition=nutrition
    )
