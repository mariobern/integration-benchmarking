# Vendor the Lazer Config Linter VS Code extension into governance repos

**Date:** 2026-04-29
**Status:** Design — pending user review
**Related:** `tools/vscode-extension/`, `tools/config-linter/`, `pyth-network/pyth-lazer-governance` PR #626

## Problem

The Lazer Config Linter VS Code extension lives in `pyth-network/integration-benchmarking` (this repo) at `tools/vscode-extension/`. The team that actually edits governance proposals — the people the extension exists for — works in `pyth-network/pyth-lazer-governance` and `pyth-network/pyth-lazer-staging-governance`. Today, installing the extension means navigating to this repo's GitHub releases and downloading a `.vsix`. That cross-repo step is friction we want to remove.

## Goal

Make the extension installable from inside each governance repo, with a single shell command, with no dependency on this repo at install time.

## Non-goals

- Publishing to the public VS Code Marketplace or Open VSX.
- Auto-install on clone (post-clone hooks, npm bootstrap, etc.).
- Vendoring the TypeScript source. Source stays in this repo.
- A CI check in governance repos that the `.vsix` is present.
- Automated cross-repo sync of the `.vsix`. Manual sync only, until it's painful.

## Background — what's already in place

Both governance repos already host the Python linter that the extension wraps:

- **`pyth-lazer-staging-governance`**: `tools/config-linter/{config_linter.py, lib/, tests/, README.md, .gitignore}` is on `main` (PR #66 merged, PR #71 sync'd).
- **`pyth-lazer-governance`**: same files arrive via PR #626 (currently open). Once merged, both repos satisfy the extension's walk-up auto-detection (`tools/config-linter/config_linter.py`).

That means the only remaining distribution problem is the extension binary itself.

## Design

### Repo layout

In each governance repo, add one folder containing two files:

```
tools/
  vscode-extension/
    lazer-config-linter.vsix      ← prebuilt artifact (~50 KB)
    README.md                     ← install + behavior notes
```

The path `tools/vscode-extension/` mirrors this repo's layout and sits next to `tools/config-linter/`, keeping all "tools" coherent in one place.

### Filename — drop the version suffix

Upstream `npm run package` produces a versioned filename (`lazer-config-linter-0.1.0.vsix`). When vendoring into governance repos, **rename to the unversioned `lazer-config-linter.vsix`**. Rationale:

- Install command stays stable across version bumps. Users `git pull` and re-run the same line.
- Avoids glob-expansion footguns on Windows / `cmd.exe`.
- Version is still recorded in the package metadata inside the `.vsix` and is visible via `code --list-extensions --show-versions`.

### Install command

Documented in `tools/vscode-extension/README.md` and referenced from the governance repo's top-level README:

```
code --install-extension --force tools/vscode-extension/lazer-config-linter.vsix
```

`--force` makes the command idempotent — safe to run no matter what version (if any) is currently installed, and safe to re-run after every `git pull`.

### Vendored README contents

`tools/vscode-extension/README.md` in each governance repo should be a short, governance-repo-specific file (not a copy of the full upstream README). It covers:

1. One-sentence "what this is".
2. The install command above, plus the `code` CLI prerequisite (and the macOS palette action `Shell Command: Install 'code' command in PATH`).
3. Activation pattern: extension activates on save of any `*/after.json` matching the proposal-directory naming convention; other JSON saves are silently ignored.
4. Python 3 prerequisite. Note that `tools/config-linter/config_linter.py` (already in this repo) is what the extension shells out to.
5. Pointer to the upstream source: `https://github.com/pyth-network/integration-benchmarking/tree/main/tools/vscode-extension`.
6. A `Last updated:` line bumped on each version sync.

The governance repo's top-level README gets one short paragraph linking to `tools/vscode-extension/README.md` so the install path is discoverable from the front door.

## Sync workflow (upstream → governance)

**Source of truth:** this repo (`integration-benchmarking-vscode-ext`), `tools/vscode-extension/`. Governance repos hold a copy of the latest released `.vsix` only.

### Initial vendoring (this task)

The existing `tools/vscode-extension/lazer-config-linter-0.1.0.vsix` is the artifact to vendor. No rebuild needed.

1. **PR against `pyth-lazer-governance`** — depends on #626 landing first (the extension can't run without `tools/config-linter/config_linter.py`). PR adds:
   - `tools/vscode-extension/lazer-config-linter.vsix` (renamed copy of `lazer-config-linter-0.1.0.vsix`)
   - `tools/vscode-extension/README.md`
   - One-paragraph pointer in the repo's top-level README
2. **PR against `pyth-lazer-staging-governance`** — same diff, no upstream-PR dependency (linter is already on `main`).

### Future updates

When the extension version bumps in this repo:

1. In this repo: bump `tools/vscode-extension/package.json` version, `npm run package`, merge to `main` (existing release process unchanged).
2. Open a PR in each governance repo replacing `tools/vscode-extension/lazer-config-linter.vsix` with the new build, and bump the `Last updated:` line in the vendored README.
3. Per-release effort: ~5 min for both PRs. Low frequency expected.

If sync ever becomes painful, an obvious next step is a GitHub Action in this repo that opens those PRs automatically on a release tag — but that's deferred.

## Edge cases & failure modes

| Scenario | Behavior | Notes |
|---|---|---|
| `code` CLI not on PATH | Shell error from the install command | README mentions the macOS palette action to install the CLI. |
| Python 3 missing | Extension surfaces a single line-0 diagnostic on the saved file | Already handled by the extension itself — never silent. |
| `config_linter.py` missing in workspace | Single line-0 diagnostic | Failure mode for an old governance commit (pre-#626 in `pyth-lazer-governance`). Tells the user exactly what's wrong. |
| Stale extension version installed | `--force` upgrades or downgrades to match the vendored `.vsix` | No manual `code --uninstall-extension` needed. |
| User re-runs install after `git pull` | Idempotent — same one-liner works | This is why we use `--force`. |

## Verification

No automated tests for the vendoring PRs — this is file movement, not code. Manual smoke test after each governance PR merges:

1. Clone the governance repo fresh.
2. Run the install one-liner.
3. Open a real proposal `after.json`, introduce a known error (e.g. duplicate `feedId`), save.
4. Confirm the diagnostic shows up inline anchored to the offending feed/publisher.
5. Confirm `code --list-extensions --show-versions` reports the expected version.

## Open questions

None at design time. If automated sync becomes desirable later, that's a separate project.
