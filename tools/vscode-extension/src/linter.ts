import { spawn } from "node:child_process";
import { Finding, LinterError, LinterResult } from "./types";

export interface LinterOptions {
  pythonPath: string;
  linterPath: string;
  configPath: string;
  baselinePath: string | null;
  timeoutMs: number;
  signal?: AbortSignal;
}

function firstLine(text: string): string {
  const trimmed = text.trim();
  const newline = trimmed.indexOf("\n");
  return newline === -1 ? trimmed : trimmed.slice(0, newline);
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

    if (options.signal) {
      const onAbort = () => {
        try {
          child.kill("SIGKILL");
        } catch {
          // child may already be dead; ignore
        }
        settle({ findings: [] });
      };
      if (options.signal.aborted) {
        onAbort();
      } else {
        options.signal.addEventListener("abort", onAbort, { once: true });
      }
    }

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

    child.on("close", () => {
      // Linter exits 0 (clean) or 1 (errors and/or input failure).
      try {
        const parsed = JSON.parse(stdout);
        if (Array.isArray(parsed)) {
          settle({ findings: parsed as Finding[] });
          return;
        }
      } catch {
        // fall through
      }
      // Non-JSON output → prefer stderr presence over exit code for dispatch.
      const error: LinterError =
        stderr.trim().length > 0
          ? { kind: "crashed", stderr: firstLine(stderr) }
          : { kind: "parse_error", output: stdout.slice(0, 200) };
      settle({ findings: [], error });
    });
  });
}
