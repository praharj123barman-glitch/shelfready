# Esko AIForge submission: ShelfReady

Paste-ready text for each submission field. Problem statement 2: *Is this Packaging Artwork ready to launch?*

---

## 1. Short explanation of the problem and our approach

Before a carton is printed, someone must check the artwork against the approved product information and the
rules of its market. The rules come from regulation (for the US, 21 CFR 101) and from the company's own
rulebook; the approved data sits in a content sheet; the artwork is a dieline PDF with dozens of small text
blocks across faces and flaps. Checking by eye is slow, and a missed allergen or a wrong claim is expensive.

ShelfReady answers "is this ready to launch?" with findings a reviewer can trust. Its principle is
**code proves, AI reasons, and code checks the AI**:

1. It reads the PDF exactly: live text with positions, layers and drawing order, the barcode, and the
   carton's faces and flaps rebuilt from the dieline's own fold lines.
2. 41 code checks prove what can be proven: nutrition math, %DV and FDA rounding, ingredients and copy against
   the approved sheet, claims against ingredients, allergen statements, net quantity rules, hidden objects,
   copy crossing folds, and type size measured from the printed ink. These are labelled Definite.
3. AI handles what needs judgement: rulebooks written in plain prose, logos and seals drawn as graphics, and
   follow-up questions.
4. Every AI answer is verified in code (quotes must exist in the cited line, "missing" claims are re-checked
   on the named panel). Failures are downgraded to Needs review with the reason shown; AI can never be
   Definite.

Every finding shows its evidence (a magnified crop of the artwork, the spreadsheet cell, or the calculation),
the rule it was judged against, and a suggested fix. A rule coverage table shows which rules were checked by
code, by AI, or not at all.

On the Esko sample it reports 20 definite issues (for example 166 kcal declared where the macronutrients give
about 535, a "No Added Sugar" claim with honey, a vegan seal with honey, net weight only on the back, and a
hidden EU nutrition table under the US panel), plus likely and review items and 17 verified passes.

Built for daily review work: issues are ranked by risk (safety first); the market can be switched between US FDA
and India FSSAI, and because checks run only when a rule they implement is loaded, the same carton gets
market-correct results; nutrition math errors come with a corrected Nutrition Facts panel; a new proof can be
compared with the last one (text diff with before and after crops, issues resolved and introduced); and a
reviewer's "false alarm, because..." waives that problem on later reviews and teaches the AI the company's
interpretation.

A mutation eval edits the real sample files 23 ways: **16/16 injected defects detected, 7/7 fixes recognised,
0 false alarms**. Building it found five real bugs in our own checker, now fixed.

## 2. Architecture or flow diagram

Attach `docs/architecture.png`. (The same diagram is in the README as Mermaid.)

## 3. AI models and technologies used

* **Google Gemini 2.5 Flash** (primary), with **Gemini 3 Flash** and **Gemini 2.5 Flash Lite** as automatic
  fallbacks when a model is rate limited or overloaded. Used multimodally: extracted text lines plus panel
  images at 160 dpi. JSON schema output at temperature 0, so every claim is structured and checkable. Three
  uses: turning a prose rulebook into rules (each rule's quote must exist in the document), judging rules no
  code check covers, and an inventory of logos and certification marks. A grounded follow-up chat answers
  questions about a finding and cites artwork lines, which are checked.
* **Verification layer (Python):** quote, absence and panel checks on every AI answer; downgrade on failure.
* **PyMuPDF:** live text with glyph boxes, optional content layers (dieline vs design), drawing sequence
  numbers (hidden text), rendering for crops and ink measurement.
* **zxing-cpp:** barcode decoding; the GS1 check digit is verified in code.
* **openpyxl:** content sheet with cell addresses for evidence.
* **FastAPI + Pydantic:** API with explicit schemas and validated uploads.
* **Next.js 16, React 19, Tailwind CSS 4, Framer Motion:** the review app, with evidence boxes drawn in PDF
  coordinates over the artwork.
* **pytest:** 88 tests (math, parsing, AI guardrails, market switch, feedback loop, version compare, full sample run) and a mutation eval.

## 4. Demo recording

3 to 5 minutes with the sample files. Script: `docs/DEMO_SCRIPT.md`.

## 5. Repository

GitHub link: (add after publishing)
