"use client";

import { Loader2, MessageSquare, Send } from "lucide-react";
import { useState } from "react";
import { askAboutFinding } from "@/lib/api";
import type { ChatTurn, Finding } from "@/lib/types";

// Quick-start questions, so a reviewer can start a conversation in one click
const STARTERS = ["Why does this matter?", "How do I fix it?", "Could this be a false alarm?"];

export function ChatBox({ runId, finding }: { runId: string; finding: Finding }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(question: string) {
    const q = question.trim();
    if (q.length < 2 || busy) return;
    setBusy(true);
    setError(null);
    setInput("");
    const history = turns;
    setTurns((t) => [...t, { role: "user", text: q }]);
    try {
      const a = await askAboutFinding(runId, finding.id, q, history);
      const note = a.needs_human ? " A person should confirm this." : "";
      const cites = a.cited_line_ids.length ? ` [lines ${a.cited_line_ids.join(", ")}]` : "";
      setTurns((t) => [...t, { role: "assistant", text: a.answer + note + cites }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The assistant could not answer.");
      setTurns((t) => t.slice(0, -1));
      setInput(q);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-line" aria-label="Ask about this finding">
      <h3 className="flex items-center gap-2 border-b border-line px-3 py-2 text-sm font-semibold">
        <MessageSquare className="size-4 text-ink-faint" aria-hidden /> Ask about this finding
      </h3>
      <div className="space-y-2 p-3" aria-live="polite">
        {!turns.length && (
          <div className="flex flex-wrap gap-1.5">
            {STARTERS.map((s) => (
              <button key={s} type="button" onClick={() => ask(s)} disabled={busy}
                className="cursor-pointer rounded-full border border-line px-2.5 py-1 text-xs text-ink-muted hover:border-primary hover:text-primary disabled:opacity-50">
                {s}
              </button>
            ))}
          </div>
        )}
        {turns.map((t, i) => (
          <p key={i} className={`rounded-lg px-3 py-2 text-sm ${t.role === "user" ? "ml-8 bg-primary-soft text-ink" : "mr-4 bg-surface-muted text-ink"}`}>
            {t.text}
          </p>
        ))}
        {busy && <p className="flex items-center gap-2 text-xs text-ink-faint"><Loader2 className="size-3.5 animate-spin" /> Thinking from the evidence...</p>}
        {error && <p role="alert" className="text-xs text-definite">{error}</p>}
      </div>
      <form
        className="flex gap-2 border-t border-line p-2"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <label htmlFor="chat-q" className="sr-only">Your question</label>
        <input
          id="chat-q" value={input} onChange={(e) => setInput(e.target.value)} placeholder="e.g. Is honey at 1% really added sugar?"
          className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 text-sm outline-none focus:border-primary"
        />
        <button type="submit" disabled={busy || input.trim().length < 2} aria-label="Send question"
          className="cursor-pointer rounded-md bg-primary px-3 text-white hover:bg-primary-hover disabled:opacity-40">
          <Send className="size-4" />
        </button>
      </form>
    </section>
  );
}
