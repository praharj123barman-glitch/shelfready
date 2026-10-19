import { CircleCheck, CircleHelp, OctagonAlert, TriangleAlert, type LucideIcon } from "lucide-react";
import type { Risk, Verdict } from "./types";

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
  market: "Market",
};

// risk is what happens if it ships; shown next to the verdict (how sure we are)
export const RISKS: Record<Risk, { label: string; hint: string }> = {
  safety: { label: "Safety", hint: "Could harm a shopper, e.g. an allergen not declared" },
  legal: { label: "Legal", hint: "Misbranding risk: mandatory information, claims, nutrition" },
  production: { label: "Production", hint: "Print and conversion: folds, hidden objects, type size" },
  data: { label: "Source data", hint: "The approved content sheet itself is wrong" },
  brand: { label: "Brand", hint: "Approved copy, taglines, retailer style" },
};
export const RISK_ORDER: Risk[] = ["safety", "legal", "production", "data", "brand"];
