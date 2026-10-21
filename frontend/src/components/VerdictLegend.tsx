import { VERDICTS, VERDICT_ORDER } from "@/lib/verdicts";

/** What each verdict means, in words (icons and colour only repeat it). Used on the start screen and,
 *  folded away, above the results. */
export function VerdictLegend({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "" : "rounded-card border border-line bg-surface p-6 shadow-card"}>
      {!compact && <h2 className="text-lg font-semibold">How to read the results</h2>}
      <dl className={`grid gap-3 text-sm ${compact ? "sm:grid-cols-2" : "mt-3 sm:grid-cols-2 lg:grid-cols-4"}`}>
        {VERDICT_ORDER.map((v) => {
          const { icon: Icon, label, hint, text } = VERDICTS[v];
          return (
            <div key={v}>
              <dt className={`flex items-center gap-1.5 font-semibold ${text}`}><Icon className="size-4" aria-hidden /> {label}</dt>
              <dd className="mt-0.5 text-ink-muted">{hint}</dd>
            </div>
          );
        })}
      </dl>
      <p className={`text-xs text-ink-faint ${compact ? "mt-3" : "mt-4"}`}>
        Only code checks can say Definite. AI answers, and text read by OCR from a scan or photo, are at most
        Likely, and AI evidence is verified in code before it is shown. ShelfReady supports artwork review; it does
        not replace a regulatory expert or guarantee legal compliance.
      </p>
    </div>
  );
}
