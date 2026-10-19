import { ArrowRight, CircleCheck, CirclePlus, Minus, MoveRight, OctagonAlert, Pencil } from "lucide-react";
import type { Comparison, RunResponse } from "@/lib/types";
import { EvidenceCrop } from "./EvidenceCrop";

const KIND = {
  changed: { label: "Changed", icon: Pencil },
  added: { label: "Added", icon: CirclePlus },
  removed: { label: "Removed", icon: Minus },
  moved: { label: "Moved", icon: MoveRight },
} as const;

export function ChangesView({ run, comparison }: { run: RunResponse; comparison: Comparison }) {
  const s = comparison.summary;
  const resolved = comparison.issues.filter((i) => i.status === "resolved");
  const introduced = comparison.issues.filter((i) => i.status === "introduced");
  const aiTag = (method: string) =>
    method === "ai" ? <span className="ml-1.5 rounded border border-review-line bg-review-soft px-1 text-xs text-review">AI</span> : null;
  const page = { pageWidth: run.page_width, pageHeight: run.page_height };

  return (
    <div className="h-full overflow-y-auto rounded-card border border-line bg-surface p-5 shadow-card">
      <h2 className="text-lg font-semibold">Changes since the previous proof</h2>
      <p className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-ink-muted">
        {comparison.before} <ArrowRight className="size-3.5" aria-hidden /> {comparison.after}
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-pass-line bg-pass-soft p-3">
          <p className="tabular text-2xl font-bold text-pass">{s.resolved}</p>
          <p className="text-sm text-pass">issues resolved</p>
        </div>
        <div className={`rounded-lg border p-3 ${s.introduced ? "border-definite-line bg-definite-soft" : "border-line bg-surface-muted"}`}>
          <p className={`tabular text-2xl font-bold ${s.introduced ? "text-definite" : "text-ink-muted"}`}>{s.introduced}</p>
          <p className={`text-sm ${s.introduced ? "text-definite" : "text-ink-muted"}`}>new issues introduced</p>
        </div>
        <div className="rounded-lg border border-line bg-surface-muted p-3">
          <p className="tabular text-2xl font-bold">{s.still_open}</p>
          <p className="text-sm text-ink-muted">still open</p>
        </div>
      </div>
      <p className="mt-2 text-xs text-ink-faint">
        Counts are code-checked findings only, which are reproducible.
        {s.ai_changes > 0 && ` ${s.ai_changes} AI-judged change(s) are listed with an AI tag: AI judgements can vary between runs and models, so confirm them.`}
      </p>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">Introduced by this proof</h3>
          {introduced.length ? (
            <ul className="space-y-1.5">
              {introduced.map((i) => (
                <li key={i.check + i.title} className="flex gap-2 text-sm"><OctagonAlert className="mt-0.5 size-4 shrink-0 text-definite" aria-hidden /><span>{i.title}{aiTag(i.method)}</span></li>
              ))}
            </ul>
          ) : <p className="text-sm text-ink-faint">None. Nothing got worse.</p>}
        </section>
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">Resolved by this proof</h3>
          {resolved.length ? (
            <ul className="space-y-1.5">
              {resolved.map((i) => (
                <li key={i.check + i.title} className="flex gap-2 text-sm text-ink-muted"><CircleCheck className="mt-0.5 size-4 shrink-0 text-pass" aria-hidden /><span><s>{i.title}</s>{aiTag(i.method)}</span></li>
              ))}
            </ul>
          ) : <p className="text-sm text-ink-faint">None.</p>}
        </section>
      </div>

      <section className="mt-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
          Text changes ({s.changed} changed, {s.added} added, {s.removed} removed, {s.moved} moved)
        </h3>
        <ul className="space-y-4">
          {comparison.text_changes.map((c, i) => {
            const K = KIND[c.kind];
            return (
              <li key={i} className="rounded-lg border border-line p-3">
                <p className="flex items-center gap-2 text-sm font-semibold">
                  <K.icon className="size-4 text-ink-faint" aria-hidden /> {K.label} on the {c.panel} panel
                </p>
                <div className="mt-2 grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-ink-faint">Before</p>
                    <p className="text-sm">{c.before ?? <span className="text-ink-faint">(nothing)</span>}</p>
                    {c.before_bbox && run.previous_image_url && (
                      <EvidenceCrop imageUrl={run.previous_image_url} {...page} bbox={c.before_bbox} stroke="var(--color-ink-muted)" label="Previous proof detail" />
                    )}
                  </div>
                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-ink-faint">After</p>
                    <p className="text-sm">{c.after ?? <span className="text-ink-faint">(removed)</span>}</p>
                    {c.after_bbox && (
                      <EvidenceCrop imageUrl={run.image_url} {...page} bbox={c.after_bbox} stroke="var(--color-primary)" label="New proof detail" />
                    )}
                  </div>
                </div>
              </li>
            );
          })}
          {!comparison.text_changes.length && <li className="text-sm text-ink-faint">No text changed.</li>}
        </ul>
      </section>
    </div>
  );
}
