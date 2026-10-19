"use client";

import { motion } from "framer-motion";
import { Calculator, Check, FileSpreadsheet, Image as ImageIcon, Lightbulb, ScrollText, ThumbsDown } from "lucide-react";
import { useState } from "react";
import { removeWaiver, sendFeedback } from "@/lib/api";
import type { Evidence, FeedbackResult, Finding } from "@/lib/types";
import { CATEGORY_LABELS, VERDICTS } from "@/lib/verdicts";
import { ChatBox } from "./ChatBox";
import { EvidenceCrop } from "./EvidenceCrop";
import { MethodTag, RiskTag, VerdictBadge } from "./VerdictBadge";

const SOURCE: Record<Evidence["source"], { label: string; icon: typeof Calculator }> = {
  artwork: { label: "Artwork", icon: ImageIcon },
  content_sheet: { label: "Content sheet", icon: FileSpreadsheet },
  rulebook: { label: "Rulebook", icon: ScrollText },
  computed: { label: "Computed", icon: Calculator },
};

export interface PageImage {
  imageUrl: string;
  pageWidth: number;
  pageHeight: number;
}

function EvidenceRow({ e, page, stroke }: { e: Evidence; page: PageImage; stroke: string }) {
  const s = SOURCE[e.source];
  const lines = e.line_ids.length > 4 ? `${e.line_ids.length} text lines` : e.line_ids.join(", ");
  const where = [e.panel && `${e.panel} panel`, e.cell && `cell ${e.cell}`, lines || null].filter(Boolean).join(" · ");
  return (
    <li className="flex gap-2.5 text-sm">
      <s.icon className="mt-0.5 size-4 shrink-0 text-ink-faint" aria-hidden />
      <div className="min-w-0 flex-1 space-y-1.5">
        <p className="break-words text-ink">{e.text}</p>
        <p className="text-xs text-ink-faint">{s.label}{where && ` · ${where}`}</p>
        {e.source === "artwork" && e.bbox && (
          <EvidenceCrop {...page} bbox={e.bbox} stroke={stroke} label={`Artwork detail: ${e.text.slice(0, 80)}`} />
        )}
        {e.note && <p className="text-xs italic text-ink-faint">{e.note}</p>}
      </div>
    </li>
  );
}

function DetailsTable({ rows }: { rows: Record<string, string>[] }) {
  const cols = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface-muted text-xs uppercase tracking-wide text-ink-faint">
          <tr>{cols.map((c) => <th key={c} scope="col" className="px-3 py-2 font-semibold">{c}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c} className="tabular px-3 py-1.5 align-top">{r[c] || "-"}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WaiverBanner({ finding }: { finding: Finding }) {
  const [state, setState] = useState<"shown" | "removed" | "error">("shown");
  if (!finding.waiver) return null;
  if (state === "removed")
    return <p className="rounded-lg bg-surface-muted p-3 text-sm text-ink-muted">Waiver removed. It will count again on the next review.</p>;
  return (
    <div className="rounded-lg border border-line bg-surface-muted p-3 text-sm">
      <p className="font-semibold">Waived by a reviewer</p>
      <p className="mt-0.5 text-ink-muted">&ldquo;{finding.waiver.reason}&rdquo; · {finding.waiver.created.slice(0, 10)}</p>
      <p className="mt-1 text-xs text-ink-faint">Still listed for the record, but it no longer blocks the launch verdict.</p>
      <button type="button" onClick={() => removeWaiver(finding.waiver!.id).then(() => setState("removed")).catch(() => setState("error"))}
        className="mt-2 cursor-pointer text-sm font-medium text-primary hover:underline">Undo waiver</button>
      {state === "error" && <p role="alert" className="mt-1 text-xs text-definite">Could not remove the waiver.</p>}
    </div>
  );
}

function Feedback({ runId, finding }: { runId: string; finding: Finding }) {
  const [state, setState] = useState<"idle" | "reason" | "saved" | "error">("idle");
  const [decision, setDecision] = useState<"accepted" | "false_alarm">("accepted");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<FeedbackResult | null>(null);

  async function save(d: "accepted" | "false_alarm", why = "") {
    setDecision(d);
    try {
      setResult(await sendFeedback(runId, finding.id, d, why));
      setState("saved");
    } catch {
      setState("error");
    }
  }

  if (state === "saved")
    return (
      <div className="space-y-1 text-sm">
        <p className="flex items-center gap-1.5 text-pass"><Check className="size-4" /> Saved as {decision === "accepted" ? "accepted" : "false alarm"}.</p>
        {result?.waiver && <p className="text-ink-muted">Waived for this artwork on later reviews (you can undo it there).</p>}
        {result?.rule_note && <p className="text-ink-muted">Your reason was saved as AI guidance for rule <span className="font-mono">{result.rule_note.rule_id}</span>, so the next review reads it.</p>}
      </div>
    );
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => save("accepted")}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:border-pass hover:text-pass">
          <Check className="size-4" /> Accept finding
        </button>
        <button type="button" onClick={() => setState("reason")}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:border-definite hover:text-definite">
          <ThumbsDown className="size-4" /> False alarm
        </button>
      </div>
      {state === "reason" && (
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); save("false_alarm", reason); }}>
          <label htmlFor="fa-reason" className="sr-only">Why is this a false alarm?</label>
          <input id="fa-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is it wrong? (helps improve the check)"
            className="min-w-0 flex-1 rounded-md border border-line px-3 py-1.5 text-sm outline-none focus:border-primary" />
          <button type="submit" className="cursor-pointer rounded-md bg-ink px-3 text-sm font-medium text-white">Save</button>
        </form>
      )}
      {state === "error" && <p role="alert" className="text-xs text-definite">Could not save feedback. Try again.</p>}
    </div>
  );
}

export function FindingDetail({ runId, finding, page }: { runId: string; finding: Finding | null; page: PageImage }) {
  return (
    <div className="h-full overflow-y-auto rounded-card border border-line bg-surface shadow-card">
      {/* enter-only animation: an exiting panel would stay clickable for a moment
          and send chat or feedback for the previous finding */}
        {!finding ? (
          <p className="p-6 text-sm text-ink-faint">Select a finding to see its evidence and the rule behind it.</p>
        ) : (
          <motion.article
            key={finding.id}
            initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="space-y-5 p-5"
          >
            <header className={`-mx-5 -mt-5 border-b px-5 pb-4 pt-5 ${VERDICTS[finding.verdict].soft} ${VERDICTS[finding.verdict].line}`}>
              <div className="flex flex-wrap items-center gap-2">
                <VerdictBadge verdict={finding.verdict} size="md" />
                {finding.verdict !== "pass" && <RiskTag risk={finding.risk} />}
                <MethodTag method={finding.method} confidence={finding.confidence} />
                <span className="text-xs text-ink-faint">{CATEGORY_LABELS[finding.category] ?? finding.category}</span>
              </div>
              <h2 className="mt-2 text-lg font-semibold leading-snug">{finding.title}</h2>
            </header>

            <p className="text-sm leading-relaxed text-ink">{finding.explanation}</p>

            {(finding.expected || finding.found) && (
              <dl className="grid grid-cols-2 gap-3 text-sm">
                {finding.found && <div className="rounded-lg bg-definite-soft p-3"><dt className="text-xs font-semibold text-definite">On the artwork</dt><dd className="tabular mt-0.5">{finding.found}</dd></div>}
                {finding.expected && <div className="rounded-lg bg-pass-soft p-3"><dt className="text-xs font-semibold text-pass">Expected</dt><dd className="tabular mt-0.5">{finding.expected}</dd></div>}
              </dl>
            )}

            {finding.details.length > 0 && <DetailsTable rows={finding.details} />}

            {finding.evidence.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">Evidence</h3>
                <ul className="space-y-3">
                  {finding.evidence.map((e, i) => <EvidenceRow key={i} e={e} page={page} stroke={VERDICTS[finding.verdict].stroke} />)}
                </ul>
              </section>
            )}

            {finding.rule_id && (
              <section className="rounded-lg border border-line bg-surface-muted p-3">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-faint">
                  <ScrollText className="size-3.5" aria-hidden /> Rule <span className="font-mono normal-case">{finding.rule_id}</span>
                </h3>
                {finding.rule_text && <p className="mt-1 text-sm text-ink-muted">{finding.rule_text}</p>}
              </section>
            )}

            {finding.fix && (
              <p className="flex gap-2 rounded-lg border border-primary/20 bg-primary-soft p-3 text-sm">
                <Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden /> <span><b className="font-semibold">Suggested fix:</b> {finding.fix}</span>
              </p>
            )}

            <WaiverBanner key={`wv-${finding.id}`} finding={finding} />
            {finding.verdict !== "pass" && !finding.waiver && <Feedback key={`fb-${finding.id}`} runId={runId} finding={finding} />}
            <ChatBox key={`chat-${finding.id}`} runId={runId} finding={finding} />
          </motion.article>
        )}
    </div>
  );
}
