# ShelfReady: developer guide

This is the guide for working on the code. The [README](../README.md) covers what the product does and how
to run it. This page explains how the code is organised, how a review flows through it, and how to extend it.

## The one idea behind the design

**Code proves, AI reasons, code checks the AI.**

- Anything that can be computed (nutrition math, rounding, text against the approved sheet, fold lines, type
  size) is a *deterministic check*: plain Python, with evidence. Only these can say **Definite**.
- Rules no code check covers go to the AI. Its answers must cite evidence, and code verifies every citation
  before the finding is kept. AI findings are at most **Likely**.
- Text read by OCR (a scan or photo) is treated the same way: a problem proven from it is at most **Likely**
  (`ocr_capped` in pipeline.py), because a misread digit would otherwise become a false Definite.
- If something could not be checked (no API key, a model failed, a check crashed), the report says so. It never
  shows a silent pass.

## Layers

```
frontend/                 Next.js UI. Talks to the API only.
backend/app.py            HTTP endpoints. Thin: open a run, call the pipeline, return JSON.
backend/runs.py           ReviewRun: one review stored on disk (inputs, result, renders).
backend/api_models.py     Request/response shapes (mirrored in frontend/src/lib/types.ts).
backend/checker/          All checking logic. Knows nothing about HTTP.
    pipeline.py           ReviewPipeline: the full review, step by step.  <- start reading here
    engine.py             run_checks(), Report, RiskRanker.
    artwork/              Everything that touches the PDF (see its __init__.py for the module map),
                          including OCR for pages with no live text (artwork/ocr.py).
    content_sheet.py      The approved content sheet (.xlsx/.csv, any layout) with cell addresses.
                          New label names for a field go in FIELD_ALIASES / NUTRIENT_ALIASES.
    rules.py              Rule, RuleSet, rule pack and rulebook loaders, equivalent rules.
    sections.py           Finding blocks on the artwork: ingredients, allergens, badges ...
    nutrition.py          Nutrition Facts parsing, FDA rounding, the corrected panel.
    vocabulary.py         Word lists shared by checks (sugars, animal products, allergens).
    checks/               Deterministic checks, one module per topic.
    ai/                   Everything that calls the model, plus the code that verifies it.
    feedback.py           FeedbackStore: waivers and reviewer guidance.
    compare.py            Version compare: text diff and issue delta.
backend/eval/             Mutation eval (plants defects, measures detection and false alarms).
backend/tests/            pytest suite.
rules/                    Rule files. Rules are data, not code.
```

Dependencies only point downwards: `app.py` uses `checker`, `checker.pipeline` uses the rest of `checker`,
checks use `artwork`, `sections` and `nutrition`. Nothing in `checker` imports from `app.py`.

## How one review flows

```
POST /api/review
  ReviewRun.create()                    run folder under backend/runs/<id>/
  ReviewPipeline.run(pdf, sheet, rules)
    read_artwork(pdf)                   Artwork: lines with panel, role (copy/guide), hidden flag; panels; barcodes
    read_content_sheet(sheet)           ApprovedSpec: approved fields with cell addresses
    _load_rules(files)                  RuleSet (JSON pack, "### ID" rulebook, or prose read by AI)
    run_checks(art, rules, spec)        every registered check whose rule is loaded -> Report
    if AI is on:
      RuleJudge.judge(uncovered rules)  AI verdicts, each citation verified by EvidenceVerifier
      MarkInspector.inspect()           logo and seal inventory from panel images, verified the same way
    FeedbackStore.apply_waivers()       reviewer-dismissed false alarms are marked, not deleted
    Report.with_findings()              sort worst first, recount, decide ready_to_launch
  ReviewRun.save() + renders            result.json, inputs.json, artwork.png, print.png
```

Comparing a new proof (`POST /api/runs/{id}/compare`) runs the same pipeline on the new PDF with the previous
run's sheet and rules, carries the waivers over, then `compare()` diffs the text and the findings.

## Main classes

| Class | File | Job |
|---|---|---|
| `ReviewPipeline` | `checker/pipeline.py` | Runs a full review; the only place that decides the order of steps |
| `Report` | `checker/engine.py` | Findings plus summary counts and the launch verdict (`with_findings` recomputes them) |
| `RiskRanker` | `checker/engine.py` | What happens if a finding ships: safety, legal, production, data, brand |
| `CheckContext` | `checker/checks/base.py` | Everything a check reads, plus `ctx.finding(...)` to build findings |
| `CheckRegistry` / `@check` | `checker/checks/registry.py` | The list of checks and which rules each implements |
| `PdfFile` | `checker/artwork/pdf_file.py` | Opens a PDF once per file version and shares it |
| `ArtworkReader` | `checker/artwork/reader.py` | PDF to `Artwork` |
| `TextAssembler` | `checker/artwork/text_lines.py` | Repairs letter-spaced, curved and duplicated text |
| `PanelFinder` | `checker/artwork/panels.py` | Front, back, sides and flaps from fold lines |
| `HiddenTextDetector` | `checker/artwork/hidden_text.py` | Text painted over by a later opaque shape |
| `GeminiClient` | `checker/ai/client.py` | The only class that calls the model: fallbacks, retries, cache |
| `EvidenceVerifier` | `checker/ai/evidence.py` | Checks every quote, absence claim and panel the model cites |
| `instruction_lines` | `checker/ai/injection.py` | Artwork lines that try to instruct the AI reviewer |
| `RuleJudge` | `checker/ai/rule_judge.py` | AI verdicts for rules no code check covers |
| `MarkInspector` | `checker/ai/marks.py` | Logos and certification seals from panel images |
| `RulebookReader` | `checker/ai/rulebook_reader.py` | Prose rules to `Rule` objects, dropping any whose quote is not in the document |
| `FindingChat` | `checker/ai/chat.py` | Follow-up questions about one finding |
| `FeedbackStore` | `checker/feedback.py` | Waivers and rule notes in one JSON file |
| `ReviewRun` | `backend/runs.py` | One review's folder on disk |

All data passed between layers is a Pydantic model (`checker/models.py`, `api_models.py`), so shapes are
validated and documented in one place.

## How to add a deterministic check

1. Pick the module in `checker/checks/` that fits the topic (or add one and list it in `checks/__init__.py`).
2. Write a function that takes the context and returns findings, and register it with the rule it implements:

```python
@check("FDA-101.60-NAS")
def check_no_added_sugar(ctx: CheckContext) -> list[Finding]:
    claim = ctx.claim_lines(r"no\s+added\s+sugars?")
    if not claim:
        return []                                   # nothing to check
    sweet = [i for i in ctx.ingredient_items() if re.search(SUGAR_WORDS, i, re.I)]
    if not sweet:
        return [ctx.finding("no_added_sugar", "claims", Verdict.PASS, "...", "...",
                            rule_id="FDA-101.60-NAS", evidence=[art_evidence(claim)])]
    return [ctx.finding("no_added_sugar", "claims", Verdict.DEFINITE, "...", "...",
                        rule_id="FDA-101.60-NAS", evidence=[...], fix="...")]
```

3. Rules for checks:
   - Every finding has evidence (`art_evidence`, `block_evidence`, `sheet_evidence`, `computed`).
   - Missing input means a REVIEW finding or nothing, never a PASS.
   - Do not raise for bad data. If a check does crash, the engine records it and the launch verdict cannot
     be "ready".
4. Add a test in `backend/tests/`, and if it catches a new kind of defect, a mutation in `eval/mutations.py`.

The check runs automatically whenever its rule (or an equivalent, see `EQUIVALENT_RULES` in `rules.py`) is
loaded. There is no list to update and no market `if`.

## How to add rules or a market

- **A regulation pack** is a JSON file in `rules/` like `us_fda_food.json`: `name`, `source`, `market`, and
  `rules` with `id`, `title`, `citation`, `url`, `text`.
- **A company rulebook** is Markdown with one `### <ID> <Title>` heading per rule
  (see `dancing_fish_company_rulebook.md`). It is parsed exactly, no AI.
- **Any other text file** is read by `RulebookReader` (AI). Each extracted rule must quote the document, and
  rules whose quote is not found are dropped and listed in the result.
- **A new market** is a new pack plus an entry in `MARKET_RULES` / `DEFAULT_RULES` in `app.py`. Rules with no
  code check are judged by the AI automatically. Write code checks for the ones that matter most.
- If a new rule means the same as an existing one, add it to `EQUIVALENT_RULES` so findings cite whichever is
  loaded.

## AI guardrails (do not weaken these)

- The AI response schemas (`RuleVerdict`, `MarkInventory`) have no "definite" option.
- Every citation goes through `EvidenceVerifier`. A quote must appear in the cited line, an absence claim is
  searched for on the named panel, and a visual citation must name a real panel. Failures downgrade to REVIEW
  and say why.
- An AI PASS needs at least one citation code can verify (a quoted line or a checked absence). Code cannot
  confirm what an image shows, so a pass resting only on images goes to REVIEW (`CODE_CHECKABLE` in
  `rule_judge.py`). Image evidence may still support an issue (LIKELY): a false alarm costs a look, a false
  pass can ship a defect.
- Model errors become "could not be checked automatically" findings, never passes.
- Artwork text is data, never an instruction. Every system prompt says so, and code does not rely on it:
  `ai/injection.py` finds lines that address an AI reviewer, `EvidenceVerifier` refuses them as evidence, and
  while any are on the artwork every AI pass goes to REVIEW (`no_ai_pass` in pipeline.py). Tested in
  `tests/test_prompt_injection.py` with a scripted model that obeys the artwork.
- Text read by OCR, ours or a scanner's invisible layer, caps every Definite at Likely (`ocr_capped`), missing
  items included; only the barcode checks, which decode pixels and verify a check digit, keep Definite.
- `GeminiClient` is the only code that calls the model. Its cache stores real model output keyed on the full
  request, and the result lists which models answered.
- The tests in `tests/test_ai_guardrails.py` feed hand-made bad answers through this layer with no API calls.

## Performance and monitoring

- **Caching by content.** `PdfFile` keeps one open document per distinct file content (SHA-256), with its
  parsed `Artwork` and PNG renders. Every run copies its files to a new folder, so keying on the path would
  re-parse the same artwork on every review. At most 8 documents are kept (least recently used dropped).
- **AI cache.** `ResponseCache` stores real model answers keyed on the full request (prompt, images, schema).
- **Parallel AI.** Rule files load while the PDF is read; `RuleJudge` and `MarkInspector` run side by side and
  share one `PromptMaterial` (panels rendered once). AI findings are numbered in a fixed order afterwards.
- **PDF work in a separate process.** PyMuPDF holds Python's global lock during long native calls, which
  paused the whole server. The API runs every PyMuPDF step (reading, code checks, rendering) in a worker
  process (`checker/pdf_work.py`, `REVIEW_PROCESSES`, default 1); AI calls stay in the API process as threads.
  The worker keeps its caches between jobs. With 2 or more workers, two users' PDF steps run in parallel,
  but each worker has its own cache. Tests and the eval use `InlinePdfWork` (same steps, in-process, holding
  `PDF_LOCK` because PyMuPDF is not thread-safe). A crashed worker fails one request and is replaced.
- **Run storage.** Files that are identical across runs (inputs, 4 MB page renders) are stored once in
  `runs/_blobs` and hard-linked into each run folder, so every folder stays complete. `python -m manage_runs`
  shows disk use (`stats`), applies this to old runs (`share`) and deletes old runs only with
  `prune --keep N --yes`.
- **Model and key fallback.** `GeminiClient` tries each (key, model) route in order: the primary model on every
  key, then the next model on every key. A route that refused in the last 60 seconds goes to the back of the
  queue (it is still tried). Timeouts are enforced without waiting for the stuck call.
- **Monitoring.** `backend/monitoring.py` logs one line per request (request id, status, duration) and adds
  `X-Request-ID` and `Server-Timing` headers. `GET /api/metrics/requests` and `GET /api/feedback` answer only
  requests made on this machine: `is_local` also rejects requests carrying tunnel or proxy headers, because the
  fallback tunnel connects from 127.0.0.1 (on Modal, the live host, requests carry the visitor's own address).
  `RateLimiter` caps reviews and questions per internet visitor, in memory (best effort on Modal while it
  replaces a container). The Modal setup is `deploy/modal_app.py`; see the README's Deploying section. Each
  `ReviewResult` carries `timings` per stage, shown in the results header.

## Testing

```bash
cd backend
../.venv/Scripts/python -m pytest -q        # unit, guardrail, API and full-sample tests (offline)
../.venv/Scripts/python -m eval.run_eval    # mutation eval: detection, repairs, false alarms
```

The tests never call the AI. The API tests use a temporary runs folder and feedback file.

## Conventions

- Small functions and small classes with one job. Module docstrings say what the module is for. Comments say
  *why*, not what.
- Configuration and secrets come from environment variables (`.env`, see `.env.example`). Never commit keys.
- Demo data is labelled as demo (`*_demo.txt`, `*_GENERATED.pdf`, "demo company rulebook").
- When the backend shape changes, update `api_models.py` and `frontend/src/lib/types.ts` together.
