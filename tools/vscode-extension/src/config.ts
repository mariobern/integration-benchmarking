import * as vscode from "vscode";

export interface ExtensionConfig {
  pythonPath: string;
  linterPath: string | null;
  timeoutMs: number;
  lintOnSave: boolean;
}

export function getConfig(): ExtensionConfig {
  const cfg = vscode.workspace.getConfiguration("lazerConfigLinter");
  return {
    pythonPath: cfg.get<string>("pythonPath", "python3"),
    linterPath: cfg.get<string | null>("linterPath", null),
    timeoutMs: cfg.get<number>("timeout", 5000),
    lintOnSave: cfg.get<boolean>("lintOnSave", true),
  };
}
