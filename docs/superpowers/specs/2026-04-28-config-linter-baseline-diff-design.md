# Config Linter — Baseline Diff Mode (Default)

**Date:** 2026-04-28
**Branch:** `feat/config-linter-baseline-diff`
**Scope:** `lib/config_lint.py`, `config_linter.py`, `.github/workflows/config-lint.yaml`, tests, docs

## Problem

`config_linter.py` evaluates every rule against every feed in `after.json` and reports the full set of findings. When a PR touches a small slice of the config, reviewers and CI still see findings for unrelated, pre-existing problems. The signal of "what did this PR introduce?" is buried in noise.

The fix is to make the linter aware of a baseline (the config as it existed before the PR's changes) and report only the findings that are present in the after-state but absent in the baseline. Pre-existing findings are tech debt; they are out of scope for any individual PR.

The user must never have to maintain a `before.json` file by hand. The linter discovers the baseline automatically from git when running on a PR branch.

## Goals

1. Default linter behavior reports **only** findings introduced by changes in the current branch relative to `origin/main`.
2. Baseline discovery is fully automatic in CI and on PR branches; no manual file management.
3. Pre-existing findings still affect tech-debt visibility (count is shown in the summary line) but never affect exit code.
4. Existing rule code is unchanged. The diff is a post-filter over current-output.
5. CI runs the linter on every PR that touches `after.json`.

## Non-goals

- "Fixed findings" reporting (showing what the PR resolved). Out of scope; no current consumer asks for it.
- Re-grouping or refactoring existing rule logic.
- Detecting whether a finding got "worse" along an axis the rule message exposes (e.g., publisher count dropping further on E004). The comparison key is `(rule_id, feed_id, symbol)`; magnitude changes within a rule are intentionally suppressed.
- Linting any config other than `after.json`.

## Solution

Three coordinated changes:

1. **`lib/config_lint.py`** — add `lint_config_diff(after_config, before_config, now=None)`. It calls existing `lint_config()` twice and returns only the after-findings whose `(rule_id, feed_id, symbol)` tuple does not appear in the before-findings. Existing rule code and `lint_config()` itself are untouched.
2. **`config_linter.py`** — make diff mode the default. Auto-detect the baseline by computing `git merge-base HEAD origin/main` and reading the config file at that commit via `git show <merge-base>:<config-path>`. Add `--baseline`, `--baseline-ref`, and `--no-baseline` flags for explicit control. Fall back to full lint with a stderr note when auto-detect cannot succeed.
3. **`.github/workflows/config-lint.yaml`** — new workflow, triggered on `pull_request` events that touch `after.json`. Calls `python3 config_linter.py --config after.json` and lets the new default behavior do the rest.

### Comparison key

```python
def _finding_key(f: LintFinding) -> tuple[str, Optional[int], Optional[str]]:
    return (f.rule_id, f.feed_id, f.symbol)
```

A finding is "pre-existing" iff its key matches any finding produced by linting the baseline config. `feed_id` and `symbol` may be `None`; that is a valid tuple element.

### `lint_config_diff` signature

```python
def lint_config_diff(
    after_config: dict,
    before_config: dict,
    now: Optional[datetime] = None,
) -> list[LintFinding]:
    """Lint after_config and return only findings not present in before_config.

    A finding is "pre-existing" when its (rule_id, feed_id, symbol) tuple
    matches any finding produced by linting before_config under the same
    `now`. Pre-existing findings are dropped from the result.

    The same `now` is passed to both runs so that time-dependent rules
    (E013) are evaluated against a single instant.
    """
```

### CLI surface

```
--config PATH         Path to config file (required). Today's flag, unchanged.
--baseline PATH       Use the given file as baseline (overrides auto-detect).
--baseline-ref REF    Git ref for auto-detect (default: origin/main).
--no-baseline         Force full lint, bypass diff mode.
--format {text,json}  Unchanged.
--output PATH         Unchanged.
--warnings-as-errors  Unchanged. In diff mode applies to NEW warnings only.
```

### Default behavior decision tree

```
Is --no-baseline set?  -> yes -> full lint (today's behavior)
                       -> no
Is --baseline PATH set? -> yes -> load file, run diff
                        -> no
Try git auto-detect:
  1. git rev-parse --is-inside-work-tree   (must succeed)
  2. git rev-parse <baseline-ref>          (must resolve, default origin/main)
  3. git merge-base HEAD <baseline-ref>    (must produce a sha != HEAD)
  4. git show <merge-base>:<config-path>   (must succeed)
  -> all four succeed -> parse JSON, run diff
  -> any step fails    -> stderr NOTE, full lint
```

### Auto-detect failure modes

In each case, print to stderr `NOTE: baseline unavailable (<reason>); running full lint` and run today's full lint. Exit code follows full-lint semantics.

| Situation                                             | `<reason>`                                      |
| ----------------------------------------------------- | ----------------------------------------------- |
| Not inside a git work tree                            | `not a git repository`                          |
| Baseline ref does not exist locally                   | `ref 'origin/main' not found`                   |
| Current `HEAD` is on the baseline ref (no divergence) | `on baseline ref, no diff to compute`           |
| Config path was not tracked at the merge-base         | `path 'after.json' not present at <merge-base>` |
| `git` binary not on PATH                              | `git command not available`                     |
| Baseline JSON fails to parse                          | `baseline JSON invalid: <error>`                |

### Behavior matrix (full)

| Invocation                                   | Behavior                        |
| -------------------------------------------- | ------------------------------- |
| `--config after.json` (in git PR branch)     | Auto-detect baseline, diff mode |
| `--config after.json` (on `main`)            | NOTE to stderr, full lint       |
| `--config after.json` (outside git)          | NOTE to stderr, full lint       |
| `--config after.json --baseline before.json` | Diff against given file         |
| `--config after.json --baseline-ref develop` | Auto-detect using `develop`     |
| `--config after.json --no-baseline`          | Full lint always                |

### Output (diff mode)

Text:

```
ERRORS (2 new):
  E004  Feed 1163 (Equity.US.NVDA/USD): minPublishers (5) >= publisher count (5), no fault tolerance
  E011  Feed 1775 (Equity.US.XLK/USD): REGULAR schedule disagrees with group (equity, US): 3 distinct schedules across 142 STABLE feeds

WARNINGS (1 new):
  W003  Feed 999 (Commodities.GCH6/USD): REGULAR schedule deviates from (commodity, GC) majority

Summary: 2 new errors, 1 new warning (12 pre-existing findings suppressed)
```

When zero new findings:

```
No new issues found. (12 pre-existing findings suppressed)
```

JSON output is a flat array of `LintFinding` objects, just filtered. No envelope change. Pre-existing-count metadata appears only in text output.

### Exit codes (diff mode)

- `0` — no new errors. New warnings allowed unless `--warnings-as-errors`.
- `1` — at least one new error. With `--warnings-as-errors`, also any new warning.

Pre-existing findings never affect exit code in diff mode.

### Edge cases

| Case                                                                    | Result                                                        |
| ----------------------------------------------------------------------- | ------------------------------------------------------------- |
| Feed unchanged in PR, has pre-existing E004                             | Suppressed in both runs → not reported                        |
| New feed added in PR, has E004                                          | Not in before, in after → reported                            |
| Existing feed modified, new error appears                               | Not in before, in after → reported                            |
| Existing feed modified, error becomes worse (same rule_id)              | Same key → suppressed (intentional)                           |
| Feed deleted in PR                                                      | Not in after → nothing to report                              |
| Group-rule cascade: feed A modified, E011 now fires on untouched feed B | E011 on B was not in before, is in after → reported (correct) |
| Symbol renamed (same feed_id, new symbol)                               | Different key → reported as new                               |
| feed_id renumbered                                                      | Different key → all old findings reappear as new              |

### CI workflow

`.github/workflows/config-lint.yaml`:

```yaml
name: Config Lint
on:
  pull_request:
    paths:
      - "after.json"

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0 # need full history for merge-base
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Run config linter
        run: python3 config_linter.py --config after.json
```

`fetch-depth: 0` is required so that `git merge-base HEAD origin/main` resolves correctly.

### Why merge-base, not just `origin/main`

Using the tip of `origin/main` as baseline breaks if main has moved ahead since the branch diverged: the linter would diff against a config that contains commits the PR author never saw, and any new errors introduced on main would surface as if the PR introduced them. The merge-base gives us "the state of the config when this branch started", which is the accurate definition of "what did this PR introduce".

### Determinism

Both lint runs share the same `now` (passed in once by `lint_config_diff`). E013 is the only time-dependent rule; threading `now` keeps the diff stable across second/midnight boundaries.

### Performance

Two full lint passes over a config with ~3000 feeds. The linter is pure Python stdlib with no I/O — current full-lint runtime is well under a second. Doubling it is negligible.

## Testing strategy

### Unit tests on `lint_config_diff`

| Test                                          | Setup                                                                              | Assertion                   |
| --------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------- |
| `test_diff_suppresses_preexisting_finding`    | `before` and `after` both have feed 100 with E004                                  | empty result                |
| `test_diff_reports_newly_introduced_finding`  | `before` clean for feed 100; `after` has E004 on feed 100                          | one E004                    |
| `test_diff_reports_finding_on_brand_new_feed` | `before` lacks feed 999; `after` has it with E005                                  | one E005                    |
| `test_diff_drops_findings_for_removed_feed`   | `before` has feed 100 with E004; `after` lacks feed 100                            | empty result                |
| `test_diff_treats_symbol_rename_as_new`       | Same feed_id, different symbol; rule fires both times                              | one finding (after-version) |
| `test_diff_handles_group_rule_cascade`        | E011 group has 3 STABLE feeds clean; `after` adds 4th feed with deviating schedule | E011 only on the new feed   |
| `test_diff_uses_consistent_now_for_e013`      | COMING_SOON futures with all `validTo` in past, identical in before/after          | empty result                |
| `test_diff_with_warnings_as_errors_diff_mode` | Pre-existing W003 + new W003 on different feed                                     | new W003 only               |

### CLI tests on `config_linter.py`

| Test                                              | Verifies                                                               |
| ------------------------------------------------- | ---------------------------------------------------------------------- |
| `test_cli_explicit_baseline_path`                 | `--baseline before.json` runs diff mode                                |
| `test_cli_no_baseline_disables_diff`              | `--no-baseline` runs full lint even when git auto-detect would succeed |
| `test_cli_auto_detect_falls_back_when_not_in_git` | NOTE to stderr, full lint output                                       |
| `test_cli_auto_detect_falls_back_on_baseline_ref` | When on `main`, NOTE + full lint                                       |
| `test_cli_summary_line_diff_mode`                 | Output contains `(N pre-existing findings suppressed)`                 |

### Git auto-detect tests

Mock `subprocess.run` for `git rev-parse`, `git merge-base`, `git show`. Tests must not invoke real git or depend on the working repo's history.

### Workflow file

No automated test (it requires a PR to fire). Manual verification: open a draft PR touching `after.json` after this lands and confirm the workflow runs.

### Coverage target

80%+ on new code. Listed cases give full branch coverage of the diff function and the CLI auto-detect logic.

## File touch list

- `lib/config_lint.py` — add `lint_config_diff` and `_finding_key`. No changes to existing rule functions.
- `config_linter.py` — add `--baseline`, `--baseline-ref`, `--no-baseline` flags; auto-detect logic; updated text-mode summary line.
- `.github/workflows/config-lint.yaml` — new file, ~15 lines.
- `tests/test_config_lint.py` — diff-function unit tests (file already exists, append).
- `tests/test_config_linter_cli.py` — CLI tests with mocked git (file already exists, append).
- `docs/config_linter.md` — document `--baseline`, `--baseline-ref`, `--no-baseline`, the new default, and the auto-detect failure modes.

## Open questions for the implementation plan

- `--baseline` and `--no-baseline` should be mutually exclusive at the argparse level (use `add_mutually_exclusive_group`). Confirm this is the convention in the existing CLI before locking it in.
