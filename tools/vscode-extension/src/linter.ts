import { spawn } from "node:child_process";
import { Finding, LinterError, LinterResult } from "./types";

export interface LinterOptions {
  pythonPath: string;
  linterPath: string;
  configPath: string;
  baselinePath: string | null;
  timeoutMs: number;
}

export function runLinter(options: LinterOptions): Promise<LinterResult> {
  return new Promise((resolve) => {
    const args: string[] = [
      options.linterPath,
      "--config",
      options.configPath,
      "--format",
      "json",
    ];
    if (options.baselinePath) {
      args.push("--baseline", options.baselinePath);
    } else {
      args.push("--no-baseline");
    }

    const child = spawn(options.pythonPath, args);
    let stdout = "";
    let stderr = "";
    let settled = false;

    const settle = (result: LinterResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };

    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      settle({ findings: [], error: { kind: "timeout" } });
    }, options.timeoutMs);

    child.stdout?.on("data", (d: Buffer | string) => {
      stdout += d.toString();
    });
    child.stderr?.on("data", (d: Buffer | string) => {
      stderr += d.toString();
    });

    child.on("error", (err: NodeJS.ErrnoException) => {
      if (err.code === "ENOENT") {
        settle({ findings: [], error: { kind: "python_not_found" } });
      } else {
        settle({
          findings: [],
          error: { kind: "crashed", stderr: err.message },
        });
      }
    });

    child.on("close", (code) => {
      // Linter exits 0 (no errors), 1 (errors), or 2 (baseline missing).
      // Stdout in all three cases should be a JSON array.
      try {
        const parsed = JSON.parse(stdout);
        if (Array.isArray(parsed)) {
          settle({ findings: parsed as Finding[] });
          return;
        }
      } catch {
        // fall through
      }
      // Non-JSON output → either crash or parse_error.
      const error: LinterError =
        code !== 0 && code !== 1
          ? { kind: "crashed", stderr: stderr.split("\n")[0] || `exit ${code}` }
          : { kind: "parse_error", output: stdout.slice(0, 200) };
      settle({ findings: [], error });
    });
  });
}
