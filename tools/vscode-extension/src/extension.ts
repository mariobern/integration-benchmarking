import * as vscode from "vscode";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { runLinter } from "./linter";
import { resolveLinterPath } from "./resolver";
import { errorToDiagnostic, findingsToDiagnostics } from "./diagnostics";
import { getConfig } from "./config";

const PROPOSAL_PATTERN = /\d{4}-\d{2}-\d{2}-T\d{6}-[a-z0-9-]+\/after\.json$/;

const SOURCE = "lazer-config-linter";

// Track in-flight subprocesses by file so we can cancel on rapid re-saves.
const inflight = new Map<string, AbortController>();

export function activate(context: vscode.ExtensionContext): void {
  const collection = vscode.languages.createDiagnosticCollection(SOURCE);
  context.subscriptions.push(collection);

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(async (document) => {
      await handleSave(document, collection);
    }),
  );
}

export function deactivate(): void {
  // Disposables are cleaned up via context.subscriptions.
}

async function handleSave(
  document: vscode.TextDocument,
  collection: vscode.DiagnosticCollection,
): Promise<void> {
  const cfg = getConfig();
  if (!cfg.lintOnSave) return;

  const fsPath = document.uri.fsPath;
  const normalized = fsPath.split(/\\+/).join("/");
  if (!PROPOSAL_PATTERN.test(normalized)) return;

  const workspaceFolder = vscode.workspace.getWorkspaceFolder(document.uri);
  if (!workspaceFolder) return;
  const workspaceRoot = workspaceFolder.uri.fsPath;

  // Resolve the linter (explicit setting overrides walk-up).
  let linterPath: string | null;
  if (cfg.linterPath) {
    linterPath = existsSync(cfg.linterPath) ? cfg.linterPath : null;
    if (linterPath === null) {
      collection.set(document.uri, [
        errorToDiagnostic({ kind: "linter_not_found" }),
      ]);
      return;
    }
  } else {
    linterPath = resolveLinterPath(dirname(fsPath), workspaceRoot);
  }

  if (!linterPath) {
    collection.set(document.uri, [
      errorToDiagnostic({ kind: "linter_not_found" }),
    ]);
    return;
  }

  // Detect sibling before.json.
  const siblingBefore = join(dirname(fsPath), "before.json");
  const baselinePath = existsSync(siblingBefore) ? siblingBefore : null;

  // Cancel any in-flight subprocess for this file.
  inflight.get(fsPath)?.abort();
  const controller = new AbortController();
  inflight.set(fsPath, controller);

  try {
    const result = await runLinter({
      pythonPath: cfg.pythonPath,
      linterPath,
      configPath: fsPath,
      baselinePath,
      timeoutMs: cfg.timeoutMs,
      signal: controller.signal,
    });

    // If a newer save kicked off another lint, drop this result.
    if (inflight.get(fsPath) !== controller) return;

    if (result.error) {
      collection.set(document.uri, [errorToDiagnostic(result.error)]);
      return;
    }
    collection.set(
      document.uri,
      findingsToDiagnostics(result.findings, document),
    );
  } finally {
    if (inflight.get(fsPath) === controller) {
      inflight.delete(fsPath);
    }
  }
}
