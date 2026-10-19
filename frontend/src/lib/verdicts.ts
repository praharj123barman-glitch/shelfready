import { CircleCheck, CircleHelp, OctagonAlert, TriangleAlert, type LucideIcon } from "lucide-react";
import type { Verdict } from "./types";

export const VERDICTS: Record<Verdict, { label: string; hint: string; icon: LucideIcon; text: string; soft: string; line: string; stroke: string }> = {
  definite: {
    label: "Definite",
    hint: "Proven wrong by calculation or exact comparison",
    icon: OctagonAlert,
    text: "text-definite",
    soft: "bg-definite-soft",
    line: "border-definite-line",
    stroke: "var(--color-definite)",
  },
  likely: {
    label: "Likely",
    hint: "Breaks a rule as interpreted; a person should confirm",
    icon: TriangleAlert,
    text: "text-likely",
    soft: "bg-likely-soft",
    line: "border-likely-line",
    stroke: "var(--color-likely)",
  },
  review: {
    label: "Needs review",
    hint: "Cannot be decided automatically; a person must check",
    icon: CircleHelp,
    text: "text-review",
    soft: "bg-review-soft",
    line: "border-review-line",
    stroke: "var(--color-review)",
  },
  pass: {
    label: "Pass",
    hint: "Checked and correct",
    icon: CircleCheck,
    text: "text-pass",
    soft: "bg-pass-soft",
    line: "border-pass-line",
    stroke: "var(--color-pass)",
  },
};

export const VERDICT_ORDER: Verdict[] = ["definite", "likely", "review", "pass"];

export const CATEGORY_LABELS: Record<string, string> = {
  nutrition: "Nutrition Facts",
  claims: "Claims & marks",
  allergens: "Allergens",
  ingredients: "Ingredients",
  mandatory: "Mandatory info",
  copy: "Approved copy",
  print_readiness: "Print readiness",
  source_data: "Source data",
  ai_rules: "Rulebook (AI)",
};
