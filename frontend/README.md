# ShelfReady web app

Next.js 16 (App Router), React 19, Tailwind CSS 4, Framer Motion. It talks only to the FastAPI backend in
`../backend`. See the [developer guide](../docs/ARCHITECTURE.md) for the whole system.

## Run

```bash
pnpm install
pnpm dev                 # http://localhost:3000, expects the API on http://127.0.0.1:8000
```

Set `NEXT_PUBLIC_API_URL` if the API runs elsewhere. Production build: `pnpm build && pnpm start`.

## Code map

```
src/app/page.tsx              Screen state machine: start -> loading -> results (and compare)
src/lib/api.ts                Every call to the backend; turns API errors into readable messages
src/lib/types.ts              Response shapes, mirrored from backend/api_models.py
src/lib/verdicts.ts           Verdict and risk labels, colours and order
src/components/
  StartScreen.tsx             Market choice, sample run or upload
  LoadingScreen.tsx           Progress while a review runs
  ResultsScreen.tsx           Layout of the results: viewer, findings, detail, tabs
  ArtworkViewer.tsx           Page image with evidence boxes drawn in PDF coordinates; print view toggle
  Carton3D.tsx                The flat dieline folded into a CSS 3D carton
  FindingsList.tsx            Findings grouped by verdict, sorted by risk
  FindingDetail.tsx           One finding: explanation, evidence, fix, feedback buttons
  EvidenceCrop.tsx            Magnified crop of the exact artwork spot
  ChatBox.tsx                 Follow-up questions about a finding
  CoverageTable.tsx           Every rule: checked by code, AI, or not at all
  CorrectedNutrition.tsx      The Nutrition Facts panel as the printed amounts require
  ChangesView.tsx             Version compare: text changes and resolved/introduced issues
  VerdictBadge.tsx            The verdict pill
```

Evidence boxes come from the API in PDF points. Multiply by `image_scale` from the run response to get image
pixels.

This version of Next.js has breaking changes from older releases. Read the guides in
`node_modules/next/dist/docs/` before changing framework-level code (see `AGENTS.md`).
