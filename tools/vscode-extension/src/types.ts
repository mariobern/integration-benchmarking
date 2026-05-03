/**
 * Shared types between linter wrapper, locator, and diagnostics.
 * No vscode import — these types are usable in pure unit tests.
 */

export type Severity = "ERROR" | "WARNING";

/** Matches the JSON shape emitted by `config_linter.py --format json`. */
export interface Finding {
  rule_id: string;
  severity: Severity;
  message: string;
  feed_id: number | null;
  symbol: string | null;
}

/** Half-open offset range into the source text. */
export interface OffsetRange {
  startOffset: number;
  endOffset: number;
}

/** Tagged union of failure modes from runLinter(). */
export type LinterError =
  | { kind: "python_not_found" }
  | { kind: "linter_not_found" }
  | { kind: "crashed"; stderr: string }
  | { kind: "timeout" }
  | { kind: "parse_error"; output: string };

export interface LinterResult {
  findings: Finding[];
  error?: LinterError;
}
