# HackerEarth "Create submission" form: paste-ready text

Repository used below: `https://github.com/praharj123barman-glitch/shelfready` (change it if the repo gets
another name).

---

## Title

ShelfReady: is this packaging artwork ready to launch?

---

## Description

**The problem.** Before a carton is printed, someone must check the artwork against the approved product data
and the rules of its market: regulation (US FDA 21 CFR 101, India FSSAI) plus the company's own rulebook. The
artwork is a dieline PDF with dozens of small text blocks across faces and flaps. Checking by eye is slow, and
a missed allergen or a false claim is expensive.

**Our approach: code proves, AI reasons, and code checks the AI.**

1. **Read exactly.** Live text with positions, layers and drawing order, the barcode, and the carton's faces
   and flaps rebuilt from the dieline's own fold lines.
2. **Prove in code.** 41 checks: nutrition math, %DV and FDA rounding, ingredients and copy against the approved
   sheet, claims against ingredients, allergen statements, net quantity, hidden objects, copy crossing folds,
   type size measured from the printed ink. Only code can mark an issue Definite.
3. **Reason with AI** where judgement is needed: rulebooks written in plain prose, logos and seals drawn as
   graphics, and follow-up questions.
4. **Verify the AI in code.** Quotes must exist in the cited line, "missing" claims are re-checked on the named
   panel, and an AI pass needs evidence code can confirm. Anything that fails goes to Needs review with the
   reason; AI can never be Definite. Model failures show as "could not be checked", never as a pass.

Every finding shows its evidence (a magnified crop of the artwork, the spreadsheet cell, or the calculation),
the rule, a suggested fix and a risk level (safety first). A coverage table shows each rule as checked by code,
by AI, or not at all.

**On the Esko sample:** 20 definite issues (for example 166 kcal declared where the macronutrients give about
535, "No Added Sugar" with honey, a vegan seal with honey, net weight only on the back, a hidden EU nutrition
table under the US panel), 10 likely, 6 for review, 16 verified passes.

**For daily review work:** switch between US FDA and India FSSAI rules; a corrected Nutrition Facts panel;
compare a new proof with the last one (what changed, issues resolved and introduced); mark a false alarm with a
reason, which waives it on later reviews and guides the AI; a 3D carton with issue pins. Scans and photos of
artwork are read by local OCR (issues from OCR text are marked likely, never definite), and content sheets
are read in any layout, including CSV.

**Measured, not claimed:** a mutation eval edits the real sample files 23 ways: 16/16 injected defects
detected, 7/7 fixes recognised, 0 false alarms. 152 automated tests; browser QA of every journey in Chromium
and Firefox.

**Live demo:** https://shelfready-check.vercel.app (click "Review the sample carton").

**Architecture diagram:**
https://github.com/praharj123barman-glitch/shelfready/blob/main/docs/architecture.png

**AI models and technologies:** Google Gemini 2.5 Flash (with Gemini 3 Flash, Flash latest and Flash Lite as
automatic fallbacks), multimodal (text lines plus 160 dpi panel images), JSON schema output at temperature 0
with a fixed seed. PyMuPDF (text, layers, drawing order, rendering), zxing-cpp (barcode, check digit verified
in code), openpyxl, FastAPI + Pydantic, Next.js 16, React 19, Tailwind CSS 4, Framer Motion, pytest.
Full write-up in the repository README and docs/SUBMISSION.md.

---

## Theme

Choose the option for Problem Statement 2, "Is this Packaging Artwork ready to launch?".

---

## Demo Link

The demo video link (YouTube "Unlisted", or Google Drive with "Anyone with the link can view").

---

## Repository URL

https://github.com/praharj123barman-glitch/shelfready

---

## Source Code

Upload `ShelfReady_source.zip` (in Downloads, under 50 MB). Rebuild it after any code change.

---

## Instructions to Run

Requirements: Python 3.12 or newer (tested on 3.14), Node.js 20 or newer with pnpm. A free Google Gemini API
key is optional: without it the code checks still run and the app says the AI part did not run.

1. Backend (from the project folder):
   - `cd backend`
   - `python -m venv ../.venv`
   - Windows: `..\.venv\Scripts\python -m pip install -r requirements.txt`
     (macOS/Linux: `../.venv/bin/python -m pip install -r requirements.txt`)
   - Copy `.env.example` (project folder) to `.env` and set `GEMINI_API_KEY` (optional)
   - Start: `..\.venv\Scripts\python -m uvicorn app:app --port 8000`
2. Frontend (second terminal):
   - `cd frontend`
   - `pnpm install`
   - `pnpm build` then `pnpm start`
   - Open http://localhost:3000
3. Click **Review the sample carton** (the Esko sample files are included in `samples/`), or upload your own
   artwork PDF, content sheet and rule files.
4. Optional checks, from `backend/`: `python -m pytest -q` (152 tests, no API key needed) and
   `python -m eval.run_eval` (mutation eval).
