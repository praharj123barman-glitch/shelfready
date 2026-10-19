# Demo video script (about 5 minutes)

**Before recording**
* Backend: `cd backend` then `..\.venv\Scripts\python -m uvicorn app:app --port 8000`
* Frontend in production mode (no dev badge): `cd frontend`, `pnpm build`, then `pnpm start`
* Before recording, run once: the US sample review, "Compare a new proof" with the generated v2, and the India sample review, so every AI answer comes from the cache (about 10 seconds each).
* Delete `backend/runs/feedback.json` if you tested waivers, so the demo starts clean.
* Browser at 100% zoom, full screen, 1600 px wide or more. Close other tabs.
* Speak slowly. Each block below is about one breath per line.

---

### 0:00 to 0:25 · The problem (start screen)

> Before a carton goes to print, someone has to check it against the approved product data and the rules for
> its market. That is slow, and the mistakes are expensive. ShelfReady answers one question: is this artwork
> ready to launch?

> The idea is simple: code proves, AI reasons, and code checks the AI.

Point at the three rule sources on the sample card.

> We use Esko's Dancing Fish carton, its content sheet, an FDA rule pack, a company rulebook, and a retailer
> policy written in plain prose.

Click **Review the sample carton**.

### 0:25 to 1:05 · The verdict and a definite finding

> Not ready to launch. Twenty definite issues, ten likely, five for review, and seventeen checks that passed.
> Passes matter: they tell the reviewer what they no longer need to check.

Click **Calories 166 cannot come from these macronutrients**.

> Definite means proven by code. Fifteen grams of fat, sixty six of carbohydrate and thirty four of protein
> give about five hundred thirty five calories, not one hundred sixty six. The box on the artwork and the
> magnified crop show exactly where it is. The rule and the fix are right here.

Click **10 %Daily Value figure(s) are wrong**, point at the table.

> Every percent daily value is recomputed from the FDA reference values.

### 1:05 to 1:45 · Things a human eye misses

Click **19 lines of hidden text under other artwork**.

> This one is invisible on screen. An old European nutrition table is still in the file, painted over by the
> white box. We find it from the PDF's drawing order.

Click **Copy crosses a fold line: GRANOLA**.

> We rebuild the carton's faces and flaps from the dieline's own fold lines. The front headline runs across
> the folds, so it will wrap around the edge.

Click **Net quantity numerals are 0.13 in tall**.

> Type size is measured from the printed ink. This panel size needs net weight at least four point eight
> millimetres tall, and it is three point two, and on the back.

### 1:45 to 2:35 · Claims, and how AI is kept honest

Click **'No Added Sugar' claim, but the ingredients add sugar**.

> Claims are checked against the actual recipe: no added sugar, but honey, coconut sugar and cane sugar.

Click **Certified Vegan mark on the front top flap panel, but the recipe has Honey**.

> The vegan seal is a graphic, not text, so AI finds it in the panel images. Code then sees the honey. Because
> the seal was identified by AI, this is marked likely, with the confidence shown, and never definite.

Click **Brand logo missing from front panel** (AI, retailer rule).

> This rule came from a retailer policy written in plain English. AI turned it into a rule and judged it.
> Every AI claim is verified in code: quotes must exist in the artwork, and "missing" claims are re-checked on
> that exact panel. When verification fails, the finding is downgraded to needs review, with the reason.

### 2:35 to 3:05 · Ask a follow-up question

On the **No Added Sugar** finding, click **Could this be a false alarm?** and wait for the answer.

> Reviewers can ask questions. The answer only uses the finding, the rule and the artwork, and cites the
> lines it relied on.

Click **Accept finding**.

> Reviewers accept findings or mark false alarms with a reason, which we keep to improve the checks.

### 3:05 to 3:25 · Rule coverage

Click the **Rule coverage** tab.

> Every rule from all three sources, and how it was checked: by code, by AI, or not applicable. Nothing is
> skipped silently.

### 3:25 to 3:55 · A second proof

Click **Compare a new proof**, then **Use generated v2 (demo)**.

> The agency sends a second proof. ShelfReady checks it with the same rules and shows what changed: six issues
> resolved, but one new one. Brazil nuts disappeared from the allergen statement. Before and after, side by side.

### 3:55 to 4:20 · Same carton, another market

Click **New review**, switch the market to **India**, click **Review the sample carton**.

> Rules are data. Under India's FSSAI rules the same carton gets different results: no FSSAI licence number,
> no MRP, no per 100 gram nutrition table, and grams alone are fine here. US-only checks switch off by themselves.

### 4:20 to 4:50 · Does it actually work?

Show `backend/eval/RESULTS.md` in the editor (or the README "Measured accuracy" table).

> We measured it. Our eval edits the real Esko files twenty three ways. It caught sixteen of sixteen injected
> defects, recognised seven of seven fixes, with zero false alarms on unrelated checks. The first run was not
> perfect: it exposed five bugs in our own checker, which we fixed.

> ShelfReady. Code proves, AI reasons, and code checks the AI. Thank you.

---

**Backup lines if a judge asks later**
* *What if the AI is wrong?* It cannot produce a definite finding, and every quote and absence is verified in
  code; unverified answers become review items.
* *What if a model is down?* A fallback model answers; if all fail, the rule is reported as unchecked.
* *Other markets?* Rules are data. A new market is a new rule pack; the checks read the rules they cite.
