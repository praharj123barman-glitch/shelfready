"use client";

import { motion } from "framer-motion";
import { FileSpreadsheet, FileText, ScrollText, Sparkles, Upload } from "lucide-react";
import { useState } from "react";
import { ARTWORK_ACCEPT, type Market, type ReviewInput } from "@/lib/api";

const MARKET_RULES: Record<Market, string[]> = {
  US: ["US FDA labeling rule pack (21 CFR 101)", "Dancing Fish company rulebook (demo)", "Retailer guidelines in plain prose (demo, read by AI)"],
  India: ["India FSSAI labelling and Legal Metrology pack", "Artwork approval core (any market)"],
};

interface Props {
  aiAvailable: boolean | null;
  error: string | null;
  onStart: (input: ReviewInput) => void;
}

function FilePick({
  label, hint, accept, multiple, icon: Icon, files, onChange, required,
}: {
  label: string; hint: string; accept: string; multiple?: boolean; icon: typeof FileText;
  files: File[]; onChange: (f: File[]) => void; required?: boolean;
}) {
  const id = label.toLowerCase().replace(/\s+/g, "-");
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-semibold text-ink">
        {label} {required ? <span className="text-definite" aria-hidden>*</span> : <span className="font-normal text-ink-faint">(optional)</span>}
      </label>
      <label
        htmlFor={id}
        className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface px-4 py-3 transition-colors hover:border-primary hover:bg-primary-soft"
      >
        <Icon className="size-5 shrink-0 text-ink-faint" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-sm text-ink-muted">
          {files.length ? files.map((f) => f.name).join(", ") : hint}
        </span>
        <span className="text-sm font-medium text-primary">Browse</span>
      </label>
      <input
        id={id}
        type="file"
        accept={accept}
        multiple={multiple}
        className="sr-only"
        onChange={(e) => onChange(Array.from(e.target.files ?? []))}
      />
    </div>
  );
}

export function StartScreen({ aiAvailable, error, onStart }: Props) {
  const [artwork, setArtwork] = useState<File[]>([]);
  const [sheet, setSheet] = useState<File[]>([]);
  const [rules, setRules] = useState<File[]>([]);
  const [useAi, setUseAi] = useState(true);
  const [market, setMarket] = useState<Market>("US");

  return (
    <div className="mx-auto max-w-5xl px-6 py-12">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: "easeOut" }}>
        <p className="text-sm font-semibold uppercase tracking-wide text-primary">Pre-print artwork review</p>
        <h1 className="mt-2 text-4xl font-bold tracking-tight text-ink">Is this artwork ready to launch?</h1>
        <p className="mt-3 max-w-2xl text-lg text-ink-muted">
          ShelfReady reads the live text, layers and marks in a packaging PDF, checks them against regulations, your
          company rulebook and the approved content sheet, and shows the evidence behind every finding.
        </p>
      </motion.div>

      <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-5">
        <motion.section
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: 0.05 }}
          className="min-w-0 rounded-card border border-line bg-surface p-6 shadow-card md:col-span-2"
        >
          <h2 className="text-lg font-semibold">Try the Esko sample</h2>
          <p className="mt-1 text-sm text-ink-muted">Dancing Fish granola carton, its content sheet, and the rules for:</p>
          <div className="mt-3 inline-flex rounded-lg border border-line p-0.5" role="radiogroup" aria-label="Market">
            {(["US", "India"] as const).map((m) => (
              <button key={m} type="button" role="radio" aria-checked={market === m} onClick={() => setMarket(m)}
                className={`cursor-pointer rounded-md px-3 py-1.5 text-sm font-semibold transition-colors ${market === m ? "bg-ink text-white" : "text-ink-muted hover:text-ink"}`}>
                {m === "US" ? "United States" : "India"}
              </button>
            ))}
          </div>
          <ul className="mt-4 space-y-2 text-sm">
            {MARKET_RULES[market].map((r) => (
              <li key={r} className="flex gap-2"><ScrollText className="mt-0.5 size-4 text-ink-faint" aria-hidden />{r}</li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => onStart({ useSamples: true, useAi, market })}
            className="mt-6 w-full cursor-pointer rounded-lg bg-primary px-4 py-3 font-semibold text-white transition-colors hover:bg-primary-hover"
          >
            Review the sample carton
          </button>
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: 0.1 }}
          className="min-w-0 rounded-card border border-line bg-surface p-6 shadow-card md:col-span-3"
        >
          <h2 className="text-lg font-semibold">Or check your own files</h2>
          <div className="mt-4 space-y-4">
            <FilePick label="Artwork" hint="Print or proof PDF. Scans and photos (PDF, PNG, JPG, TIFF) are read by OCR" accept={ARTWORK_ACCEPT} icon={FileText} files={artwork} onChange={setArtwork} required />
            <FilePick label="Approved content sheet" hint="Excel (.xlsx) or CSV with the approved copy and nutrition, in any layout" accept=".xlsx,.xlsm,.csv" icon={FileSpreadsheet} files={sheet} onChange={setSheet} />
            <FilePick
              label="Rules" hint={`JSON rule pack, rulebook (.md) or any rules text (.txt). Default: ${market === "US" ? "US FDA" : "India FSSAI"} pack`}
              accept=".json,.md,.txt" multiple icon={ScrollText} files={rules} onChange={setRules}
            />
          </div>
          <button
            type="button"
            disabled={!artwork.length}
            onClick={() => onStart({ useSamples: false, useAi, market, artwork: artwork[0], sheet: sheet[0], rules })}
            className="mt-6 inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border border-primary px-4 py-3 font-semibold text-primary transition-colors hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Upload className="size-4" aria-hidden /> Check my files
          </button>
        </motion.section>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3 text-sm text-ink-muted">
        <label className="inline-flex cursor-pointer items-center gap-2">
          <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} className="size-4 accent-primary" />
          <Sparkles className="size-4" aria-hidden /> Use AI for rulebook rules and marks
        </label>
        {aiAvailable === false && (
          <span className="text-likely">AI is not configured on the server; only code checks will run.</span>
        )}
      </div>

      {error && (
        <div role="alert" className="mt-6 rounded-lg border border-definite-line bg-definite-soft px-4 py-3 text-sm text-definite">
          {error}
        </div>
      )}
    </div>
  );
}
