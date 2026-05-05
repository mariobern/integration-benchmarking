import { describe, expect, it, vi, beforeEach } from "vitest";
import { EventEmitter } from "node:events";

// Mock child_process before importing linter.
vi.mock("node:child_process", () => ({
  spawn: vi.fn(),
}));

import { spawn } from "node:child_process";
import { runLinter } from "../src/linter";

const mockSpawn = vi.mocked(spawn);

interface FakeChildProcess extends EventEmitter {
  stdout: EventEmitter;
  stderr: EventEmitter;
  kill: (signal?: string) => boolean;
}

function makeFakeChild(): FakeChildProcess {
  const child = new EventEmitter() as FakeChildProcess;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = vi.fn(() => true);
  return child;
}

describe("runLinter", () => {
  beforeEach(() => {
    mockSpawn.mockReset();
  });

  it("parses linter JSON envelope into findings on exit code 0", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const promise = runLinter({
      pythonPath: "python3",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
    });

    // Linter now emits {"findings": [...], "pre_existing_count": N | null}.
    const sample = JSON.stringify({
      findings: [
        {
          rule_id: "E001",
          severity: "ERROR",
          message: "feedId 327 is duplicated",
          feed_id: 327,
          symbol: null,
        },
      ],
      pre_existing_count: null,
    });
    child.stdout.emit("data", Buffer.from(sample));
    child.emit("close", 0);

    const result = await promise;
    expect(result.error).toBeUndefined();
    expect(result.findings).toHaveLength(1);
    expect(result.findings[0].rule_id).toBe("E001");
    expect(result.findings[0].feed_id).toBe(327);
  });

  it("rejects bare-array stdout as parse_error (regression guard)", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const promise = runLinter({
      pythonPath: "python3",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
    });

    // Old bare-array shape — no longer accepted.
    child.stdout.emit("data", Buffer.from("[]"));
    child.emit("close", 0);

    const result = await promise;
    expect(result.findings).toEqual([]);
    expect(result.error?.kind).toBe("parse_error");
  });

  it("returns crashed error when subprocess exits non-zero with no JSON output", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const promise = runLinter({
      pythonPath: "python3",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
    });

    child.stderr.emit(
      "data",
      Buffer.from("Traceback (most recent call last):\n  ..."),
    );
    child.emit("close", 2);

    const result = await promise;
    expect(result.findings).toEqual([]);
    expect(result.error?.kind).toBe("crashed");
    if (result.error?.kind === "crashed") {
      expect(result.error.stderr).toContain("Traceback");
    }
  });

  it("returns crashed error when linter exits 1 with stderr but no JSON stdout", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const promise = runLinter({
      pythonPath: "python3",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
    });

    child.stderr.emit(
      "data",
      Buffer.from(
        "ERROR: Invalid JSON in /path/after.json: line 12 column 5\n",
      ),
    );
    child.emit("close", 1);

    const result = await promise;
    expect(result.findings).toEqual([]);
    expect(result.error?.kind).toBe("crashed");
    if (result.error?.kind === "crashed") {
      expect(result.error.stderr).toContain("Invalid JSON");
    }
  });

  it("kills subprocess and returns empty findings when signal aborts", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const controller = new AbortController();
    const promise = runLinter({
      pythonPath: "python3",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
      signal: controller.signal,
    });

    controller.abort();

    const result = await promise;
    expect(result.findings).toEqual([]);
    expect(result.error).toBeUndefined();
    expect(child.kill).toHaveBeenCalledWith("SIGKILL");
  });

  it("returns python_not_found when spawn emits ENOENT", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const promise = runLinter({
      pythonPath: "nonexistent-python",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
    });

    const err = new Error(
      "spawn nonexistent-python ENOENT",
    ) as NodeJS.ErrnoException;
    err.code = "ENOENT";
    child.emit("error", err);

    const result = await promise;
    expect(result.findings).toEqual([]);
    expect(result.error?.kind).toBe("python_not_found");
  });
});
