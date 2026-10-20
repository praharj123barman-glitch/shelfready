"use client";

import { useEffect, useState } from "react";
import { LoadingScreen } from "@/components/LoadingScreen";
import { ResultsScreen } from "@/components/ResultsScreen";
import { StartScreen } from "@/components/StartScreen";
import { compareProof, getHealth, getRun, runReview, type CompareInput, type ReviewInput } from "@/lib/api";
import type { RunResponse } from "@/lib/types";

type State = { kind: "start" } | { kind: "loading"; useAi: boolean } | { kind: "done"; run: RunResponse };

// The open review is kept in the address (?run=<id>), so a refresh or a shared link comes back to it.
function runIdInUrl(): string | null {
  return new URLSearchParams(window.location.search).get("run");
}

function setRunInUrl(runId: string | null) {
  const url = new URL(window.location.href);
  if (runId) url.searchParams.set("run", runId);
  else url.searchParams.delete("run");
  window.history.replaceState(null, "", url);
}

export default function Home() {
  const [state, setState] = useState<State>({ kind: "start" });
  const [error, setError] = useState<string | null>(null);
  const [aiAvailable, setAiAvailable] = useState<boolean | null>(null);

  async function reopen(runId: string) {
    setState({ kind: "loading", useAi: false });
    try {
      setState({ kind: "done", run: await getRun(runId) });
    } catch (e) {
      setRunInUrl(null);
      setError(`Could not reopen that review: ${e instanceof Error ? e.message : "unknown error"}`);
      setState({ kind: "start" });
    }
  }

  useEffect(() => {
    getHealth().then((h) => setAiAvailable(h.ai_available)).catch((e) => setError(e.message));
    const runId = runIdInUrl();
    // Syncing once with the URL, which the static prerender cannot know. Reading it in the initial state
    // instead would make the first client render differ from the server HTML (a hydration mismatch).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (runId) void reopen(runId);
  }, []);

  function show(run: RunResponse) {
    setRunInUrl(run.run_id);
    setState({ kind: "done", run });
  }

  async function start(input: ReviewInput) {
    setError(null);
    setState({ kind: "loading", useAi: input.useAi });
    try {
      show(await runReview(input));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The review failed.");
      setState({ kind: "start" });
    }
  }

  async function compareWith(previous: RunResponse, input: CompareInput) {
    setError(null);
    setState({ kind: "loading", useAi: input.useAi });
    try {
      show(await compareProof(previous.run_id, input));
    } catch (e) {
      // keep the reviewer on the previous results and say what went wrong
      setState({ kind: "done", run: previous });
      setError(e instanceof Error ? e.message : "The comparison failed.");
    }
  }

  function backToStart() {
    setError(null); // an old compare error is not about the next review
    setRunInUrl(null);
    setState({ kind: "start" });
  }

  if (state.kind === "loading") return <LoadingScreen useAi={state.useAi} />;
  if (state.kind === "done")
    return (
      <ResultsScreen key={state.run.run_id} run={state.run} error={error} onBack={backToStart}
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
