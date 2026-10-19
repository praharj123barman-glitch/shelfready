"use client";

import { motion } from "framer-motion";
import type { Finding, Verdict } from "@/lib/types";
import { CATEGORY_LABELS, VERDICTS, VERDICT_ORDER } from "@/lib/verdicts";
import { MethodTag, RiskTag, VerdictBadge } from "./VerdictBadge";

interface Props {
  findings: Finding[];
  summary: Record<Verdict, number>;
  filter: Verdict | "issues" | "all";
  onFilter: (f: Verdict | "issues" | "all") => void;
  method: "all" | "deterministic" | "ai";
  onMethod: (m: "all" | "deterministic" | "ai") => void;
  selectedId: string | null;
  onSelect: (f: Finding) => void;
}

export function FindingsList({ findings, summary, filter, onFilter, method, onMethod, selectedId, onSelect }: Props) {
  const issues = summary.definite + summary.likely + summary.review;
  const chips: { key: Verdict | "issues" | "all"; label: string; count: number }[] = [
    { key: "issues", label: "All issues", count: issues },
    ...VERDICT_ORDER.map((v) => ({ key: v, label: VERDICTS[v].label, count: summary[v] })),
    { key: "all", label: "Everything", count: findings.length },
  ];
  const shown = findings.filter(
    (f) =>
      (filter === "all" || (filter === "issues" ? f.verdict !== "pass" : f.verdict === filter)) &&
      (method === "all" || f.method === method),
  );

  return (
    <div className="flex h-full flex-col rounded-card border border-line bg-surface shadow-card">
      <div className="space-y-2 border-b border-line p-3">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by verdict">
          {chips.map((c) => (
            <button
              key={c.key}
              type="button"
              role="tab"
              aria-selected={filter === c.key}
              onClick={() => onFilter(c.key)}
              className={`cursor-pointer rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${
                filter === c.key ? "border-ink bg-ink text-white" : "border-line text-ink-muted hover:border-line-strong"
              }`}
            >
              {c.label} <span className="tabular opacity-70">{c.count}</span>
            </button>
          ))}
        </div>
        <div className="flex gap-1.5 text-xs" aria-label="Filter by method">
          {(["all", "deterministic", "ai"] as const).map((m) => (
            <button key={m} type="button" onClick={() => onMethod(m)} aria-pressed={method === m}
              className={`cursor-pointer rounded px-2 py-0.5 ${method === m ? "bg-primary-soft font-semibold text-primary" : "text-ink-faint hover:text-ink-muted"}`}>
              {m === "all" ? "Any method" : m === "deterministic" ? "Code-checked" : "AI-judged"}
            </button>
          ))}
        </div>
      </div>

      <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {shown.map((f, i) => (
          <motion.li key={f.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.15, delay: Math.min(i, 12) * 0.02 }}>
            <button
              type="button"
              onClick={() => onSelect(f)}
              aria-current={selectedId === f.id}
              className={`flex w-full cursor-pointer flex-col gap-1.5 border-l-4 px-3 py-2.5 text-left transition-colors ${
                selectedId === f.id ? "border-primary bg-primary-soft" : "border-transparent hover:bg-surface-muted"
              } ${f.waiver ? "opacity-60" : ""}`}
            >
              <span className="flex items-start gap-2">
                <VerdictBadge verdict={f.verdict} />
                <span className="text-sm font-medium leading-snug text-ink">{f.title}</span>
              </span>
              <span className="flex flex-wrap items-center gap-2 pl-0.5 text-xs text-ink-faint">
                {f.waiver && <span className="rounded border border-line px-1.5 py-0.5 text-xs font-semibold text-ink-faint">Waived</span>}
                {f.verdict !== "pass" && !f.waiver && <RiskTag risk={f.risk} />}
                <span>{CATEGORY_LABELS[f.category] ?? f.category}</span>
                {f.rule_id && <span className="font-mono">{f.rule_id}</span>}
                <MethodTag method={f.method} confidence={f.confidence} />
              </span>
            </button>
          </motion.li>
        ))}
        {!shown.length && <li className="p-6 text-center text-sm text-ink-faint">Nothing matches this filter.</li>}
      </ul>
    </div>
  );
}
