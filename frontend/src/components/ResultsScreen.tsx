"use client";

import { motion } from "framer-motion";
import { ArrowLeft, GitCompare, Info, OctagonX, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import type { Finding, RunResponse, Verdict } from "@/lib/types";
import { RISKS, RISK_ORDER } from "@/lib/verdicts";
import type { CompareInput } from "@/lib/api";
import { ArtworkViewer } from "./ArtworkViewer";
import { Carton3D } from "./Carton3D";
import { ChangesView } from "./ChangesView";
import { CoverageTable } from "./CoverageTable";
import { FindingDetail } from "./FindingDetail";
import { FindingsList } from "./FindingsList";

export function ResultsScreen({ run, onBack, onCompare, error }: {
  run: RunResponse; onBack: () => void; onCompare: (input: CompareInput) => void; error: string | null;
}) {
  const { report, ai_ran, ai_note, ai_models, coverage, rule_sources } = run.result;
  const firstIssue = report.findings.find((f) => f.verdict !== "pass") ?? report.findings[0] ?? null;
  const [selected, setSelected] = useState<Finding | null>(firstIssue);
  const [filter, setFilter] = useState<Verdict | "issues" | "all">("issues");
  const [method, setMethod] = useState<"all" | "deterministic" | "ai">("all");
  const [tab, setTab] = useState<"findings" | "coverage" | "changes" | "carton">(run.comparison ? "changes" : "findings");
  const [comparing, setComparing] = useState(false);
  const s = report.summary;

  const headline = useMemo(() => {
    if (report.ready_to_launch) return { icon: ShieldCheck, text: "No blocking issues found", tone: "text-pass" };
    const n = s.definite + s.likely;
    return { icon: OctagonX, text: `Not ready to launch: ${n} issue${n === 1 ? "" : "s"} to fix`, tone: "text-definite" };
  }, [report.ready_to_launch, s]);
  const Icon = headline.icon;
  // what is at stake among the problems to fix (definite + likely)
  const atStake = RISK_ORDER.map((r) => ({
    r,
    n: report.findings.filter((f) => f.risk === r && (f.verdict === "definite" || f.verdict === "likely")).length,
  })).filter((x) => x.n > 0);

  return (
    <div className="flex h-dvh flex-col">
      <header className="border-b border-line bg-surface">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3">
          <button type="button" onClick={onBack} className="inline-flex cursor-pointer items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
            <ArrowLeft className="size-4" /> New review
          </button>
          <motion.h1 initial={{ opacity: 0 }} animate={{ opacity: 1 }} className={`flex items-center gap-2 text-lg font-bold ${headline.tone}`}>
            <Icon className="size-5" aria-hidden /> {headline.text}
          </motion.h1>
          <p className="tabular text-sm text-ink-muted">
            <b className="text-definite">{s.definite}</b> definite · <b className="text-likely">{s.likely}</b> likely ·{" "}
            <b className="text-review">{s.review}</b> need review · <b className="text-pass">{s.pass}</b> passed
            {report.waived > 0 && <> · {report.waived} waived</>}
          </p>
          {atStake.length > 0 && (
            <p className="text-xs text-ink-muted" aria-label="Issues to fix by risk">
              {atStake.map(({ r, n }, i) => (
                <span key={r}>
                  {i > 0 && " · "}
                  <b className={r === "safety" ? "text-definite" : "text-ink"}>{n}</b> {RISKS[r].label.toLowerCase()}
                </span>
              ))}
            </p>
          )}
          <p className="ml-auto truncate text-xs text-ink-faint" title={report.artwork}>
            {report.artwork}{report.content_sheet ? ` vs ${report.content_sheet}` : ""}
            {ai_ran && ai_models.length > 0 && ` · AI: ${ai_models.join(", ")}`}
          </p>
        </div>
        {(ai_note || !ai_ran || report.check_errors.length > 0) && (
          <p className="flex items-center gap-2 border-t border-line bg-likely-soft px-5 py-1.5 text-xs text-likely">
            <Info className="size-3.5" aria-hidden />
            {[ai_note, ...report.check_errors.map((e) => `Check error: ${e}`)].filter(Boolean).join(" · ")}
          </p>
        )}
        <nav className="flex flex-wrap items-center gap-1 px-5" aria-label="Result views">
          {([...(run.comparison ? ["changes"] : []), "findings", "carton", "coverage"] as const).map((t) => (
            <button key={t} type="button" onClick={() => setTab(t as typeof tab)} aria-current={tab === t}
              className={`cursor-pointer border-b-2 px-3 py-2 text-sm font-medium ${tab === t ? "border-primary text-primary" : "border-transparent text-ink-muted hover:text-ink"}`}>
              {t === "findings" ? "Findings" : t === "coverage" ? "Rule coverage" : t === "carton" ? "3D carton" : "Changes since previous proof"}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-2 py-1">
            {comparing ? (
              <>
                <label className="cursor-pointer rounded-md border border-line px-2.5 py-1 text-sm text-ink-muted hover:border-primary hover:text-primary">
                  Upload new proof (PDF)
                  <input type="file" accept=".pdf" className="sr-only"
                    onChange={(e) => e.target.files?.[0] && onCompare({ useAi: run.result.ai_ran, useSampleV2: false, artwork: e.target.files[0] })} />
                </label>
                <button type="button" onClick={() => onCompare({ useAi: run.result.ai_ran, useSampleV2: true })}
                  className="cursor-pointer rounded-md border border-line px-2.5 py-1 text-sm text-ink-muted hover:border-primary hover:text-primary"
                  title="A second proof generated from the sample: 3 fixes and 1 regression">
                  Use generated v2 (demo)
                </button>
                <button type="button" onClick={() => setComparing(false)} className="cursor-pointer px-1 text-sm text-ink-faint hover:text-ink">Cancel</button>
              </>
            ) : (
              <button type="button" onClick={() => setComparing(true)}
                className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-sm font-medium hover:border-primary hover:text-primary">
                <GitCompare className="size-4" aria-hidden /> Compare a new proof
              </button>
            )}
          </div>
        </nav>
        {error && <p role="alert" className="border-t border-definite-line bg-definite-soft px-5 py-1.5 text-sm text-definite">{error}</p>}
      </header>

      {tab === "findings" ? (
        <main className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.8fr)_minmax(340px,0.95fr)]">
          <div className="min-h-[360px] lg:min-h-0">
            <ArtworkViewer
              imageUrl={run.image_url} pageWidth={run.page_width} pageHeight={run.page_height}
              findings={report.findings} selected={selected} onSelect={setSelected}
            />
          </div>
          <div className="min-h-[360px] lg:min-h-0">
            <FindingsList
              findings={report.findings} summary={s} filter={filter} onFilter={setFilter}
              method={method} onMethod={setMethod} selectedId={selected?.id ?? null} onSelect={setSelected}
            />
          </div>
          <div className="min-h-[360px] lg:min-h-0">
            <FindingDetail
              runId={run.run_id} finding={selected} corrected={run.result.corrected_nutrition}
              page={{ imageUrl: run.image_url, pageWidth: run.page_width, pageHeight: run.page_height }}
            />
          </div>
        </main>
      ) : tab === "carton" ? (
        <main className="min-h-0 flex-1 p-3">
          <Carton3D
            imageUrl={run.print_image_url ?? run.image_url} pageWidth={run.page_width} pageHeight={run.page_height} panels={run.panels}
            findings={report.findings}
            onSelect={(f) => { setSelected(f); setFilter("issues"); setTab("findings"); }}
          />
        </main>
      ) : tab === "coverage" ? (
        <main className="min-h-0 flex-1 p-3">
          <CoverageTable rows={coverage} sources={rule_sources} />
        </main>
      ) : (
        <main className="min-h-0 flex-1 p-3">
          {run.comparison && <ChangesView run={run} comparison={run.comparison} />}
        </main>
      )}
    </div>
  );
}
