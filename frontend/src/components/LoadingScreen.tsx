"use client";

import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

// The review is one request, so we do not fake step-by-step progress.
// We say what the server is doing, how long it usually takes, and how long this one has taken.
const STEPS = [
  "Read the text, panels and layers from the PDF (or the image, by OCR)",
  "Decode the barcode and look for hidden objects",
  "Run nutrition math and label checks in code",
  "Compare the artwork with the approved content sheet",
];
const AI_STEPS = ["Ask AI about rulebook rules and certification marks", "Verify every AI quote against the artwork"];
const SLOW_AFTER_S = 45; // past the usual range: say why it can take longer, so it does not look stuck

export function LoadingScreen({ useAi }: { useAi: boolean }) {
  const steps = useAi ? [...STEPS, ...AI_STEPS] : STEPS;
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="mx-auto max-w-lg px-6 py-24" aria-busy="true">
      <div className="flex items-center gap-3">
        <Loader2 className="size-6 animate-spin text-primary motion-reduce:animate-none" aria-hidden />
        <h1 className="text-2xl font-bold">Reviewing artwork</h1>
      </div>
      <p className="mt-2 text-sm text-ink-muted">
        Usually {useAi ? "10 to 40" : "2 to 20"} seconds{" "}
        <span className="tabular text-ink-faint">({seconds} s so far)</span>. The checker will:
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
      {seconds >= SLOW_AFTER_S && (
        <p className="mt-6 rounded-lg bg-surface-muted p-3 text-sm text-ink-muted" aria-live="polite">
          Still working. {useAi ? "A free AI model may be busy, in which case the next one is tried; " : ""}
          scans and photos also take longer, because their text is read by OCR. The review stops with a clear
          message if it cannot finish.
        </p>
      )}
    </div>
  );
}
