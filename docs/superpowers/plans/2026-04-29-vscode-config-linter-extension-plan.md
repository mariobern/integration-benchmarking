# VS Code Config Linter Extension — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small VS Code extension at `tools/vscode-extension/` that runs the existing Python config linter on save and surfaces findings as inline diagnostics in proposal `after.json` files.

**Architecture:** TypeScript extension distributed as a `.vsix` package. Activates on JSON files matching the proposal-directory regex; spawns the existing Python linter as a subprocess on save; uses Microsoft's `jsonc-parser` to map findings to file ranges; updates a singleton `DiagnosticCollection`. No LSP, no daemon — each save is an independent subprocess.

**Tech Stack:** TypeScript (strict mode), Node 18+, VS Code Extension API, `jsonc-parser` (range-tracking JSON parser), `vitest` (unit tests), `@vscode/vsce` (packaging).

**Spec:** `docs/superpowers/specs/2026-04-29-vscode-config-linter-extension-design.md`

---

## File Structure

```
tools/vscode-extension/
├── package.json              # extension manifest, activation events, settings
├── tsconfig.json             # TypeScript build config (strict)
├── .gitignore                # node_modules, out/, *.vsix
├── .vscodeignore             # exclude tests/sources from packaged .vsix
├── README.md                 # install + usage
├── vitest.config.ts          # vitest config
├── src/
│   ├── types.ts              # Finding, OffsetRange, LinterError types
│   ├── locator.ts            # text + Finding → OffsetRange (pure)
│   ├── linter.ts             # spawn linter subprocess (pure, vscode-free)
│   ├── config.ts             # read workspace settings (vscode-coupled, thin)
│   ├── diagnostics.ts        # findings → vscode.Diagnostic[] (vscode-coupled)
│   └── extension.ts          # activate(), deactivate(), event wiring
└── test/
    ├── fixtures/             # small JSON fixtures for locator tests
    │   ├── one-feed.json
    │   ├── one-publisher.json
    │   └── unparseable.json
    ├── locator.test.ts       # 5 unit tests
    └── linter.test.ts        # 2 unit tests (mocked spawn)
```

**Module responsibilities (designed for testability — pure modules have no `vscode` import):**

- `types.ts`: shared types. No imports. Easy to test against.
- `locator.ts`: given a JSON document text and a `Finding`, return the `OffsetRange` of the most relevant anchor. Pure. Unit-tested via vitest.
- `linter.ts`: given options (pythonPath, linterPath, configPath, baselinePath, timeoutMs), spawn the subprocess, return `{findings, error?}`. Pure (no `vscode` import). Unit-tested via vitest with `child_process.spawn` mocked.
- `config.ts`: thin wrapper around `vscode.workspace.getConfiguration('lazerConfigLinter')` returning a typed `Config` object.
- `diagnostics.ts`: glue between `locator` (offsets) and `vscode.TextDocument.positionAt` (line/col) → `vscode.Diagnostic`. Small, vscode-coupled. Covered by smoke test.
- `extension.ts`: `activate()` registers the diagnostic collection and the save handler; the save handler does the path gate, walk-up resolver, in-flight subprocess management, calls into `linter`, then `diagnostics`, then updates the collection.

Manual smoke test in `pyth-lazer-staging-governance` is the integration check.

---

## Task 1: Scaffold extension package

**Files:**

- Create: `tools/vscode-extension/package.json`
- Create: `tools/vscode-extension/tsconfig.json`
- Create: `tools/vscode-extension/.gitignore`
- Create: `tools/vscode-extension/.vscodeignore`
- Create: `tools/vscode-extension/vitest.config.ts`
- Create: `tools/vscode-extension/README.md`
- Create: `tools/vscode-extension/src/extension.ts` (placeholder)

- [ ] **Step 1: Create the package.json manifest**

```json
{
  "name": "lazer-config-linter",
  "displayName": "Lazer Config Linter",
  "description": "Inline diagnostics for pyth-lazer governance proposal after.json files. Wraps the Python config linter.",
  "version": "0.1.0",
  "publisher": "pyth-network",
  "engines": { "vscode": "^1.85.0" },
  "categories": ["Linters"],
  "activationEvents": ["onLanguage:json"],
  "main": "./out/extension.js",
  "contributes": {
    "configuration": {
      "title": "Lazer Config Linter",
      "properties": {
        "lazerConfigLinter.pythonPath": {
          "type": "string",
          "default": "python3",
          "description": "Python interpreter path. Use absolute path if Python is not on PATH."
        },
        "lazerConfigLinter.linterPath": {
          "type": ["string", "null"],
          "default": null,
          "description": "Explicit path to config_linter.py. Set to null for walk-up auto-detect."
        },
        "lazerConfigLinter.timeout": {
          "type": "number",
          "default": 5000,
          "description": "Subprocess kill timeout in milliseconds."
        },
        "lazerConfigLinter.lintOnSave": {
          "type": "boolean",
          "default": true,
          "description": "Master switch — set to false to disable the extension without uninstalling."
        }
      }
    }
  },
  "scripts": {
    "compile": "tsc -p ./",
    "watch": "tsc -watch -p ./",
    "test": "vitest run",
    "test:watch": "vitest",
    "package": "vsce package",
    "vscode:prepublish": "npm run compile"
  },
  "devDependencies": {
    "@types/node": "^18.0.0",
    "@types/vscode": "^1.85.0",
    "@vscode/vsce": "^2.24.0",
    "typescript": "^5.3.0",
    "vitest": "^1.2.0"
  },
  "dependencies": {
    "jsonc-parser": "^3.2.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "module": "commonjs",
    "target": "ES2022",
    "outDir": "out",
    "lib": ["ES2022"],
    "sourceMap": true,
    "rootDir": "src",
    "strict": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "exclude": ["node_modules", "out", "test"]
}
```

- [ ] **Step 3: Create .gitignore**

```
node_modules/
out/
*.vsix
.vscode-test/
```

- [ ] **Step 4: Create .vscodeignore**

```
.vscode/**
.vscode-test/**
src/**
test/**
out/test/**
**/*.map
**/*.ts
!out/**/*.js
.gitignore
.eslintrc*
tsconfig.json
vitest.config.ts
```

- [ ] **Step 5: Create vitest.config.ts**

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    environment: "node",
  },
});
```

- [ ] **Step 6: Create README.md skeleton**

```markdown
# Lazer Config Linter (VS Code Extension)

Inline diagnostics for pyth-lazer governance proposal `after.json` files. Runs the Python config linter on save and surfaces all 26 lint rules as VS Code diagnostics.

## Install

1. Download the latest `lazer-config-linter-<version>.vsix` from the [GitHub release page](https://github.com/pyth-network/integration-benchmarking/releases?q=vscode-extension).
2. Install:
   - Command line: `code --install-extension lazer-config-linter-<version>.vsix`
   - Or in VS Code: `Extensions: Install from VSIX...` command palette action.

## Requirements

- Python 3.x on `PATH` (or set `lazerConfigLinter.pythonPath` to the interpreter).
- The `config_linter.py` source is auto-detected by walking up from the saved file. Override with `lazerConfigLinter.linterPath` for non-standard layouts.

## Activation

The extension activates only on files matching `<date>-T<time>-<slug>/after.json` — the proposal-directory pattern used in `pyth-lazer-governance` and `pyth-lazer-staging-governance`. Other JSON files are silently ignored.

## Configuration

| Setting                        | Default     | Description                                                    |
| ------------------------------ | ----------- | -------------------------------------------------------------- |
| `lazerConfigLinter.pythonPath` | `"python3"` | Python interpreter path.                                       |
| `lazerConfigLinter.linterPath` | `null`      | Explicit `config_linter.py` path. `null` triggers auto-detect. |
| `lazerConfigLinter.timeout`    | `5000`      | Subprocess kill timeout (ms).                                  |
| `lazerConfigLinter.lintOnSave` | `true`      | Master switch.                                                 |

## Behavior

On save of a proposal `after.json`, the extension:

1. Auto-detects the linter location (walks up looking for `tools/config-linter/config_linter.py`).
2. Detects sibling `before.json` (passed as `--baseline` if present, otherwise `--no-baseline`).
3. Spawns `python3 config_linter.py --config <file> ... --format json`.
4. Parses the linter's JSON output and shows each finding as an inline diagnostic anchored to the offending feed or publisher.

Failures (Python missing, linter missing, subprocess crash, timeout) appear as a single line-0 diagnostic — never silent.
```

- [ ] **Step 7: Create the placeholder src/extension.ts**

```typescript
import * as vscode from "vscode";

export function activate(_context: vscode.ExtensionContext): void {
  // Wired up in a later task.
}

export function deactivate(): void {
  // Disposables clean up via context.subscriptions.
}
```

- [ ] **Step 8: Install dependencies and verify compile**

Run from `tools/vscode-extension/`:

```bash
npm install
npm run compile
```

Expected: `npm install` completes without errors. `npm run compile` produces `out/extension.js` with no TypeScript errors.

- [ ] **Step 9: Commit**

```bash
git add tools/vscode-extension/package.json tools/vscode-extension/tsconfig.json tools/vscode-extension/.gitignore tools/vscode-extension/.vscodeignore tools/vscode-extension/vitest.config.ts tools/vscode-extension/README.md tools/vscode-extension/src/extension.ts
git commit -m "feat(vscode): scaffold extension package"
```

Note: do NOT commit `node_modules/` or `out/` (covered by `.gitignore`).

---

## Task 2: Define shared types

**Files:**

- Create: `tools/vscode-extension/src/types.ts`

- [ ] **Step 1: Create src/types.ts**

```typescript
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
```

- [ ] **Step 2: Verify it compiles**

Run: `npm run compile`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add tools/vscode-extension/src/types.ts
git commit -m "feat(vscode): add shared types for findings and locator output"
```

---

## Task 3: Locator — feed match (TDD)

**Files:**

- Create: `tools/vscode-extension/test/fixtures/one-feed.json`
- Create: `tools/vscode-extension/test/locator.test.ts`
- Create: `tools/vscode-extension/src/locator.ts`

**Goal:** First locator test — when a finding has `feed_id` set and a matching feed exists, return the offset range of that feed's `feedId` value.

- [ ] **Step 1: Create the fixture**

`tools/vscode-extension/test/fixtures/one-feed.json`:

```json
{
  "feeds": [
    {
      "feedId": 327,
      "symbol": "FX.EURUSD/USD",
      "state": "STABLE",
      "kind": "PRICE",
      "metadata": { "asset_type": "fx" },
      "allowedPublisherIds": [1, 2],
      "minPublishers": 1
    }
  ],
  "publishers": [
    { "publisherId": 1, "name": "p1", "keyType": "PRODUCTION" },
    { "publisherId": 2, "name": "p2", "keyType": "PRODUCTION" }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`tools/vscode-extension/test/locator.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { locateFinding } from "../src/locator";
import { Finding } from "../src/types";

const FIXTURE_DIR = join(__dirname, "fixtures");
const loadFixture = (name: string) =>
  readFileSync(join(FIXTURE_DIR, name), "utf8");

describe("locateFinding", () => {
  it("anchors a feed-keyed finding to the matching feedId value", () => {
    const text = loadFixture("one-feed.json");
    const finding: Finding = {
      rule_id: "E001",
      severity: "ERROR",
      message: "feedId 327 is duplicated",
      feed_id: 327,
      symbol: null,
    };
    const range = locateFinding(text, finding);
    // The feedId value "327" appears once in the fixture.
    const idx = text.indexOf("327");
    expect(range.startOffset).toBe(idx);
    expect(range.endOffset).toBe(idx + "327".length);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test`
Expected: FAIL — `Cannot find module '../src/locator'` (locator.ts doesn't exist yet).

- [ ] **Step 4: Implement minimal locator**

`tools/vscode-extension/src/locator.ts`:

```typescript
import { findNodeAtLocation, Node, parseTree } from "jsonc-parser";
import { Finding, OffsetRange } from "./types";

const FALLBACK: OffsetRange = { startOffset: 0, endOffset: 1 };

export function locateFinding(text: string, finding: Finding): OffsetRange {
  const tree = parseTree(text);
  if (!tree) return FALLBACK;

  // Default: match feeds[*].feedId == finding.feed_id
  if (finding.feed_id != null) {
    const node = findInArrayByProperty(
      tree,
      "feeds",
      "feedId",
      finding.feed_id,
    );
    if (node) return toRange(node);
  }
  return FALLBACK;
}

function findInArrayByProperty(
  tree: Node,
  arrayPath: string,
  propertyName: string,
  propertyValue: number | string,
): Node | null {
  const arrayNode = findNodeAtLocation(tree, [arrayPath]);
  if (!arrayNode || arrayNode.type !== "array" || !arrayNode.children) {
    return null;
  }
  for (let i = 0; i < arrayNode.children.length; i++) {
    const propNode = findNodeAtLocation(arrayNode, [i, propertyName]);
    if (propNode && propNode.value === propertyValue) {
      return propNode;
    }
  }
  return null;
}

function toRange(node: Node): OffsetRange {
  return { startOffset: node.offset, endOffset: node.offset + node.length };
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test`
Expected: PASS — 1 test, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add tools/vscode-extension/test/fixtures/one-feed.json tools/vscode-extension/test/locator.test.ts tools/vscode-extension/src/locator.ts
git commit -m "feat(vscode): locator anchors feed-keyed findings to feedId value"
```

---

## Task 4: Locator — E017 (duplicate publisherId)

**Files:**

- Create: `tools/vscode-extension/test/fixtures/one-publisher.json`
- Modify: `tools/vscode-extension/test/locator.test.ts`
- Modify: `tools/vscode-extension/src/locator.ts`

**Background:** E017's `feed_id` slot holds the duplicated publisherId, by linter convention (`lib/config_lint.py:1019`). The locator must recognize this and look up `publishers[*].publisherId` instead of `feeds[*].feedId`.

- [ ] **Step 1: Create the publisher fixture**

`tools/vscode-extension/test/fixtures/one-publisher.json`:

```json
{
  "feeds": [],
  "publishers": [
    { "publisherId": 55, "name": "AcmeMM", "keyType": "PRODUCTION" }
  ]
}
```

- [ ] **Step 2: Add a failing test**

Append to `tools/vscode-extension/test/locator.test.ts`:

```typescript
it("anchors E017 finding to the matching publishers[*].publisherId value", () => {
  const text = loadFixture("one-publisher.json");
  const finding: Finding = {
    rule_id: "E017",
    severity: "ERROR",
    message: "publisherId 55 is duplicated",
    feed_id: 55, // E017 convention: feed_id slot holds the publisherId
    symbol: null,
  };
  const range = locateFinding(text, finding);
  const idx = text.indexOf("55");
  expect(range.startOffset).toBe(idx);
  expect(range.endOffset).toBe(idx + "55".length);
});
```

- [ ] **Step 3: Run tests to verify it fails**

Run: `npm test`
Expected: FAIL — the locator currently returns the FALLBACK because the lookup table doesn't yet branch on `rule_id === 'E017'`.

- [ ] **Step 4: Extend locator with E017 branch**

In `tools/vscode-extension/src/locator.ts`, replace the body of `locateFinding` with:

```typescript
export function locateFinding(text: string, finding: Finding): OffsetRange {
  const tree = parseTree(text);
  if (!tree) return FALLBACK;

  // E017: feed_id slot holds the duplicated publisherId.
  if (finding.rule_id === "E017" && finding.feed_id != null) {
    const node = findInArrayByProperty(
      tree,
      "publishers",
      "publisherId",
      finding.feed_id,
    );
    if (node) return toRange(node);
    return FALLBACK;
  }

  // Default: match feeds[*].feedId == finding.feed_id
  if (finding.feed_id != null) {
    const node = findInArrayByProperty(
      tree,
      "feeds",
      "feedId",
      finding.feed_id,
    );
    if (node) return toRange(node);
  }
  return FALLBACK;
}
```

- [ ] **Step 5: Run tests to verify both pass**

Run: `npm test`
Expected: PASS — 2 tests, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add tools/vscode-extension/test/fixtures/one-publisher.json tools/vscode-extension/test/locator.test.ts tools/vscode-extension/src/locator.ts
git commit -m "feat(vscode): locator anchors E017 findings to publishers[*].publisherId"
```

---

## Task 5: Locator — E018 (duplicate publisher name)

**Files:**

- Modify: `tools/vscode-extension/test/locator.test.ts`
- Modify: `tools/vscode-extension/src/locator.ts`

**Background:** E018's `symbol` slot holds the duplicated publisher name (`lib/config_lint.py:1042`). The locator must look up `publishers[*].name` matching `finding.symbol`.

- [ ] **Step 1: Add the failing test**

Append to `tools/vscode-extension/test/locator.test.ts`:

```typescript
it("anchors E018 finding to the matching publishers[*].name value", () => {
  const text = loadFixture("one-publisher.json");
  const finding: Finding = {
    rule_id: "E018",
    severity: "ERROR",
    message: "publisher name 'AcmeMM' is duplicated",
    feed_id: null,
    symbol: "AcmeMM", // E018 convention: symbol slot holds the duplicated name
  };
  const range = locateFinding(text, finding);
  // The string "AcmeMM" appears once in the fixture (as the publisher's name value).
  const idx = text.indexOf('"AcmeMM"');
  expect(range.startOffset).toBe(idx);
  expect(range.endOffset).toBe(idx + '"AcmeMM"'.length);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL — the locator returns FALLBACK because there's no E018 branch.

- [ ] **Step 3: Add E018 branch to locator**

Insert into `locateFinding`, after the E017 branch:

```typescript
// E018: symbol slot holds the duplicated publisher name.
if (finding.rule_id === "E018" && finding.symbol != null) {
  const node = findInArrayByProperty(
    tree,
    "publishers",
    "name",
    finding.symbol,
  );
  if (node) return toRange(node);
  return FALLBACK;
}
```

- [ ] **Step 4: Run tests to verify all three pass**

Run: `npm test`
Expected: PASS — 3 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add tools/vscode-extension/test/locator.test.ts tools/vscode-extension/src/locator.ts
git commit -m "feat(vscode): locator anchors E018 findings to publishers[*].name"
```

---

## Task 6: Locator — unparseable JSON fallback

**Files:**

- Create: `tools/vscode-extension/test/fixtures/unparseable.json`
- Modify: `tools/vscode-extension/test/locator.test.ts`

**Goal:** When the document doesn't parse, the locator must not throw — return the line-0 fallback.

- [ ] **Step 1: Create the unparseable fixture**

`tools/vscode-extension/test/fixtures/unparseable.json`:

```
{ this is not valid JSON
```

(Invalid: missing braces, no quotes, no closing.)

- [ ] **Step 2: Add the failing test**

Append to `tools/vscode-extension/test/locator.test.ts`:

```typescript
it("returns the line-0 fallback when the document does not parse", () => {
  const text = loadFixture("unparseable.json");
  const finding: Finding = {
    rule_id: "E001",
    severity: "ERROR",
    message: "feedId 1 is duplicated",
    feed_id: 1,
    symbol: null,
  };
  const range = locateFinding(text, finding);
  expect(range).toEqual({ startOffset: 0, endOffset: 1 });
});
```

- [ ] **Step 3: Run test**

Run: `npm test`
Expected: This may already PASS if `parseTree` returns a partial tree even on malformed input, because the lookup falls through to FALLBACK when no match is found.

If it FAILS: investigate. The expected behavior is that `parseTree` either returns `undefined` or a partial tree where `feeds[]` doesn't exist, both of which fall through to FALLBACK in our existing code.

- [ ] **Step 4: If failing, ensure defensive guard**

If the test fails because `parseTree` returns a non-null but unusable tree, harden the lookup: ensure `findInArrayByProperty` returns `null` for missing array nodes (it already does — `if (!arrayNode || arrayNode.type !== 'array' || !arrayNode.children) return null;`).

If still failing, add an explicit guard at the top of `locateFinding`:

```typescript
const tree = parseTree(text);
if (!tree || tree.type !== "object") return FALLBACK;
```

- [ ] **Step 5: Run tests to verify all four pass**

Run: `npm test`
Expected: PASS — 4 tests, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add tools/vscode-extension/test/fixtures/unparseable.json tools/vscode-extension/test/locator.test.ts tools/vscode-extension/src/locator.ts
git commit -m "test(vscode): locator falls back to line 0 on unparseable JSON"
```

---

## Task 7: Locator — no-match fallback

**Files:**

- Modify: `tools/vscode-extension/test/locator.test.ts`

**Goal:** When the finding's identifier doesn't match anything in the document (e.g. `feed_id=999` but no such feed), return the line-0 fallback. Sanity test of the existing fallback behavior.

- [ ] **Step 1: Add the failing test**

Append to `tools/vscode-extension/test/locator.test.ts`:

```typescript
it("returns the line-0 fallback when no matching entry exists", () => {
  const text = loadFixture("one-feed.json");
  const finding: Finding = {
    rule_id: "E001",
    severity: "ERROR",
    message: "feedId 999 is duplicated",
    feed_id: 999, // not present in fixture (only 327)
    symbol: null,
  };
  const range = locateFinding(text, finding);
  expect(range).toEqual({ startOffset: 0, endOffset: 1 });
});
```

- [ ] **Step 2: Run test**

Run: `npm test`
Expected: PASS — should already pass because `findInArrayByProperty` returns `null` and the locator returns FALLBACK.

- [ ] **Step 3: Commit**

```bash
git add tools/vscode-extension/test/locator.test.ts
git commit -m "test(vscode): locator no-match fallback sanity check"
```

---

## Task 8: Linter wrapper — happy path (mocked spawn)

**Files:**

- Create: `tools/vscode-extension/src/linter.ts`
- Create: `tools/vscode-extension/test/linter.test.ts`

**Goal:** A pure async function `runLinter(options): Promise<LinterResult>` that spawns the Python linter and parses its JSON output. Use vitest's `vi.mock` to stub `child_process.spawn`.

- [ ] **Step 1: Write the failing test**

`tools/vscode-extension/test/linter.test.ts`:

```typescript
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL — `Cannot find module '../src/linter'`.

- [ ] **Step 3: Implement minimal runLinter**

`tools/vscode-extension/src/linter.ts`:

```typescript
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test`
Expected: PASS — 5 tests total (4 locator + 1 linter), 0 failures.

- [ ] **Step 5: Commit**

```bash
git add tools/vscode-extension/src/linter.ts tools/vscode-extension/test/linter.test.ts
git commit -m "feat(vscode): linter wrapper parses JSON output on success"
```

---

## Task 9: Linter wrapper — error paths

**Files:**

- Modify: `tools/vscode-extension/test/linter.test.ts`

**Goal:** Add a test for the non-zero-exit-with-non-JSON-output case (linter crashed). The implementation already handles this; this task adds the regression test.

- [ ] **Step 1: Add the failing test**

Append to `tools/vscode-extension/test/linter.test.ts`:

```typescript
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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `npm test`
Expected: PASS — 7 tests total (4 locator + 3 linter), 0 failures. (The implementation already handles these cases.)

- [ ] **Step 3: Commit**

```bash
git add tools/vscode-extension/test/linter.test.ts
git commit -m "test(vscode): cover linter wrapper crash and python-not-found paths"
```

---

## Task 10: Config helper

**Files:**

- Create: `tools/vscode-extension/src/config.ts`

**Goal:** Thin typed wrapper around `vscode.workspace.getConfiguration`. No unit test (vscode-coupled and trivial; covered by smoke test).

- [ ] **Step 1: Create src/config.ts**

```typescript
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
```

- [ ] **Step 2: Verify it compiles**

Run: `npm run compile`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add tools/vscode-extension/src/config.ts
git commit -m "feat(vscode): config helper wrapping workspace settings"
```

---

## Task 11: Diagnostics conversion

**Files:**

- Create: `tools/vscode-extension/src/diagnostics.ts`

**Goal:** Convert `Finding[]` plus a `vscode.TextDocument` into `vscode.Diagnostic[]` using the locator. Vscode-coupled; covered by smoke test.

- [ ] **Step 1: Create src/diagnostics.ts**

```typescript
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
```

- [ ] **Step 2: Verify it compiles**

Run: `npm run compile`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add tools/vscode-extension/src/diagnostics.ts
git commit -m "feat(vscode): convert findings and errors to vscode.Diagnostic"
```

---

## Task 12: Linter path resolver

**Files:**

- Create: `tools/vscode-extension/src/resolver.ts`

**Goal:** Walk-up auto-detection of `tools/config-linter/config_linter.py`, with workspace caching. Pure module (uses `node:fs` / `node:path`, no vscode).

- [ ] **Step 1: Create src/resolver.ts**

```typescript
import { existsSync } from "node:fs";
import { dirname, join, parse, sep } from "node:path";

const LINTER_REL = join("tools", "config-linter", "config_linter.py");

const cache = new Map<string, string | null>();

/**
 * Walk up from `startDir` looking for a sibling `tools/config-linter/config_linter.py`.
 * Stops at `workspaceRoot` (inclusive) or the filesystem root, whichever comes first.
 *
 * Returns the absolute linter path or null if not found. Cached per workspaceRoot.
 */
export function resolveLinterPath(
  startDir: string,
  workspaceRoot: string,
): string | null {
  const cached = cache.get(workspaceRoot);
  if (cached !== undefined) return cached;

  const fsRoot = parse(startDir).root;
  let current = startDir;
  // Walk up from startDir up to workspaceRoot inclusive.
  while (true) {
    const candidate = join(current, LINTER_REL);
    if (existsSync(candidate)) {
      cache.set(workspaceRoot, candidate);
      return candidate;
    }
    if (current === workspaceRoot || current === fsRoot) break;
    const parent = dirname(current);
    if (parent === current) break; // safety
    current = parent;
  }

  cache.set(workspaceRoot, null);
  return null;
}

/** For tests: clear the cache. */
export function clearResolverCache(): void {
  cache.clear();
}
```

- [ ] **Step 2: Verify it compiles**

Run: `npm run compile`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add tools/vscode-extension/src/resolver.ts
git commit -m "feat(vscode): walk-up resolver for config_linter.py with caching"
```

---

## Task 13: Extension entry point

**Files:**

- Modify: `tools/vscode-extension/src/extension.ts`

**Goal:** Wire everything together. On `onDidSaveTextDocument`: gate on the proposal-path regex, resolve the linter, run it, convert findings to diagnostics, update the collection.

- [ ] **Step 1: Replace src/extension.ts**

```typescript
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
  const linterPath =
    cfg.linterPath && existsSync(cfg.linterPath)
      ? cfg.linterPath
      : resolveLinterPath(dirname(fsPath), workspaceRoot);

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
```

- [ ] **Step 2: Verify it compiles**

Run: `npm run compile`
Expected: no errors. `out/extension.js` produced.

- [ ] **Step 3: Commit**

```bash
git add tools/vscode-extension/src/extension.ts
git commit -m "feat(vscode): wire activate(), save handler, and diagnostic collection"
```

---

## Task 14: Manual smoke test

**Files:** None (manual verification).

**Goal:** Confirm the extension works end-to-end against a real proposal in `pyth-lazer-staging-governance`.

- [ ] **Step 1: Build the extension locally**

Run from `tools/vscode-extension/`:

```bash
npm run compile
```

Expected: `out/extension.js` exists, no TS errors.

- [ ] **Step 2: Launch the extension in VS Code's debug host**

Open `tools/vscode-extension/` as a folder in VS Code, then press F5 (or Run → Start Debugging). This opens a new "Extension Development Host" window with the extension loaded.

- [ ] **Step 3: Open a real proposal in the dev host**

In the new window, open the `pyth-lazer-staging-governance` repo as a workspace. Navigate to any proposal directory's `after.json` (e.g. `2026-04-28-T162830-linter-testing-e-001-e-018/after.json`).

- [ ] **Step 4: Introduce a known error and save**

In the opened `after.json`, find a feed and duplicate its `feedId` value into another existing feed (so two feeds share one feedId). Save the file.

Expected: Within ~1 second, an inline red squiggle appears on at least one of the duplicate `feedId` values. The Problems panel shows an `E001` diagnostic with the message "feedId N is duplicated (...)".

- [ ] **Step 5: Revert and confirm the squiggle clears**

Undo the duplicate. Save.

Expected: The squiggle disappears within ~1 second.

- [ ] **Step 6: Test the no-Python failure path**

In VS Code settings, set `Lazer Config Linter: Python Path` to `nonexistent-python-binary`. Save the file again.

Expected: A line-0 diagnostic appears with the message starting "Python 3 not found." All other diagnostics are cleared (replaced by this single one).

Restore `pythonPath` to `python3`. Save again. Expected: normal diagnostics return.

- [ ] **Step 7: Test that non-proposal files are ignored**

Open a `README.md` or any other non-`after.json` file in the workspace. Save it.

Expected: No diagnostics added. No error in the Output panel.

- [ ] **Step 8: Document the smoke-test results**

If all six checks above passed, no further action needed; proceed to packaging. If any failed, debug and re-run.

---

## Task 15: Package and tag a release

**Files:** None (release artifact only).

**Goal:** Produce `lazer-config-linter-0.1.0.vsix` and attach it to a GitHub Release.

- [ ] **Step 1: Verify the package builds**

Run from `tools/vscode-extension/`:

```bash
npm run package
```

Expected: A file named `lazer-config-linter-0.1.0.vsix` is produced in the current directory. `vsce` may emit warnings about the missing LICENSE file or icon — those are non-blocking for v1.

- [ ] **Step 2: Smoke-test the packaged .vsix in a clean VS Code instance**

```bash
code --install-extension lazer-config-linter-0.1.0.vsix
```

Open `pyth-lazer-staging-governance` in VS Code, repeat smoke-test steps 3–4 from Task 14.

Expected: Same behavior as the development-host smoke test.

- [ ] **Step 3: Uninstall the dev install (optional, to avoid two copies)**

```bash
code --uninstall-extension pyth-network.lazer-config-linter
```

- [ ] **Step 4: Merge the spec/plan branches and the implementation branches**

Open PRs for:

- `docs/vscode-extension-spec` (already exists; the spec doc)
- The implementation branch (whichever name was used during execution; likely a feature branch off `main` containing all of Tasks 1–13)

Merge them in the order: spec → implementation.

- [ ] **Step 5: Cut a GitHub Release**

```bash
gh release create vscode-extension-v0.1.0 \
  --title "VS Code Extension v0.1.0" \
  --notes "Initial release. Inline diagnostics for proposal after.json files via the Python config linter. See tools/vscode-extension/README.md for install instructions." \
  lazer-config-linter-0.1.0.vsix
```

Expected: A new release is visible at `https://github.com/pyth-network/integration-benchmarking/releases/tag/vscode-extension-v0.1.0` with the `.vsix` attached.

- [ ] **Step 6: Update CONTRIBUTING.md in the governance repos**

In each of `pyth-lazer-governance` and `pyth-lazer-staging-governance`, add a short section to `CONTRIBUTING.md` (or create one if missing):

````markdown
## Editor Integration

For inline lint feedback while editing proposal `after.json` files in VS Code, install the [Lazer Config Linter extension](https://github.com/pyth-network/integration-benchmarking/releases?q=vscode-extension):

```bash
code --install-extension lazer-config-linter-<version>.vsix
```
````

Saves of `<proposal-dir>/after.json` will display inline diagnostics from the same linter that runs in CI. See [tools/vscode-extension/README.md](https://github.com/pyth-network/integration-benchmarking/blob/main/tools/vscode-extension/README.md) for full configuration.

```

Open separate PRs in each governance repo for that doc change.

- [ ] **Step 7: Final commit / tag confirmation**

Verify the release page shows the `.vsix` and the install command in CONTRIBUTING.md works for a teammate.

---

## Self-Review

**Spec coverage:**

- Goals (inline diagnostics on save, all 26 rules, anchored to feeds/publishers, never silent failure, no linter changes) → covered by Tasks 3–13 (locator, linter wrapper, diagnostics, extension entry).
- Non-goals (github.dev, linter rewrite, marketplace v1, sub-feed precision) → respected; not implemented.
- Architecture (TS extension, subprocess per save, no LSP) → matches Tasks 8 and 13.
- File layout → matches Task 1, 10, 11, 12, 13.
- Activation scope (proposal-dir regex, normalised slashes) → Task 13 step 1.
- Data flow (path gate → resolver → before.json detect → spawn → parse → diagnostics) → Task 13 step 1.
- Range mapping (jsonc-parser, four cases) → Tasks 3, 4, 5, 6, 7.
- Configuration (4 settings) → Tasks 1 and 10.
- Error handling (5 named failure modes, line-0 diagnostic) → Task 11 (`formatError`) and Task 8/9 (`LinterError` cases).
- Distribution (vsce package + GitHub Release + README + CONTRIBUTING) → Task 1 step 6 (README), Task 15 (release + CONTRIBUTING).
- Testing (5 locator + 2 linter + manual smoke) → Tasks 3–7 (5 locator), Tasks 8–9 (2 linter), Task 14 (smoke).
- Implementation hygiene (TS strict, spawn-not-exec, Disposables) → Task 1 (tsconfig), Task 8 (spawn), Task 13 (context.subscriptions).

No uncovered spec requirements.

**Placeholder scan:** No "TBD", "TODO", "implement later", or "similar to Task N" references. Each task has full code or full instructions.

**Type consistency check:**

- `Finding`: defined in `types.ts` (Task 2), used in `locator.ts` (Tasks 3–7), `linter.ts` (Task 8), `diagnostics.ts` (Task 11). All references match: `{rule_id, severity, message, feed_id, symbol}`.
- `OffsetRange`: defined in `types.ts`, returned by `locator.ts`, consumed by `diagnostics.ts` via `document.positionAt`. Consistent.
- `LinterError`: defined in `types.ts`, produced by `linter.ts`, consumed by `diagnostics.ts:errorToDiagnostic`. All five `kind` values (`python_not_found`, `linter_not_found`, `crashed`, `timeout`, `parse_error`) are produced (Task 8/9) and consumed (Task 11) — match.
- `LinterOptions`: declared in `linter.ts` (Task 8), called from `extension.ts` with matching property names (Task 13).
- `ExtensionConfig`: declared in `config.ts` (Task 10), consumed in `extension.ts` (Task 13). Property names match.
- `resolveLinterPath`: declared in Task 12, called in Task 13. Signature matches.

No type drift.

---
```
