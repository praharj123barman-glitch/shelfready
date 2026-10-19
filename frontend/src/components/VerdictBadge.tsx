import { VERDICTS } from "@/lib/verdicts";
import type { Verdict } from "@/lib/types";

export function VerdictBadge({ verdict, size = "sm" }: { verdict: Verdict; size?: "sm" | "md" }) {
  const v = VERDICTS[verdict];
  const Icon = v.icon;
  return (
    <span
      title={v.hint}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border font-semibold ${v.text} ${v.soft} ${v.line} ${
        size === "md" ? "px-2.5 py-1 text-sm" : "px-2 py-0.5 text-xs"
      }`}
    >
      <Icon className={size === "md" ? "size-4" : "size-3.5"} aria-hidden />
      {v.label}
    </span>
  );
}

export function MethodTag({ method, confidence }: { method: "deterministic" | "ai"; confidence: number }) {
  return method === "deterministic" ? (
    <span className="rounded border border-line bg-surface-muted px-1.5 py-0.5 text-xs font-medium text-ink-muted" title="Proven by code: calculation, exact match or file structure">
      Code-checked
    </span>
  ) : (
    <span className="rounded border border-review-line bg-review-soft px-1.5 py-0.5 text-xs font-medium text-review" title="Judged by AI, evidence verified by code where possible">
      AI · {Math.round(confidence * 100)}% conf.
    </span>
  );
}
