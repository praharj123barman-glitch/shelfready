"use client";

import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";

// The review is one request, so we do not fake step-by-step progress.
// We say what the server is doing and how long it usually takes.
const STEPS = [
  "Read live text, panels and layers from the PDF",
  "Decode the barcode and look for hidden objects",
  "Run nutrition math and label checks in code",
  "Compare the artwork with the approved content sheet",
];
const AI_STEPS = ["Ask AI about rulebook rules and certification marks", "Verify every AI quote against the artwork"];

export function LoadingScreen({ useAi }: { useAi: boolean }) {
  const steps = useAi ? [...STEPS, ...AI_STEPS] : STEPS;
  return (
    <div className="mx-auto max-w-lg px-6 py-24" aria-live="polite" aria-busy="true">
      <div className="flex items-center gap-3">
        <Loader2 className="size-6 animate-spin text-primary" aria-hidden />
        <h1 className="text-2xl font-bold">Reviewing artwork</h1>
      </div>
      <p className="mt-2 text-sm text-ink-muted">
        Usually {useAi ? "10 to 40" : "2 to 5"} seconds. The checker will:
      </p>
      <ol className="mt-5 space-y-2.5">
        {steps.map((s, i) => (
          <motion.li
            key={s}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, delay: i * 0.05, ease: "easeOut" }}
            className="flex items-start gap-3 text-sm text-ink-muted"
          >
            <span className="tabular mt-0.5 font-mono text-xs text-ink-faint">{String(i + 1).padStart(2, "0")}</span>
            {s}
          </motion.li>
        ))}
      </ol>
    </div>
  );
}
