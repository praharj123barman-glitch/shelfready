// Mirrors backend/checker models (Pydantic). Keep field names identical.

export type Verdict = "definite" | "likely" | "review" | "pass";
export type Risk = "safety" | "legal" | "production" | "data" | "brand";

export interface BBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Evidence {
  source: "artwork" | "content_sheet" | "rulebook" | "computed";
  text: string;
  panel: string | null;
  bbox: BBox | null;
  line_ids: string[];
  cell: string | null;
  note: string | null;
}

export interface Finding {
  id: string;
  check: string;
  category: string;
  verdict: Verdict;
  risk: Risk;
  title: string;
  explanation: string;
  rule_id: string | null;
  rule_text: string | null;
  expected: string | null;
  found: string | null;
  fix: string | null;
  evidence: Evidence[];
  details: Record<string, string>[];
  method: "deterministic" | "ai";
  confidence: number;
  waiver: Waiver | null;
}

export interface Waiver {
  id: string;
  check: string;
  problem: string;
  reason: string;
  created: string;
}

export interface FeedbackResult {
  saved: boolean;
  waiver: Waiver | null;
  rule_note: { id: string; rule_id: string; note: string } | null;
}

export interface Report {
  artwork: string;
  content_sheet: string | null;
  rule_sources: string[];
  findings: Finding[];
  summary: Record<Verdict, number>;
  ready_to_launch: boolean;
  check_errors: string[];
  waived: number;
}

export interface RuleSource {
  name: string;
  kind: "regulation" | "company" | "ai_extracted";
  rule_count: number;
  dropped: string[];
}

export interface CoverageRow {
  rule_id: string;
  title: string;
  source: string;
  checked_by: "code" | "ai" | "not checked";
  result: Verdict | "not_applicable" | null;
}

export interface ReviewResult {
  report: Report;
  rule_sources: RuleSource[];
  coverage: CoverageRow[];
  ai_ran: boolean;
  ai_note: string | null;
  ai_models: string[];
  corrected_nutrition: CorrectedPanel | null;
}

export interface CorrectedRow {
  key: string;
  label: string;
  indent: boolean;
  printed_amount: string;
  amount: string;
  printed_dv: string | null;
  dv: string | null;
  changed: boolean;
}

export interface CorrectedPanel {
  basis: string;
  servings_per_container: number | null;
  printed_serving: string | null;
  calories_printed: number | null;
  calories: number | null;
  rows: CorrectedRow[];
}

export interface RunResponse {
  run_id: string;
  image_url: string;
  page_width: number;
  page_height: number;
  image_scale: number;
  result: ReviewResult;
  comparison: Comparison | null;
  previous_image_url: string | null;
  panels: Record<string, BBox>;
  print_image_url: string | null;
}

export interface TextChange {
  kind: "added" | "removed" | "changed" | "moved";
  panel: string;
  before: string | null;
  after: string | null;
  before_bbox: BBox | null;
  after_bbox: BBox | null;
}

export interface IssueChange {
  status: "resolved" | "introduced" | "still_open";
  check: string;
  title: string;
  verdict: string;
  rule_id: string | null;
  method: "deterministic" | "ai";
}

export interface Comparison {
  before: string;
  after: string;
  text_changes: TextChange[];
  issues: IssueChange[];
  summary: Record<"changed" | "added" | "removed" | "moved" | "resolved" | "introduced" | "still_open" | "ai_changes", number>;
}

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

export interface ChatAnswer {
  answer: string;
  cited_line_ids: string[];
  needs_human: boolean;
}

export interface Health {
  ok: boolean;
  ai_available: boolean;
  model: string;
}
