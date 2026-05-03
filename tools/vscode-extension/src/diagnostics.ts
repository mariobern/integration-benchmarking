import * as vscode from "vscode";
import { Finding, LinterError } from "./types";
import { locateFinding } from "./locator";

const SOURCE = "lazer-config-linter";

export function findingsToDiagnostics(
  findings: Finding[],
  document: vscode.TextDocument,
): vscode.Diagnostic[] {
  const text = document.getText();
  return findings.map((finding) => {
    const offsets = locateFinding(text, finding);
    const range = new vscode.Range(
      document.positionAt(offsets.startOffset),
      document.positionAt(offsets.endOffset),
    );
    const severity =
      finding.severity === "ERROR"
        ? vscode.DiagnosticSeverity.Error
        : vscode.DiagnosticSeverity.Warning;
    const diagnostic = new vscode.Diagnostic(range, finding.message, severity);
    diagnostic.code = finding.rule_id;
    diagnostic.source = SOURCE;
    return diagnostic;
  });
}

/**
 * Build a single line-0 diagnostic for an extension-level failure
 * (Python missing, linter missing, subprocess crash, timeout, parse error).
 */
export function errorToDiagnostic(error: LinterError): vscode.Diagnostic {
  const message = formatError(error);
  const range = new vscode.Range(0, 0, 0, 1);
  const diagnostic = new vscode.Diagnostic(
    range,
    message,
    vscode.DiagnosticSeverity.Error,
  );
  diagnostic.code = "EXT-FAILURE";
  diagnostic.source = SOURCE;
  return diagnostic;
}

function formatError(error: LinterError): string {
  switch (error.kind) {
    case "python_not_found":
      return "Python 3 not found. Configure `lazerConfigLinter.pythonPath` or install Python 3.x.";
    case "linter_not_found":
      return "Could not locate `config_linter.py`. Set `lazerConfigLinter.linterPath` if your repo layout is non-standard.";
    case "crashed":
      return `Linter crashed: ${error.stderr || "(no stderr)"}`;
    case "timeout":
      return "Linter timed out. File may be too large.";
    case "parse_error":
      return `Couldn't parse linter output: ${error.output}`;
  }
}
