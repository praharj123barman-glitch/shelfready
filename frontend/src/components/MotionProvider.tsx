"use client";

import { MotionConfig } from "framer-motion";

/** Framer Motion animations follow the visitor's "reduce motion" setting (CSS rules alone do not reach them). */
export function MotionProvider({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
