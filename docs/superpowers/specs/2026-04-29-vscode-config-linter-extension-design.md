# VS Code Extension for the Config Linter — Design

**Date:** 2026-04-29
**Status:** Design approved, ready for implementation plan
**Canonical home:** `pyth-network/integration-benchmarking/tools/vscode-extension/`

## Background

Configurations in `pyth-lazer-governance` and `pyth-lazer-staging-governance` are validated by the Python config linter (in `tools/config-linter/`) only after a PR is pushed. People editing `after.json` get no immediate feedback about structural mistakes, missing publishers, or schedule inconsistencies — they see them several minutes later in the GitHub Actions logs.

This spec describes a VS Code extension that runs the existing linter on save and surfaces findings as inline diagnostics, giving authors immediate per-file feedback without waiting for CI.

## Goals

- A VS Code user editing `<proposal-dir>/after.json` sees inline diagnostics within ~1 second of saving the file.
- All 26 linter rules are surfaced (no coverage loss vs CI).
- Diagnostics anchor to the right feed or publisher entry, not always line 0.
- Failure modes (missing Python, missing linter, subprocess crash) produce a single visible diagnostic — never silent no-ops.
- The Python linter requires no changes. Linter and extension are versioned independently.

## Non-Goals

- **github.dev (browser editor) support.** github.dev cannot execute Python; the alternatives (rewriting the linter in TypeScript, embedding Pyodide) are not justified for the partial coverage they'd produce. Browser-based editing continues to rely on post-push CI.
- **Linter rewrite or partial port.** The Python linter remains the single source of truth. The extension is a thin wrapper around the existing CLI.
- **Marketplace publication (v1).** Distribution is via `.vsix` from a GitHub Release. Open VSX/marketplace is a v2 follow-up if onboarding friction warrants it.
- **Sub-feed precision (v1).** Findings anchor to the feed or publisher entry; session-level / corp-action-index precision is deferred to v2 (would require linter changes).

## Architecture

A single VS Code extension written in TypeScript, distributed as a `.vsix` package. Activates on JSON files matching the proposal-directory regex; spawns the existing Python linter as a subprocess on save; converts the linter's JSON output to `vscode.Diagnostic` objects.

No persistent process, no Language Server Protocol, no daemon. Each save runs an independent subprocess. State held by the extension is a singleton `DiagnosticCollection` and a per-workspace cache of the resolved linter path.

### File layout

```
pyth-network/integration-benchmarking/
└── tools/
    ├── config-linter/                    # existing — unchanged
    └── vscode-extension/                 # new
        ├── package.json
        ├── tsconfig.json
        ├── src/
        │   ├── extension.ts              # activate(), deactivate(), event wiring
        │   ├── linter.ts                 # spawn subprocess, parse JSON output
        │   ├── locator.ts                # JSON-path → range lookup (jsonc-parser)
        │   ├── diagnostics.ts            # finding → vscode.Diagnostic
        │   └── config.ts                 # workspace settings access
        ├── test/
        │   └── locator.test.ts           # ~5 fixture cases
        ├── README.md                     # install + usage
        └── .vscodeignore
```

Total ~400 lines TypeScript plus tests.

## Activation Scope

`package.json` declares `activationEvents: ["onLanguage:json"]` — the extension loads when any JSON file is opened. Inside `onDidSaveTextDocument` it gates on a path regex applied to the file's `fsPath` after normalising backslashes to forward slashes (cross-platform):

```
\d{4}-\d{2}-\d{2}-T\d{6}-[a-z0-9-]+/after\.json$
```

Files outside this pattern (root configs, the linter's own test fixtures, `before.json`, etc.) are silently ignored.

## Data Flow on Save

1. User saves a proposal `after.json`.
2. `onDidSaveTextDocument` fires.
3. Path regex check; non-matching files exit early.
4. Resolve linter location: walk up from the saved file's directory looking for a sibling `tools/config-linter/config_linter.py`, stopping at the workspace root or filesystem root, whichever comes first. Result cached per workspace until VS Code reload.
5. Check for sibling `before.json`. If present → `--baseline before.json`. Otherwise → `--no-baseline`.
6. If a previous subprocess is still running for this same file, send `SIGKILL` before starting the new one. (Save-spam protection.)
7. Spawn:
   ```
   python3 <linter>/config_linter.py --config <file>
       [--baseline <before.json> | --no-baseline] --format json
   ```
   with a 5-second timeout (configurable).
8. On exit code 0/1, parse stdout as JSON (a flat array of finding objects).
9. For each finding, compute a `vscode.Range` via the locator (next section).
10. Convert findings to `vscode.Diagnostic` (severity ERROR → `Error`, WARNING → `Warning`).
11. Replace the file's entry in a singleton `DiagnosticCollection`. Old diagnostics from the previous save vanish atomically.

The linter exits with code 0 (no errors) or 1 (errors, baseline file missing, or malformed input). Both are valid; only spawn-level failures (`ENOENT`, timeout, malformed stdout) trigger error-handler diagnostics.

## Range Mapping (Locator)

The linter emits findings keyed on `(rule_id, feed_id, symbol)` with no file positions. The locator maps each finding to a range using Microsoft's `jsonc-parser` library — the same parser VS Code uses for `settings.json` — which returns an AST where every node carries `offset` and `length`.

| Finding shape                                  | Anchor target                                                                                   |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `feed_id` set, standard rule (E001–E016)       | `feeds[*].feedId` value of the matching feed                                                    |
| `rule_id == "E017"` (duplicate publisherId)    | `publishers[*].publisherId` value — `feed_id` slot holds the duplicated id by linter convention |
| `rule_id == "E018"` (duplicate publisher name) | `publishers[*].name` value — `symbol` slot holds the duplicated name                            |
| No match (defensive)                           | Line 0, range length 1                                                                          |

The locator never throws. Worst case: diagnostics land at line 0 with the full message visible in the Problems panel — the user still sees the finding.

**Sub-feed precision (deferred to v2):** Session-level findings (E003 session, E004 session, E010 verbatim-dup) and corp-action findings (E015 with `corporateActions[i]` in message) currently anchor to the parent feed because the linter does not emit session or array index in the `LintFinding` struct. To anchor to a specific session or corp-action would require extending the linter. Not blocking for v1.

**Performance:** `parseTree` is O(file size); a 50k-line `after.json` parses in ~50ms. Lookups across `feeds[*]` are O(N) per finding — for 3000 feeds × 50 findings, sub-millisecond total. No memoisation needed.

## Configuration

Workspace/user settings (registered in `package.json` under `contributes.configuration`):

```json
{
  "lazerConfigLinter.pythonPath": "python3",
  "lazerConfigLinter.linterPath": null,
  "lazerConfigLinter.timeout": 5000,
  "lazerConfigLinter.lintOnSave": true
}
```

| Setting      | Default     | Meaning                                                                        |
| ------------ | ----------- | ------------------------------------------------------------------------------ |
| `pythonPath` | `"python3"` | Python interpreter. Use absolute path if Python isn't on `PATH`.               |
| `linterPath` | `null`      | Explicit `config_linter.py` path. `null` triggers walk-up auto-detect.         |
| `timeout`    | `5000`      | Subprocess kill timeout in milliseconds.                                       |
| `lintOnSave` | `true`      | Master switch. Setting to `false` disables the extension without uninstalling. |

## Error Handling

Every failure mode produces a single line-0 diagnostic — never a silent no-op. Old diagnostics are replaced; the user always sees the most recent state.

| Failure                                             | User-visible diagnostic                                                                                        |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Python binary not found (`ENOENT`)                  | "Python 3 not found. Configure `lazerConfigLinter.pythonPath` or install Python 3.x."                          |
| Linter file missing                                 | "Could not locate `config_linter.py`. Set `lazerConfigLinter.linterPath` if your repo layout is non-standard." |
| Subprocess non-zero exit (other than 1) and no JSON | "Linter crashed: <first line of stderr>"                                                                       |
| Subprocess exceeds timeout                          | "Linter timed out after <N>s. File may be too large."                                                          |
| JSON parse failure on stdout                        | "Couldn't parse linter output: <first 200 chars>"                                                              |

Implementation: `child_process.spawn` (not `exec`) — no shell injection, stdout/stderr captured separately, stdout parsed as JSON only after exit-code inspection.

## Distribution (v1)

- **Build:** `cd tools/vscode-extension && npm install && npm run package` → produces `lazer-config-linter-<version>.vsix`.
- **Release:** GitHub Release on `pyth-network/integration-benchmarking` tagged `vscode-extension-v0.1.0`. `.vsix` attached as a release asset.
- **Install (user-facing):** documented in `tools/vscode-extension/README.md`. Either:
  - Download `.vsix`, run `code --install-extension <file>.vsix`, or
  - In VS Code: `Extensions: Install from VSIX...` command.
- **Onboarding:** `CONTRIBUTING.md` in both governance repos points to the release URL with a one-line install snippet.
- **Versioning:** extension version independent of linter version. Linter rule additions don't force extension republish.

## Out of Scope / v2 Follow-ups

- **Open VSX or VS Code Marketplace publication.** Would unlock the workspace `.vscode/extensions.json` "recommended extensions" prompt for new contributors. Polish, not blocking.
- **Auto-update mechanism.** v1 users pull new versions manually.
- **Sub-feed precision** (session-level, corp-action-index). Requires extending the linter's `LintFinding` struct.
- **Lint on type with debounce.** v1 lints on save only — simpler, predictable, sufficient given linter latency is ~200ms.

## Testing

**Unit tests (vitest)** for `locator.ts`: five fixture-based cases.

| Case                      | Fixture                                                               | Expected                      |
| ------------------------- | --------------------------------------------------------------------- | ----------------------------- |
| Feed match                | Doc with feeds[0].feedId=327 + finding(E001, feed_id=327)             | Range covers `327` value      |
| E017 publisher match      | Doc with publishers[0].publisherId=55 + finding(E017, feed_id=55)     | Range covers `55` value       |
| E018 publisher name match | Doc with publishers[0].name="AcmeMM" + finding(E018, symbol="AcmeMM") | Range covers `"AcmeMM"` value |
| Unparseable JSON          | Doc with trailing comma + any finding                                 | Range = line 0 length 1       |
| No match                  | Doc with feeds[0].feedId=1 + finding(E001, feed_id=999)               | Range = line 0 length 1       |

Plus 1–2 cases for `linter.ts` mocking subprocess output (happy path + non-zero-exit error path). ~150 lines total.

**Integration tests (`@vscode/test-electron`)** — three cases. Optional for v1; defer if budget tight.

| Case         | Setup                                             | Expected                                                 |
| ------------ | ------------------------------------------------- | -------------------------------------------------------- |
| Happy path   | Open fixture proposal with 1 known E001 → save    | Diagnostic appears at expected feed range                |
| Failure path | Configure `pythonPath` to a missing binary → save | Single line-0 diagnostic with "Python not found" message |
| No-op path   | Open `README.md` (non-proposal) → save            | No diagnostics added                                     |

**Manual smoke test:** open a real proposal in `pyth-lazer-staging-governance`, intentionally introduce an E001 duplicate, save, confirm the squiggle lands on the offending feed.

## Implementation Hygiene

- TypeScript strict mode
- ESLint + Prettier
- Node.js 18+ target (VS Code's runtime)
- All `Disposable` instances registered to `context.subscriptions` for clean teardown in `deactivate()`
- `child_process.spawn` over `exec` (no shell, separate stdout/stderr)
- `vscode.workspace.onDidSaveTextDocument` (not `onDidChangeTextDocument`) — save is the trigger

## Open Questions

None at design time. v1 scope is bounded; v2 follow-ups are listed and explicitly out of scope.
