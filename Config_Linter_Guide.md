# Config Linter Guide

This guide explains how to use `config_linter.py` to validate `after.json` before submitting a governance proposal.

## What the Config Linter Does

The Rust governance tool (`pyth-lazer-governance`) aborts a proposal pipeline with a stack-trace error when `after.json` violates structural invariants — for example, duplicate `feedId`s, references to publishers that don't exist, or `minPublishers` that leaves a feed with no fault tolerance. Catching the same conditions locally surfaces a readable error before CI rejects the change.

`config_linter.py` runs over `after.json` and emits findings categorized as **ERROR** (exit 1, gates CI) or **WARNING** (exit 0, advisory). It uses pure stdlib — no ClickHouse, no network, no auth.

By default the linter runs in **diff mode**: it lints both the working-tree config and the version at the merge-base of the current branch with `origin/main`, and reports only findings introduced by the branch. Pre-existing findings are silently suppressed. This keeps long-standing technical debt from blocking unrelated PRs.

## Concepts

### Findings

Every issue surfaces as a structured finding with five fields:

| Field      | Meaning                                                                  |
| ---------- | ------------------------------------------------------------------------ |
| `rule_id`  | `E###` for errors, `W###` for warnings                                   |
| `severity` | `ERROR` or `WARNING`                                                     |
| `message`  | Human-readable description (e.g. `"minPublishers (5) >= publisher count (5)"`) |
| `feed_id`  | The offending `feedId` (or `null` for publisher-array rules)             |
| `symbol`   | The offending `symbol` (or `null`)                                       |

ERRORs cause exit code 1. WARNINGs are advisory unless `--warnings-as-errors` is set.

### Diff Mode

When run with no `--baseline*` flag the linter:

1. Verifies it's inside a git work tree.
2. Resolves the baseline ref (default `origin/main`).
3. Walks back to `git merge-base HEAD <baseline-ref>`.
4. Reads `after.json` at that commit via `git show <merge-base>:<config-path>`.
5. Lints both versions and subtracts pre-existing findings.

Auto-detect failure modes (printed to stderr, then falls back to full lint):

| Situation                                             | `<reason>`                                      |
| ----------------------------------------------------- | ----------------------------------------------- |
| Not inside a git work tree                            | `not a git repository`                          |
| Baseline ref does not exist locally                   | `ref 'origin/main' not found`                   |
| Current `HEAD` is on the baseline ref                 | `on baseline ref, no diff to compute`           |
| Config path was untracked at the merge-base           | `path 'after.json' not present at <merge-base>` |
| Baseline JSON fails to parse                          | `baseline JSON invalid: <error>`                |

### Comparison Key

A finding is "pre-existing" when the tuple `(rule_id, feed_id, symbol)` matches any baseline finding. Message text is intentionally excluded from the key, so magnitude shifts (e.g. publisher count drops further on E004) don't surface as new findings. To audit those, run with `--no-baseline` periodically.

### Rule Scope

Most rules skip `INACTIVE` feeds. The major scope buckets:

| Scope                | Rules                                                                  |
| -------------------- | ---------------------------------------------------------------------- |
| All feeds            | `E001`, `E007`                                                         |
| Active-pipeline only | `E002` (STABLE + COMING_SOON)                                          |
| Non-INACTIVE         | `E003`, `E006`, `E008`, `E010`, `E012`, `E016`, `W006`                 |
| STABLE only          | `E004`, `E005`, `E009`, `E011`, `E014`, `W001`, `W002`, `W005`, `W007` |
| COMING_SOON only     | `W004`, plus `E013` for futures                                        |
| STABLE + COMING_SOON | `W003`                                                                 |
| Publishers array     | `E017`, `E018`                                                         |

## How To: Run the Linter Locally

```bash
# Default: diff against origin/main (auto-detected)
python3 config_linter.py --config after.json

# Diff against an explicit baseline file
python3 config_linter.py --config after.json --baseline before.json

# Diff against a different ref (e.g. develop)
python3 config_linter.py --config after.json --baseline-ref develop

# Force full lint (skip baseline)
python3 config_linter.py --config after.json --no-baseline

# JSON output (pipe-friendly)
python3 config_linter.py --config after.json --format json

# Treat warnings as errors (in diff mode applies to NEW warnings only)
python3 config_linter.py --config after.json --warnings-as-errors

# Write results to file (format auto-detected from extension)
python3 config_linter.py --config after.json --output lint.json
```

### Arguments

| Argument               | Default       | Notes                                                                 |
| ---------------------- | ------------- | --------------------------------------------------------------------- |
| `--config`             | —             | Required. Path to `after.json`.                                       |
| `--baseline`           | (auto-detect) | Explicit baseline file. Mutually exclusive with `--no-baseline`.      |
| `--baseline-ref`       | `origin/main` | Git ref for auto-detect. Ignored when `--baseline`/`--no-baseline`.   |
| `--no-baseline`        | False         | Force full lint.                                                      |
| `--format`             | `text`        | `text` or `json`.                                                     |
| `--warnings-as-errors` | False         | Exit 1 if any warning. In diff mode, applies only to **new** warnings. |
| `--output`             | —             | Write findings to file. Format auto-detected from extension.          |

### Exit Codes

- `0` — no errors (warnings allowed unless `--warnings-as-errors`)
- `1` — at least one **ERROR** finding (or any finding when `--warnings-as-errors`)

In diff mode, exit code reflects only **new** findings.

## How To: Run the Linter in CI

Add a pre-merge job that runs the default diff-mode invocation:

```yaml
- name: Lint after.json
  run: python3 config_linter.py --config after.json
```

This blocks the merge on any **new** error introduced by the branch. Pre-existing findings are surfaced in stdout but do not fail the job.

To gate on warnings as well (recommended once the baseline is clean):

```yaml
- name: Lint after.json (strict)
  run: python3 config_linter.py --config after.json --warnings-as-errors
```

For a non-blocking advisory pass over the whole config (useful as a periodic audit job, not on every PR):

```yaml
- name: Full audit
  run: python3 config_linter.py --config after.json --no-baseline
  continue-on-error: true
```

## How To: Read a Finding

### Text output

```
ERRORS (3 found):
  E009  Feed 458 (Crypto.JITOSOL/USD): STABLE feed references .Test-suffixed publishers: [49]
  E012  Feed 964 (Equity.US.APTV/USD): hermes_id 'abc...' duplicated across feedIds: 964, 3126
  E013  Feed 2973 (Commodities.ALH6/USD): COMING_SOON futures feed has expired (latest validTo: 2026-03-27T17:00:00+00:00); change state to INACTIVE

WARNINGS (1 found):
  W003  Feed 1775 (Equity.US.XLK/USD): REGULAR schedule deviates from (equity, US) majority

Summary: 3 errors, 1 warnings
```

In diff mode the header reads `ERRORS (1 new):` / `WARNINGS (2 new):` and the summary appends `(N pre-existing findings suppressed)`.

### JSON output

A flat array of finding objects, suitable for piping into `jq`:

```json
[
  {
    "rule_id": "E009",
    "severity": "ERROR",
    "message": "STABLE feed references .Test-suffixed publishers: [49]",
    "feed_id": 458,
    "symbol": "Crypto.JITOSOL/USD"
  }
]
```

Pre-existing-count metadata appears only in text output.

## How To: Resolve Common Findings

The five rules that bite most often, with the typical fix:

| Rule | Symptom                                            | Typical fix                                                           |
| ---- | -------------------------------------------------- | --------------------------------------------------------------------- |
| E004 | `minPublishers (N) >= publisher count (N)`         | Lower `minPublishers`, or onboard another publisher to add headroom.  |
| E011 | Two STABLE peers disagree on a session schedule    | Pick one canonical schedule for the asset group and update outliers.  |
| E014 | STABLE benchmarkable feed missing `benchmarkMapping` | Add `benchmarkMapping` to every non-OVERNIGHT session.                |
| W003 | Schedule deviates from asset-class majority        | Confirm the deviation is intentional, otherwise align with majority.  |
| E013 | COMING_SOON futures past every `validTo`           | Flip `state` to `INACTIVE` (the contract has rolled off).             |

For the full set, see [docs/config_linter_examples.md](docs/config_linter_examples.md), which shows the smallest fragment that triggers each rule.

## How To: Investigate Pre-existing Findings

Diff mode silently suppresses anything that already existed at the merge-base. To audit everything the linter sees in the working tree:

```bash
python3 config_linter.py --config after.json --no-baseline
```

To compare against a specific historical state (e.g. what was deployed last week):

```bash
git show <commit>:after.json > /tmp/before.json
python3 config_linter.py --config after.json --baseline /tmp/before.json
```

To get a stable identity for a finding across runs, the linter uses `(rule_id, feed_id, symbol)`. Two findings with the same tuple are considered the same issue even if their messages differ.

## How To: Add a New Rule

1. Add the check to `lib/config_lint.py` as a new `check_<topic>` function returning `list[LintFinding]`. Use an unused rule ID (next free `E0##` or `W0##`).
2. Wire it into `lint_config()` at the bottom of the file.
3. Add unit tests in `tests/test_config_lint.py` (one class per rule, one method per trigger condition).
4. Add a row to the rule table in `docs/config_linter.md`.
5. Add a minimal trigger example to `docs/config_linter_examples.md`.
6. Add a row to the cross-symptom cheatsheet at the bottom of the examples doc.

The orchestrator at the bottom of `lib/config_lint.py` is the only place that needs to be aware of every rule. Each `check_*` function is independent and operates on the parsed JSON dict.

## Rule Reference

For each rule's exact trigger condition and a copy-pasteable example fragment, see [docs/config_linter_examples.md](docs/config_linter_examples.md). The summary tables below are duplicates of the reference in [docs/config_linter.md](docs/config_linter.md).

### Errors

| ID   | Rule                                                                                | Scope                                                       |
| ---- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| E001 | Duplicate `feedId`                                                                  | all feeds                                                   |
| E002 | Duplicate `symbol` within STABLE/COMING_SOON                                        | active-pipeline                                             |
| E003 | References unknown `publisherId`                                                    | non-INACTIVE                                                |
| E004 | `minPublishers >= publisher count` (no headroom)                                    | STABLE, non-exempt                                          |
| E005 | STABLE feed with no publishers                                                      | STABLE                                                      |
| E006 | Non-equity feed has extended sessions                                               | non-INACTIVE, non-equity                                    |
| E007 | Missing required field (`feedId`, `symbol`, `state`, `kind`, `metadata.asset_type`) | all feeds                                                   |
| E008 | Session-level publisher not in top-level list                                       | non-INACTIVE                                                |
| E009 | STABLE feed references a `.Test`-named publisher                                    | STABLE                                                      |
| E010 | Duplicate session in `marketSchedules`                                              | non-INACTIVE                                                |
| E011 | Schedule inconsistency within asset group                                           | STABLE only                                                 |
| E012 | Duplicate `metadata.hermes_id`                                                      | non-INACTIVE                                                |
| E013 | COMING_SOON futures past every `validTo`                                            | COMING_SOON futures                                         |
| E014 | STABLE benchmarkable feed missing `benchmarkMapping`                                | STABLE, benchmarkable, non-OVERNIGHT                        |
| E015 | `corporateActions` schema violation                                                 | any feed with `corporateActions`                            |
| E016 | Identifier date range overlap within same vendor/session                            | non-INACTIVE, 2+ identifiers per vendor                     |
| E017 | Duplicate `publisherId` in publishers array                                         | publishers array                                            |
| E018 | Duplicate publisher `name` in publishers array                                      | publishers array                                            |

### Warnings

| ID   | Rule                                                                          | Scope                       |
| ---- | ----------------------------------------------------------------------------- | --------------------------- |
| W001 | US equity missing extended sessions (`PRE_MARKET`/`POST_MARKET`/`OVER_NIGHT`) | STABLE US equities          |
| W002 | US equity using a non-`America/New_York` timezone                             | STABLE US equities          |
| W003 | Schedule deviates from asset-class majority                                   | STABLE + COMING_SOON        |
| W004 | COMING_SOON feed with no publishers                                           | COMING_SOON                 |
| W005 | `minPublishers` leaves only 1 headroom publisher                              | STABLE, non-exempt          |
| W006 | Duplicate `publisherId` in feed                                               | non-INACTIVE                |
| W007 | STABLE feed references a `TEST` key-type publisher                            | STABLE                      |
| W009 | Unknown `corporateActions` event type (schema not validated)                  | any feed with `corporateActions` |

### E011 vs W003

Both flag schedule drift but with different scopes:

- **E011 (ERROR)** — fires when two `STABLE` feeds in the same group disagree on a session's `marketSchedule`. Groups are `(asset_type, equity_listing_prefix?, futures_root?)`. Equity futures are sub-grouped by both listing prefix and root. Comparison is per-session within a group; a feed missing a session is not penalized.
- **W003 (WARNING)** — fires on minority deviation from the group majority across `STABLE + COMING_SOON` feeds. Same group key as E011. Surfaces drift E011 cannot see (COMING_SOON disagreeing with STABLE peers) without blocking CI.

The two intentionally overlap on STABLE feeds.

### Asset Types Exempt from E004 / W005

Single-source asset types where `minPublishers >= publisher count` is acceptable:

- `funding-rate`
- `custom`
- `crypto-redemption-rate`
- `nav`
- `crypto-index`
- `kalshi`

Exemptions apply only to the publisher-count headroom rules.

### Notes on Time-Sensitive and Schema-Validating Rules

- **E013** is evaluated against `datetime.now(timezone.utc)` at runtime. Feeds with no `validTo` identifiers are skipped — E013 only fires when there is positive evidence every mapped contract has rolled off.
- **E014** considers only `equity`, `fx`, `metal`, `commodity`, `rates` as benchmarkable. The `OVER_NIGHT` session is always exempt because it uses publisher 32 peer comparison rather than Datascope.
- **E015 / W009** validate `corporateActions` entries. Only `SPLIT` is currently implemented. Unknown event types raise `W009` (advisory) rather than blocking CI; once the linter is taught the new schema, the same config produces `E015` with structured field-level messages.
- **E016** sorts identifiers by `validFrom` and checks consecutive pairs. The last identifier in a chain may omit `validTo` (open-ended current contract); a non-last identifier missing `validTo` is flagged because it creates an unbounded range.
- **E017 / E018** mirror invariants enforced by the Rust governance tool's `diff_publishers`. Both fire before the proposal pipeline reaches the Rust stack-trace error.

## Suggested Adoption Plan

1. **Run locally on the current branch** with the default diff-mode invocation. Fix any new errors introduced by the branch before opening a PR.
2. **Add the diff-mode lint as a required CI check** on the governance repo. This blocks regressions without forcing existing technical debt into scope.
3. **Run a one-shot full audit** (`--no-baseline`) and triage the pre-existing findings into a backlog. Fix the ERRORs first; the WARNINGs are advisory until you're ready to enforce them.
4. **Once the baseline is clean**, switch CI to `--warnings-as-errors` so that no new warnings can land. Pre-existing warnings remain suppressed in diff mode, so this does not retroactively block on legacy state.
5. **Schedule a periodic full audit** (weekly or per-release) to catch findings whose magnitude has changed without crossing the diff-mode comparison key — for example, an `E004` violation getting worse. Diff mode only sees these as "still the same finding," so they need a separate sweep.
