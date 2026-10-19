"""Build a 'second proof' of the sample carton for the version-compare demo.

GENERATED DEMO FILE, not from Esko. It applies four fixes and one regression to
the real sample with the same PDF redaction edits the mutation eval uses:

  fixes:      net weight on the front in oz and g, manufacturer address,
              serving size with units
  regression: Brazil nuts dropped from the allergen statement

(Rounding fixes are left out: those Nutrition Facts lines overlap the hidden
EU table, and redacting them would also clip the hidden text.)

Run from backend/:  python -m eval.make_v2_proof
"""

from pathlib import Path

from .mutations import MUTATIONS, apply_pdf

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
DST = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton_v2_GENERATED.pdf"
STEPS = ["R01", "R02", "R03", "D03"]


def main() -> None:
    by_id = {m.id: m for m in MUTATIONS}
    edits = [e for step in STEPS for e in by_id[step].edits]
    apply_pdf(SRC, DST, edits)
    print(f"wrote {DST.name}: " + ", ".join(by_id[s].description for s in STEPS))


if __name__ == "__main__":
    main()
