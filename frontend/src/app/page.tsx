"use client";

import { useEffect, useState } from "react";
import { LoadingScreen } from "@/components/LoadingScreen";
import { ResultsScreen } from "@/components/ResultsScreen";
import { StartScreen } from "@/components/StartScreen";
import { compareProof, getHealth, runReview, type CompareInput, type ReviewInput } from "@/lib/api";
import type { RunResponse } from "@/lib/types";

type State = { kind: "start" } | { kind: "loading"; useAi: boolean } | { kind: "done"; run: RunResponse };

export default function Home() {
  const [state, setState] = useState<State>({ kind: "start" });
  const [error, setError] = useState<string | null>(null);
  const [aiAvailable, setAiAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    getHealth().then((h) => setAiAvailable(h.ai_available)).catch((e) => setError(e.message));
  }, []);

  async function start(input: ReviewInput) {
    setError(null);
    setState({ kind: "loading", useAi: input.useAi });
    try {
      setState({ kind: "done", run: await runReview(input) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The review failed.");
      setState({ kind: "start" });
    }
  }

  async function compareWith(previous: RunResponse, input: CompareInput) {
    setError(null);
    setState({ kind: "loading", useAi: input.useAi });
    try {
      setState({ kind: "done", run: await compareProof(previous.run_id, input) });
    } catch (e) {
      // keep the reviewer on the previous results and say what went wrong
      setState({ kind: "done", run: previous });
      setError(e instanceof Error ? e.message : "The comparison failed.");
    }
  }

  if (state.kind === "loading") return <LoadingScreen useAi={state.useAi} />;
  if (state.kind === "done")
    return (
      <ResultsScreen key={state.run.run_id} run={state.run} error={error} onBack={() => setState({ kind: "start" })}
        onCompare={(input) => compareWith(state.run, input)} />
    );
  return (
    <>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-6 py-3">
          <span className="grid size-7 place-items-center rounded-md bg-primary text-sm font-bold text-white" aria-hidden>S</span>
          <span className="font-semibold">ShelfReady</span>
          <span className="text-sm text-ink-faint">· packaging artwork checker</span>
        </div>
      </header>
      <StartScreen aiAvailable={aiAvailable} error={error} onStart={start} />
    </>
  );
}
