import type { CoverageRow, RuleSource } from "@/lib/types";
import { VerdictBadge } from "./VerdictBadge";

const HOW: Record<CoverageRow["checked_by"], string> = {
  code: "Code",
  ai: "AI",
  "not checked": "Not checked",
};

export function CoverageTable({ rows, sources }: { rows: CoverageRow[]; sources: RuleSource[] }) {
  const counts = rows.reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.checked_by]: (acc[r.checked_by] ?? 0) + 1 }), {});
  return (
    <div className="h-full overflow-y-auto rounded-card border border-line bg-surface p-5 shadow-card">
      <h2 className="text-lg font-semibold">Rule coverage</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Every rule supplied, and how it was checked. {counts.code ?? 0} by code, {counts.ai ?? 0} by AI,{" "}
        {counts["not checked"] ?? 0} not checked. Nothing is skipped silently.
      </p>
      <ul className="mt-3 flex flex-wrap gap-2 text-xs">
        {sources.map((s) => (
          <li key={s.name} className="rounded-full border border-line px-2.5 py-1 text-ink-muted">
            {s.name} · {s.rule_count} rules · {s.kind === "ai_extracted" ? "read by AI" : s.kind}
            {s.dropped.length > 0 && <span className="text-likely"> · {s.dropped.length} dropped (quote not found)</span>}
          </li>
        ))}
      </ul>
      <div className="mt-4 overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface-muted text-xs uppercase tracking-wide text-ink-faint">
            <tr>
              <th scope="col" className="px-3 py-2">Rule</th>
              <th scope="col" className="px-3 py-2">Source</th>
              <th scope="col" className="px-3 py-2">Checked by</th>
              <th scope="col" className="px-3 py-2">Result</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.rule_id}>
                <td className="px-3 py-2"><span className="font-mono text-xs text-ink-faint">{r.rule_id}</span><br />{r.title}</td>
                <td className="px-3 py-2 text-ink-muted">{r.source}</td>
                <td className={`px-3 py-2 ${r.checked_by === "not checked" ? "font-semibold text-likely" : ""}`}>{HOW[r.checked_by]}</td>
                <td className="px-3 py-2">
                  {r.result === "not_applicable" ? <span className="text-xs text-ink-faint">Not applicable</span>
                    : r.result ? <VerdictBadge verdict={r.result} /> : <span className="text-xs text-ink-faint">-</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
