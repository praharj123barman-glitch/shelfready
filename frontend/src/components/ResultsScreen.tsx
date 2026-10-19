"use client";

import { motion } from "framer-motion";
import { ArrowLeft, Info, OctagonX, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import type { Finding, RunResponse, Verdict } from "@/lib/types";
import { RISKS, RISK_ORDER } from "@/lib/verdicts";
import { ArtworkViewer } from "./ArtworkViewer";
import { CoverageTable } from "./CoverageTable";
import { FindingDetail } from "./FindingDetail";
import { FindingsList } from "./FindingsList";

export function ResultsScreen({ run, onBack }: { run: RunResponse; onBack: () => void }) {
  const { report, ai_ran, ai_note, ai_models, coverage, rule_sources } = run.result;
  const firstIssue = report.findings.find((f) => f.verdict !== "pass") ?? report.findings[0] ?? null;
  const [selected, setSelected] = useState<Finding | null>(firstIssue);
  const [filter, setFilter] = useState<Verdict | "issues" | "all">("issues");
  const [method, setMethod] = useState<"all" | "deterministic" | "ai">("all");
  const [tab, setTab] = useState<"findings" | "coverage">("findings");
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
        <nav className="flex gap-1 px-5" aria-label="Result views">
          {(["findings", "coverage"] as const).map((t) => (
            <button key={t} type="button" onClick={() => setTab(t)} aria-current={tab === t}
              className={`cursor-pointer border-b-2 px-3 py-2 text-sm font-medium ${tab === t ? "border-primary text-primary" : "border-transparent text-ink-muted hover:text-ink"}`}>
              {t === "findings" ? "Findings" : "Rule coverage"}
            </button>
          ))}
        </nav>
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
      ) : (
        <main className="min-h-0 flex-1 p-3">
          <CoverageTable rows={coverage} sources={rule_sources} />
        </main>
      )}
    </div>
  );
}
