# Config linter precision improvements — design

Date: 2026-05-05
Status: design (pending implementation plan)

## Goal

Tighten and clarify a handful of existing config-linter rules whose
current behavior is either misleading, incomplete, or silently wrong on
ambiguous input. Also fix two pieces of documentation drift and one
JSON-output omission.

This is a precision pass on the existing ruleset, not a new ruleset.
No new rule IDs are introduced; the changes either reword messages,
extend scope, or refine logic on rules that already exist.

## Scope summary

| Item | Type   | Affects                                                         |
| ---- | ------ | --------------------------------------------------------------- |
| 1    | Logic  | E004 message text                                               |
| 2    | Logic  | E011 ambiguous-tie handling                                     |
| 3    | Logic  | E013 expand to STABLE expired futures                           |
| 4    | Logic  | E014 lift OVER_NIGHT exemption                                  |
| 5    | Logic  | W003 fire when no majority exists                               |
| 6    | Output | `--format json` envelope to include `pre_existing_count`        |
| 7    | Docs   | VS Code extension spec/plan: remove stale "exit code 2" claim   |

E017/E018 are already documented in `docs/config_linter.md` (lines
126–127); no doc change needed there.

## Item 1 — E004 message rewording

**Current:** `minPublishers (X) >= publisher count (Y), no fault tolerance`
**New:** `minPublishers (X) >= publisher count (Y), Not enough publishers permissioned`

Same condition, same severity, same scope. Only the trailing clause
changes. Both top-level and session-level E004 emissions update.

**Confirmation on coverage:** the existing `>=` predicate already
catches both `==` and `>` cases, so `minPublishers > len(pub_ids)` is
covered by E004 today (no separate rule needed). The
`len(pub_ids) == 0` case is caught by E005.

## Item 2 — E011 ambiguous-tie handling

**Today:** when a STABLE bucket has 2 distinct schedules with equal
counts, `Counter.most_common(1)` arbitrarily picks one as the
"reference" and flags the other. The flagged feed is determined by
dict insertion order, not by any meaningful signal.

**New behavior (option c from brainstorming):** detect ties on the
top count and switch reporting mode.

```
sig_counter = Counter(...)
top_count = sig_counter.most_common(1)[0][1]
top_schedules = {s for s, c in sig_counter.items() if c == top_count}

if len(top_schedules) == 1:
    # current behavior — flag minority feeds against the clear majority
else:
    # tie — flag every STABLE feed in the bucket with a "no consensus" message
```

**Tie-mode message:**

```
{session} schedule has no consensus across group {group_label}:
  {len(distinct)} distinct schedules across {N} STABLE feeds, no majority
```

Every STABLE feed in the bucket gets one finding under E011 in this
case. This preserves the per-feed identity tuple
`(rule_id, feed_id, symbol)` that diff mode and the VS Code extension
rely on.

## Item 3 — E013 expand to STABLE expired futures

**Today:** E013 fires on `state == "COMING_SOON"` futures whose every
`validTo` is in the past.

**New:** E013 also fires on `state == "STABLE"` futures whose every
`validTo` is in the past. Scope stays futures-only (`is_futures_symbol`
guard retained); the rule branches the message by state.

| State        | Message                                                                             |
| ------------ | ----------------------------------------------------------------------------------- |
| COMING_SOON  | `COMING_SOON futures feed has expired (latest validTo: {ts}); change state to INACTIVE` |
| STABLE       | `STABLE futures feed has expired (latest validTo: {ts}); change state to INACTIVE`  |

Same rule ID, same severity (ERROR). The "more critical" framing for
STABLE comes through in the message and PR-review attention rather
than a separate code.

`docs/config_linter.md` line 175 ("Notes on E013") needs to mention
both states.

## Item 4 — E014 lift OVER_NIGHT exemption

**Today:** `check_benchmark_mapping` skips OVER_NIGHT
(`config_lint.py:692`), based on the historical reasoning that
OVER_NIGHT uses publisher 32 peer comparison rather than Datascope.

**New:** delete the OVER_NIGHT skip. Every session in
`marketSchedules` of a STABLE benchmarkable feed must have a
populated `benchmarkMapping`.

**Empirical safety check:** of the 126 STABLE feeds in the current
`after.json` that have an OVER_NIGHT session, 100% already have
`benchmarkMapping` populated. So this change is a tightening of an
already-followed convention, not a new requirement that would
immediately fail existing config.

**Severity:** ERROR (unchanged).
**Asset-type scope:** unchanged (`_BENCHMARKABLE_ASSET_TYPES`).
The implicit equity-only scope of OVER_NIGHT is enforced by which
feeds actually carry that session, not by extra rule branching.

`docs/config_linter.md` line 179 ("Notes on E014") needs the
OVER_NIGHT exemption claim removed.

## Item 5 — W003 fire when no majority

**Today:** if the highest-count schedule in a bucket has count 1
(i.e., every feed has a unique schedule), W003 short-circuits with
`if counts[majority] == 1: continue` and emits nothing.

**New:** detect the no-majority case and emit one warning per feed in
the bucket. Mirror the same option-c approach as E011 for symmetry.

```
counts = Counter(...)
top_count = counts.most_common(1)[0][1]
top_schedules = {s for s, c in counts.items() if c == top_count}

if top_count >= 2 and len(top_schedules) == 1:
    # current behavior — flag minority feeds against majority
elif top_count == 1 or len(top_schedules) > 1:
    # no consensus — flag every STABLE+COMING_SOON feed in the bucket
```

**No-consensus message:**

```
{session} schedule has no consensus across group {group_label}
```

Severity stays WARNING. Per-feed identity tuple preserved.

## Item 6 — JSON output envelope

**Today:** `_format_json` (`config_linter.py:121`) emits a bare array
of findings. The text path threads `pre_existing_count` into its
summary; the JSON path discards it.

**New JSON shape:**

```json
{
  "findings": [
    {
      "rule_id": "E004",
      "severity": "ERROR",
      "message": "...",
      "feed_id": 1163,
      "symbol": "Equity.US.NVDA/USD"
    }
  ],
  "pre_existing_count": 12
}
```

`pre_existing_count` is omitted (or `null`) when not in diff mode, so
consumers can distinguish "full lint" from "diff mode with zero
suppressed".

**Backwards compatibility:** This is a breaking change for any
consumer that parses the output as `JSON.parse(stdout)` and expects
an array. Acceptable because:

1. The only known JSON consumer is the VS Code extension, which
   already does its own dispatch on stdout content (`linter.ts:96`)
   and can be updated in lockstep.
2. The text format has carried `pre_existing_count` for some time;
   bringing JSON to parity is a stated goal.

The VS Code extension parser must be updated to read
`response.findings` instead of `response`. This is in scope for the
implementation plan, not a follow-up.

## Item 7 — Doc fix: stale "exit code 2" claim

**Today:** the VS Code extension design and plan both claim the
linter exits 2 when the baseline file is missing or unparseable.
The CLI does not — it exits 1, like every other failure
(`config_linter.py:216`).

**Verified:** the extension code itself never checks for exit code 2
(`grep -rn` over `tools/vscode-extension/src/` found no usage). It
dispatches on `ENOENT` for spawn failures and on stdout content for
everything else.

**Fix:** edit two files only:

- `docs/superpowers/specs/2026-04-29-vscode-config-linter-extension-design.md:86`
- `docs/superpowers/plans/2026-04-29-vscode-config-linter-extension-plan.md:893`

Replace the "0, 1, or 2" claim with "0 (no errors) or 1 (errors,
spawn failure, or unparseable input)". No CLI change.

## Out of scope

- Adding a new exit code 2 contract to the CLI.
- Distinguishing "baseline missing" from "errors found" in any
  surface other than stderr text.
- Any new rule IDs.
- Changing the diff-mode comparison key.
- Touching the exchange-aware rules (E019–E025, W010–W011).

## Test plan (implementation-time)

Each item lands with focused unit tests in `tests/test_config_lint.py`
(library) and `tests/test_config_linter_cli.py` (CLI envelope):

| Item | Tests                                                                  |
| ---- | ---------------------------------------------------------------------- |
| 1    | E004 message text matches new wording at top-level and session-level   |
| 2    | E011 emits per-feed findings on 2-feed-2-schedule bucket               |
| 2    | E011 keeps current per-minority behavior when one schedule dominates    |
| 3    | E013 fires on STABLE expired futures with state-tagged message         |
| 3    | E013 keeps existing COMING_SOON behavior unchanged                     |
| 4    | E014 fires on STABLE benchmarkable feed with empty OVER_NIGHT mapping  |
| 4    | E014 silent on STABLE feed where every session (incl. OVER_NIGHT) has mapping |
| 5    | W003 emits one finding per feed when bucket has no majority            |
| 5    | W003 keeps current behavior when one schedule has clear majority       |
| 6    | `--format json` includes `pre_existing_count` in diff mode             |
| 6    | `--format json` omits or nulls `pre_existing_count` outside diff mode  |
| 6    | VS Code extension parser reads `response.findings`                     |

Diff-mode regression: re-run the linter against current `after.json`
in diff mode against `origin/main` and confirm no new findings appear
that aren't a direct consequence of items 2–5 (the message change in
item 1 should be silently absorbed by `_finding_key` since message
text is excluded from the identity tuple).
