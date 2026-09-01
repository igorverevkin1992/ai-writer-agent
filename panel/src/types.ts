// Типы ответов локального API (ugar/server.py)

export interface QueueChapter {
  chapter: number;
  state: string;
  draft: number;
  e1: string;
  e2: string;
  author_min: number;
  machine_min: number;
  next: string;
}

export interface Brief {
  chapter: number;
  volume: number;
  focal: string;
  date: string;
}

export interface Job {
  name: string;
  chapter: number | null;
  status: "выполняется" | "готово" | "ошибка" | "ручной-режим";
  output: string;
  started: string;
  finished?: string;
}

export interface AppState {
  workspace: string;
  chapters: QueueChapter[];
  briefs: Brief[];
  regression_green: boolean | null;
  models: { writer: string; verifier2: string };
  job: Job | null;
}

export interface Check {
  check_id: string;
  status: "PASS" | "FLAG" | "BRAK";
  threshold: string;
  actual: string;
  quotes: string[];
  rule_source: string;
  note: string;
}

export interface Flag {
  flag_id: string;
  type: string;
  severity: string;
  quote: string;
  rule: string;
  recommendation: string;
  kind: "violation" | "samovolka";
}

export interface Resolution {
  flag_id: string;
  decision: "вычеркнуть" | "канонизировать" | null;
  target_registry: string | null;
}

export interface DiffReport {
  applied_share: number;
  not_applied: number[];
  unauthorized: string[];
  unverifiable: number[];
}

export interface EditParsed {
  seq: number;
  before: string;
  after: string;
  note: string;
  found: boolean;
}

export interface HistoryEntry {
  из: string;
  в: string;
  время: string;
  команда: string;
}

export interface ChapterDetail {
  chapter: number;
  state: string;
  draft: number;
  retries: number;
  iterations: number;
  history: HistoryEntry[];
  verdict: { draft: number; checks: Check[] } | null;
  flags: Flag[];
  resolutions: Resolution[];
  diff_report: DiffReport | null;
  text: string | null;
  drafts: number[];
  edits_md: string | null;
  edits_parsed: EditParsed[];
  canon_batch: string | null;
  author_min: number;
  machine_min: number;
  next: string;
}

export interface ApiLogRow {
  ts: string;
  role: string;
  model: string;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_est: number | null;
  chapter: number | null;
  duration: number | null;
  error?: string;
}
