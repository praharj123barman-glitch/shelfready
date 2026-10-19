"use client";

import { animate, motion, useMotionValue, useReducedMotion } from "framer-motion";
import { RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { API_URL } from "@/lib/api";
import type { BBox, Finding } from "@/lib/types";
import { VERDICTS } from "@/lib/verdicts";

interface Props {
  imageUrl: string;
  pageWidth: number;
  pageHeight: number;
  panels: Record<string, BBox>;
  findings: Finding[];
  onSelect: (f: Finding) => void;
}

type FaceName = "front" | "back" | "right" | "left" | "top" | "bottom";
interface Face { name: FaceName; label: string; rect: BBox; w: number; h: number; transform: string }

const BOX_HEIGHT_PX = 430;
// preset views: [rotateX, rotateY] in degrees
const VIEWS: Record<string, [number, number]> = {
  Front: [-16, -32], Back: [-16, 148], Left: [-12, 58], Right: [-12, -112], Top: [-62, -28],
};
const PANEL_AREA = 40_000; // pt²: evidence this large is a whole panel, not a pin position

const near = (a: number, b: number) => Math.abs(a - b) < 2;

/** Fold the flat dieline into a box using the faces found from its fold lines. */
function buildFaces(panels: Record<string, BBox>): { faces: Face[]; scale: number } | null {
  const front = panels.front;
  if (!front) return null;
  const sides = Object.entries(panels).filter(([n]) => !n.includes(" "));
  // the face beside the front in the flat layout folds onto that side of the box
  const right = sides.find(([, r]) => near(r.x0, front.x1))?.[1];
  const left = sides.find(([, r]) => near(r.x1, front.x0))?.[1];
  const back = panels.back;
  if (!right || !left || !back) return null;
  const W = front.x1 - front.x0;
  const H = front.y1 - front.y0;
  const D = right.x1 - right.x0;
  const s = BOX_HEIGHT_PX / H;
  const [w, h, d] = [W * s, H * s, D * s];
  // top and bottom are the closure panels directly above and below the front face
  const top: BBox = { x0: front.x0, x1: front.x1, y0: front.y0 - D, y1: front.y0 };
  const bottom: BBox = { x0: front.x0, x1: front.x1, y0: front.y1, y1: front.y1 + D };
  const sideName = (r: BBox) => Object.entries(panels).find(([, p]) => p === r)?.[0] ?? "side";
  return {
    scale: s,
    faces: [
      { name: "front", label: "front", rect: front, w, h, transform: `translateZ(${d / 2}px)` },
      { name: "back", label: "back", rect: back, w, h, transform: `rotateY(180deg) translateZ(${d / 2}px)` },
      { name: "right", label: sideName(right), rect: right, w: d, h, transform: `rotateY(90deg) translateZ(${w / 2}px)` },
      { name: "left", label: sideName(left), rect: left, w: d, h, transform: `rotateY(-90deg) translateZ(${w / 2}px)` },
      { name: "top", label: "top closure", rect: top, w, h: d, transform: `rotateX(90deg) translateZ(${h / 2}px)` },
      { name: "bottom", label: "bottom closure", rect: bottom, w, h: d, transform: `rotateX(-90deg) translateZ(${h / 2}px)` },
    ],
  };
}

function inside(b: BBox, r: BBox) {
  const cx = (b.x0 + b.x1) / 2;
  const cy = (b.y0 + b.y1) / 2;
  return cx >= r.x0 && cx <= r.x1 && cy >= r.y0 && cy <= r.y1;
}

export function Carton3D({ imageUrl, pageWidth, pageHeight, panels, findings, onSelect }: Props) {
  const reduce = useReducedMotion();
  const rx = useMotionValue(VIEWS.Front[0]);
  const ry = useMotionValue(VIEWS.Front[1]);
  const drag = useRef<{ x: number; y: number; rx: number; ry: number } | null>(null);
  const built = useMemo(() => buildFaces(panels), [panels]);

  // one slow turn into the front view on first show, so the box reads as 3D at a glance
  useEffect(() => {
    if (reduce) return;
    ry.set(VIEWS.Front[1] - 140);
    const spin = animate(ry, VIEWS.Front[1], { duration: 1.4, ease: [0.22, 1, 0.36, 1] });
    return () => spin.stop();
  }, [reduce, ry]);

  const issues = findings.filter((f) => f.verdict !== "pass" && !f.waiver);
  const pins = useMemo(() => {
    if (!built) return [];
    return built.faces.flatMap((face) =>
      issues.flatMap((f) => {
        const ev = f.evidence.find((e) => e.bbox && (e.bbox.x1 - e.bbox.x0) * (e.bbox.y1 - e.bbox.y0) < PANEL_AREA && inside(e.bbox, face.rect));
        if (!ev?.bbox) return [];
        const r = face.rect;
        return [{ face: face.name, f, left: (((ev.bbox.x0 + ev.bbox.x1) / 2 - r.x0) / (r.x1 - r.x0)) * 100, top: (((ev.bbox.y0 + ev.bbox.y1) / 2 - r.y0) / (r.y1 - r.y0)) * 100 }];
      }),
    );
  }, [built, issues]);

  if (!built) {
    return <p className="p-6 text-sm text-ink-faint">The dieline has no fold lines for front, back and both sides, so the carton cannot be folded in 3D.</p>;
  }
  const front = built.faces[0];
  const depth = built.faces[2].w;
  const pinned = new Set(pins.map((p) => p.f.id));
  const notOnBox = issues.filter((f) => !pinned.has(f.id) && f.evidence.some((e) => e.panel && e.bbox));

  function goTo(view: string) {
    const [x, y] = VIEWS[view];
    const opts = reduce ? { duration: 0 } : { type: "spring" as const, stiffness: 80, damping: 18 };
    animate(rx, x, opts);
    animate(ry, y, opts);
  }

  return (
    <div className="flex h-full flex-col rounded-card border border-line bg-surface shadow-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2">
        <span className="text-sm font-semibold">Folded carton</span>
        <span className="text-xs text-ink-faint">Drag to rotate. Pins are issues; click one to open it.</span>
        <div className="ml-auto flex flex-wrap gap-1">
          {Object.keys(VIEWS).map((v) => (
            <button key={v} type="button" onClick={() => goTo(v)}
              className="cursor-pointer rounded-md border border-line px-2 py-1 text-xs font-medium text-ink-muted hover:border-primary hover:text-primary">
              {v}
            </button>
          ))}
          <button type="button" onClick={() => goTo("Front")} aria-label="Reset view"
            className="cursor-pointer rounded-md border border-line p-1 text-ink-muted hover:border-primary hover:text-primary">
            <RotateCcw className="size-3.5" />
          </button>
        </div>
      </div>

      <div
        className="relative flex min-h-[560px] flex-1 cursor-grab touch-none select-none items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_50%_40%,var(--color-surface)_0%,var(--color-surface-muted)_70%)] active:cursor-grabbing"
        style={{ perspective: 1400 }}
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          drag.current = { x: e.clientX, y: e.clientY, rx: rx.get(), ry: ry.get() };
        }}
        onPointerMove={(e) => {
          if (!drag.current) return;
          ry.set(drag.current.ry + (e.clientX - drag.current.x) * 0.4);
          rx.set(Math.max(-85, Math.min(85, drag.current.rx - (e.clientY - drag.current.y) * 0.4)));
        }}
        onPointerUp={() => { drag.current = null; }}
        onPointerCancel={() => { drag.current = null; }}
      >
        <motion.div
          className="relative"
          style={{ width: front.w, height: front.h, transformStyle: "preserve-3d", rotateX: rx, rotateY: ry }}
          initial={reduce ? false : { scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
        >
          {built.faces.map((face) => (
            <div
              key={face.name}
              aria-label={`${face.label} face`}
              className="absolute overflow-hidden bg-surface ring-1 ring-black/10"
              style={{
                width: face.w, height: face.h, left: (front.w - face.w) / 2, top: (front.h - face.h) / 2,
                transform: face.transform, backfaceVisibility: "hidden",
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- crop of the API-rendered dieline */}
              <img
                src={`${API_URL}${imageUrl}`}
                alt=""
                draggable={false}
                className="pointer-events-none absolute left-0 top-0 max-w-none"
                style={{
                  width: `${(pageWidth / (face.rect.x1 - face.rect.x0)) * 100}%`,
                  transform: `translate(${(-face.rect.x0 / pageWidth) * 100}%, ${(-face.rect.y0 / pageHeight) * 100}%)`,
                }}
              />
              {pins.filter((p) => p.face === face.name).map((p) => (
                <button
                  key={p.f.id}
                  type="button"
                  title={p.f.title}
                  aria-label={`${VERDICTS[p.f.verdict].label}: ${p.f.title}`}
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => onSelect(p.f)}
                  className="absolute size-4 -translate-x-1/2 -translate-y-1/2 cursor-pointer rounded-full border-2 border-white shadow-pop transition-transform hover:scale-125"
                  style={{ left: `${p.left}%`, top: `${p.top}%`, background: VERDICTS[p.f.verdict].stroke }}
                />
              ))}
            </div>
          ))}
        </motion.div>
        <p className="pointer-events-none absolute bottom-2 left-3 text-xs text-ink-faint">
          {Math.round(front.w / built.scale)} × {Math.round(front.h / built.scale)} × {Math.round(depth / built.scale)} pt, folded from the dieline&apos;s own fold lines
        </p>
      </div>

      <div className="border-t border-line px-4 py-2 text-xs text-ink-muted">
        <b>{pins.length}</b> issue pins on the outside of the box.
        {notOnBox.length > 0 && (
          <> {notOnBox.length} more are on flaps that are hidden when the carton is closed (for example{" "}
            {[...new Set(notOnBox.flatMap((f) => f.evidence.map((e) => e.panel)).filter((p): p is string => !!p && p.includes(" ")))].slice(0, 3).join(", ") || "inside flaps"}
            ); see the Findings tab.</>
        )}
      </div>
    </div>
  );
}
