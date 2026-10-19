import { API_URL } from "@/lib/api";
import type { BBox } from "@/lib/types";

interface Props {
  imageUrl: string;
  pageWidth: number;
  pageHeight: number;
  bbox: BBox;
  stroke: string;
  label: string;
}

const PAD = 10; // PDF points of context around the evidence
const MAX_H = 220; // px

/** A magnified cut-out of the artwork around one evidence box, positioned in PDF units. */
export function EvidenceCrop({ imageUrl, pageWidth, pageHeight, bbox, stroke, label }: Props) {
  const x0 = Math.max(0, bbox.x0 - PAD);
  const y0 = Math.max(0, bbox.y0 - PAD);
  const x1 = Math.min(pageWidth, bbox.x1 + PAD);
  const y1 = Math.min(pageHeight, bbox.y1 + PAD);
  const w = x1 - x0;
  const h = y1 - y0;
  return (
    <div
      // ring, not border: a border changes the box the percentages below are measured against
      className="relative overflow-hidden rounded-md bg-surface-muted ring-1 ring-line"
      // width follows the aspect ratio so tall crops stay under MAX_H px without being squashed
      style={{ aspectRatio: `${w} / ${h}`, width: `min(100%, ${(MAX_H * w) / h}px)` }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- cropped view of the API-rendered page */}
      <img
        src={`${API_URL}${imageUrl}`}
        alt={label}
        className="absolute left-0 top-0 max-w-none select-none"
        draggable={false}
        // translate % is relative to the image itself, so the offset is exact in both axes
        style={{
          width: `${(pageWidth / w) * 100}%`,
          transform: `translate(${(-x0 / pageWidth) * 100}%, ${(-y0 / pageHeight) * 100}%)`,
        }}
      />
      <svg viewBox={`${x0} ${y0} ${w} ${h}`} className="absolute inset-0 h-full w-full" preserveAspectRatio="none" aria-hidden>
        <rect x={bbox.x0 - 1.5} y={bbox.y0 - 1.5} width={bbox.x1 - bbox.x0 + 3} height={bbox.y1 - bbox.y0 + 3}
          fill="none" stroke={stroke} strokeWidth={Math.max(w, h) / 160} rx={1} />
      </svg>
    </div>
  );
}
