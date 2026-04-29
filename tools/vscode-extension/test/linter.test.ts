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

  it("parses linter JSON output into findings on exit code 0", async () => {
    const child = makeFakeChild();
    mockSpawn.mockReturnValue(child as never);

    const promise = runLinter({
      pythonPath: "python3",
      linterPath: "/repo/tools/config-linter/config_linter.py",
      configPath: "/repo/2026-04-29-T123456-foo/after.json",
      baselinePath: null,
      timeoutMs: 5000,
    });

    // Simulate linter producing output then exiting cleanly.
    const sample = JSON.stringify([
      {
        rule_id: "E001",
        severity: "ERROR",
        message: "feedId 327 is duplicated",
        feed_id: 327,
        symbol: null,
      },
    ]);
    child.stdout.emit("data", Buffer.from(sample));
    child.emit("close", 0);

    const result = await promise;
    expect(result.error).toBeUndefined();
    expect(result.findings).toHaveLength(1);
    expect(result.findings[0].rule_id).toBe("E001");
    expect(result.findings[0].feed_id).toBe(327);
  });
});
