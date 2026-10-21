"use client";

import { Minus, Plus, ScanSearch } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { API_URL } from "@/lib/api";
import type { BBox, Finding } from "@/lib/types";
import { VERDICTS } from "@/lib/verdicts";

interface Props {
  imageUrl: string;
  pageWidth: number;
  pageHeight: number;
  findings: Finding[];
  selected: Finding | null;
  onSelect: (f: Finding) => void;
}

const ZOOMS = [1, 1.6, 2.4, 3.2];
// a box this large is a whole panel (visual evidence), drawn dashed instead of filled
const PANEL_AREA = 40_000;

function area(b: BBox) {
  return (b.x1 - b.x0) * (b.y1 - b.y0);
}

export function ArtworkViewer({ imageUrl, pageWidth, pageHeight, findings, selected, onSelect }: Props) {
  const [zoom, setZoom] = useState(0);
  const [showAll, setShowAll] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);

  // scroll the first evidence box of the selected finding into the middle of the view
  useEffect(() => {
    const box = selected?.evidence.find((e) => e.bbox)?.bbox;
    const el = scroller.current;
    if (!box || !el) return;
    const content = el.scrollWidth;
    const scale = content / pageWidth;
    el.scrollTo({
      left: ((box.x0 + box.x1) / 2) * scale - el.clientWidth / 2,
      top: ((box.y0 + box.y1) / 2) * scale - el.clientHeight / 2,
      behavior: "smooth",
    });
  }, [selected, zoom, pageWidth]);

  const others = showAll ? findings.filter((f) => f.verdict !== "pass" && f.id !== selected?.id) : [];

  return (
    <div className="flex h-full flex-col rounded-card border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <ScanSearch className="size-4 text-ink-faint" aria-hidden /> Artwork
        </span>
        <div className="flex items-center gap-2">
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-ink-muted">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} className="accent-primary" />
            Show all issues
          </label>
          <div className="flex items-center rounded-md border border-line">
            <button type="button" aria-label="Zoom out" disabled={zoom === 0} onClick={() => setZoom((z) => z - 1)}
              className="cursor-pointer p-1.5 text-ink-muted hover:bg-surface-muted disabled:opacity-40"><Minus className="size-4" /></button>
            <span className="tabular w-10 text-center text-xs text-ink-muted">{Math.round(ZOOMS[zoom] * 100)}%</span>
            <button type="button" aria-label="Zoom in" disabled={zoom === ZOOMS.length - 1} onClick={() => setZoom((z) => z + 1)}
              className="cursor-pointer p-1.5 text-ink-muted hover:bg-surface-muted disabled:opacity-40"><Plus className="size-4" /></button>
          </div>
        </div>
      </div>

      {selected && !selected.evidence.some((e) => e.bbox) && (
        <p className="border-b border-line bg-surface-muted px-3 py-1.5 text-xs text-ink-muted" aria-live="polite">
          This finding has no single spot on the artwork (for example, something missing from the whole pack).
          Its evidence is listed in the detail panel.
        </p>
      )}
      <div ref={scroller} className="relative min-h-0 flex-1 overflow-auto bg-surface-muted p-3">
        <div className="relative" style={{ width: `${ZOOMS[zoom] * 100}%` }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- dynamic image from the API, sized by its container */}
          <img src={`${API_URL}${imageUrl}`} alt="Packaging artwork dieline with all panels" className="block w-full select-none rounded" draggable={false} />
          <svg viewBox={`0 0 ${pageWidth} ${pageHeight}`} className="absolute inset-0 h-full w-full" preserveAspectRatio="none">
            {others.flatMap((f) =>
              f.evidence.filter((e) => e.bbox && area(e.bbox) < PANEL_AREA).map((e, i) => (
                <rect
                  key={`${f.id}-${i}`}
                  x={e.bbox!.x0 - 1.5} y={e.bbox!.y0 - 1.5}
                  width={e.bbox!.x1 - e.bbox!.x0 + 3} height={e.bbox!.y1 - e.bbox!.y0 + 3}
                  fill={VERDICTS[f.verdict].stroke} fillOpacity={0.08}
                  stroke={VERDICTS[f.verdict].stroke} strokeOpacity={0.45} strokeWidth={0.8}
                  className="cursor-pointer"
                  onClick={() => onSelect(f)}
                >
                  <title>{f.title}</title>
                </rect>
              )),
            )}
            {selected?.evidence.filter((e) => e.bbox).map((e, i) => {
              const b = e.bbox!;
              const isPanel = area(b) >= PANEL_AREA;
              return (
                <rect
                  key={`sel-${i}`}
                  x={b.x0 - 3} y={b.y0 - 3} width={b.x1 - b.x0 + 6} height={b.y1 - b.y0 + 6}
                  rx={2}
                  fill={VERDICTS[selected.verdict].stroke} fillOpacity={isPanel ? 0.04 : 0.16}
                  stroke={VERDICTS[selected.verdict].stroke} strokeWidth={isPanel ? 2 : 2.2}
                  strokeDasharray={isPanel ? "8 5" : undefined}
                >
                  <animate attributeName="stroke-opacity" values="1;0.45;1" dur="1.6s" repeatCount="3" />
                </rect>
              );
            })}
          </svg>
        </div>
      </div>
    </div>
  );
}
