"""Telling dieline print marks apart from real copy.

Packaging PDFs carry text that never prints on the pack: panel labels
("Front panel"), plate codes, glue-area notes. They live on structural layers
(cut, crease, dimensions ...) when the file has layers; otherwise we recognise
them by their wording.
"""

from __future__ import annotations

import re

GUIDE_PATTERNS = [
    r"\bpanel\b",
    r"\borientation\b",
    r"^copy free$",
    r"^principal display panel$",
    r"^gl\d+$",
    r"^\d,\d[A-Z0-9 ]+$",  # registration/plate codes in the slug area
]
STRUCTURAL_LAYER_WORDS = ["dimension", "cut", "crease", "glue", "bleed", "coating", "3d assist", "inkfree"]


def is_guide_text(text: str) -> bool:
    """Wording that marks a dieline label rather than copy."""
    t = text.strip().lower()
    return any(re.search(p, t, re.I) for p in GUIDE_PATTERNS)


def is_structural_layer(layer: str | None) -> bool:
    """A layer that holds the dieline (cut, crease, dimensions ...), not the design."""
    return bool(layer) and any(k in layer.lower() for k in STRUCTURAL_LAYER_WORDS)


def is_guide_line(text: str, layer: str | None) -> bool:
    """Prefer the PDF layer (dieline tools put marks on structural layers);
    fall back to text patterns when the file has no layers."""
    if layer:
        return is_structural_layer(layer)
    return is_guide_text(text)
