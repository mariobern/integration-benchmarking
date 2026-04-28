# Config Linter — International Equities & Severity-by-State

**Date:** 2026-04-28
**Branch:** `feat/config-linter-intl-equities`
**Scope:** `lib/config_lint.py`, `lib/symbol_utils.py`, tests, docs

## Problem

E011 ("schedule inconsistency within asset group") and W003 ("schedule deviates from asset-class majority") both group equity feeds by `asset_type == "equity"` only. Every non-US equity (`Equity.JP`, `Equity.KR`, `Equity.GB`, `Equity.HK`, `Equity.DE`, `Equity.FR`, `Equity.NL`, `Equity.IE`, `Equity.LU`, `Equity.CN`, `Equity.CA`, `Equity.Index`) is therefore compared against the US-majority schedule signature, which encodes timezone (`America/New_York`). These feeds legitimately use different exchanges and trading hours, so the rules misfire on every single one of them.

Current snapshot of `after.json` (non-INACTIVE):

| Group           | Feeds | Distinct schedule sigs |
| --------------- | ----- | ---------------------- |
| Equity.US       | 994   | 9                      |
| Equity.JP       | 233   | 1                      |
| Equity.KR       | 104   | 2                      |
| Equity.GB       | 105   | 1                      |
| Equity.HK       | 90    | 1                      |
| Equity.DE       | 39    | 1                      |
| Equity.FR       | 37    | 1                      |
| Equity.Index    | 12    | 1                      |
| Equity.IE       | 6     | 3                      |
| Equity.NL       | 5     | 2                      |
| Equity.LU/CN/CA | 2/2/1 | 1 each                 |

Under the current rules, the ~620 non-US equity feeds each fire E011 and W003 against the US majority — drowning real signal in noise.

A secondary issue: E011 is an ERROR that blocks CI. It fires on any drift in any non-INACTIVE feed, including COMING_SOON feeds that are by definition not yet in production. A misconfigured COMING_SOON feed should not block deployment of unrelated, correct STABLE feeds.

## Solution

Two coordinated changes to `lib/config_lint.py`:

1. **Refine grouping by listing prefix.** For equity feeds, sub-group by the second segment of the symbol (`US`, `JP`, `Index`, …). Apply identically to E011 and W003.
2. **Split severity by state.** E011 (ERROR, CI blocker) runs on STABLE feeds only. W003 (WARNING, advisory) runs on STABLE + COMING_SOON feeds. Both rules use the same group key and the same group_signatures collection.

### New helper in `lib/symbol_utils.py`

```python
def equity_listing_prefix(symbol: str) -> str:
    """For 'Equity.<X>.<Y>/<Z>' return '<X>', else ''.

    Examples:
        'Equity.US.AAPL/USD' -> 'US'
        'Equity.JP.1305/JPY' -> 'JP'
        'Equity.Index.TSLA/USD' -> 'Index'
        'Crypto.BTC/USD' -> ''
        'Equity.US' -> '' (malformed)
    """
    parts = symbol.split(".")
    if len(parts) >= 3 and parts[0] == "Equity":
        return parts[1]
    return ""
```

### Group key construction

```python
if asset_type == "equity":
    prefix = equity_listing_prefix(sym)
    if is_futures_symbol(sym):
        group_key = (asset_type, prefix, futures_root(sym))
    else:
        group_key = (asset_type, prefix)
else:
    if is_futures_symbol(sym):
        group_key = (asset_type, futures_root(sym))
    else:
        group_key = (asset_type,)
```

`Equity.Index` lands in `("equity", "Index")`, automatically standalone from `("equity", "US")`. Equity futures sub-group by listing country and root (`("equity", "US", "EM")` for E-Mini S&P, `("equity", "KR", "KS")` for KOSPI 200, etc.).

### State scope and severity

| Rule     | State filter         | Futures handling            | Severity | CI gate                            |
| -------- | -------------------- | --------------------------- | -------- | ---------------------------------- |
| **E011** | STABLE only          | sub-grouped by futures_root | ERROR    | yes                                |
| **W003** | STABLE + COMING_SOON | sub-grouped by futures_root | WARNING  | no (unless `--warnings-as-errors`) |

Both rules consume the same `group_signatures` dict, populated once for all non-INACTIVE feeds with `state` stored alongside each entry. E011 filters entries to STABLE-only when computing the reference signature and when emitting findings. W003 uses all entries (STABLE + COMING_SOON) for both majority and firing.

### Coverage matrix

| Drift case                                      | E011                      | W003                      |
| ----------------------------------------------- | ------------------------- | ------------------------- |
| STABLE spot, intra-prefix                       | fires (ERROR)             | fires (WARNING)           |
| STABLE futures, intra-root                      | fires (ERROR)             | fires (WARNING)           |
| COMING_SOON spot drifts from STABLE majority    | silent                    | fires (WARNING)           |
| COMING_SOON futures drifts from STABLE majority | silent                    | fires (WARNING)           |
| Cross-prefix (Equity.JP vs Equity.US)           | silent (different groups) | silent (different groups) |
| Cross-root (Equity.US.EM* vs Equity.US.NQ*)     | silent (different groups) | silent (different groups) |

The existing futures-exemption in W003 (`is_future` flag, `if not is_future` filter) is removed. It was a workaround for the old too-broad `(asset_type,)` grouping; under the new prefix+root grouping, futures comparisons are well-bounded and the exemption is no longer needed.

### Intentional overlap

E011 and W003 deliberately overlap on STABLE feeds. The existing docs note: "They intentionally overlap. A future that disagrees with a sibling on the same root will fire E011 but not W003." Under this design, the overlap becomes symmetric across spot and futures, and W003 additionally covers COMING_SOON drift that E011 does not see.

## Behavior changes

### Newly silent (false positives removed)

- All ~620 non-US equity feeds stop firing E011/W003 against the US-majority schedule.

### Newly visible signal

- 4 of 104 `Equity.KR` feeds drift on session close time (`0900-1545` vs `0900-1530`) → E011 (STABLE) or W003 (COMING_SOON).
- 6 `Equity.IE` ETFs split across 3 listing-venue timezones (London / Paris / Zurich) → E011 fires on the 3 minority feeds.
- 1 `Equity.NL` ETF on `Europe/Berlin` differs from 4 on `Europe/Paris` → E011 fires on the 1 minority feed.
- COMING_SOON futures whose schedule drifts from STABLE peers in the same root → W003 fires (previously silent).

The IE/NL findings are arguably correct — multi-venue ETFs _do_ have different trading hours per listing — but surfacing them is the right behavior; operators can decide whether to split into separate feeds or accept the heterogeneity.

### No-longer-blocking

- COMING_SOON feeds with schedule drift now produce a W003 warning instead of an E011 error. CI is no longer blocked by COMING_SOON misconfiguration.

## Caveats

- `is_futures_symbol` has pre-existing false positives for German spot tickers matching the `[A-Z]+[FGHJKMNQUVXZ][0-9]` pattern (`DN3`, `HEN3`, `MUV2`, `PAH3`). Under this design these tickers each form a singleton "futures" subgroup `("equity", "DE", "<root>")`, so they neither fire nor cause spurious comparisons. Behavior matches today's accidental treatment. Out of scope for this change; tracked separately if pursued.

## Files changed

| File                        | Change                                                                                                                                                                                        |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lib/symbol_utils.py`       | Add `equity_listing_prefix()`                                                                                                                                                                 |
| `lib/config_lint.py`        | Update group key in `check_schedules`; split E011 (STABLE) and W003 (STABLE+COMING_SOON); remove `is_future` exemption in W003; update finding messages to include prefix/root in group label |
| `tests/test_config_lint.py` | Add cases for the new helper and the new grouping/state/severity behavior                                                                                                                     |
| `docs/config_linter.md`     | Update E011 / W003 rows + scope notes; refresh the "E011 vs W003" section                                                                                                                     |

## Test plan

`tests/test_symbol_utils.py` (new or existing):

- `equity_listing_prefix("Equity.US.AAPL/USD") == "US"`
- `equity_listing_prefix("Equity.JP.1305/JPY") == "JP"`
- `equity_listing_prefix("Equity.Index.TSLA/USD") == "Index"`
- `equity_listing_prefix("Crypto.BTC/USD") == ""`
- `equity_listing_prefix("Equity.US") == ""` (malformed, two segments)
- `equity_listing_prefix("") == ""`

`tests/test_config_lint.py`:

- E011 fires when 1 of 3 STABLE Equity.JP feeds has a different schedule signature.
- E011 does NOT fire when an Equity.JP feed disagrees with an Equity.US feed (different groups).
- E011 does NOT fire on a COMING_SOON-only drift (STABLE-only scope).
- E011 still fires on STABLE futures drift within the same `(asset_type, prefix, futures_root)`.
- E011 does NOT fire across different futures roots (`Equity.US.EMH6` vs `Equity.US.NQH6`).
- W003 fires for a COMING_SOON Equity.US feed that drifts from the STABLE Equity.US majority.
- W003 fires for a COMING_SOON futures feed that drifts from STABLE peers in the same root.
- W003 does NOT fire across different listing prefixes.
- `Equity.Index.*` does not group with `Equity.US.*` (no false E011/W003 between them even with identical schedules in different signatures).
- All pre-existing E011/W003 tests still pass after migration.

## Out of scope

- `is_futures_symbol` false positives on German spot tickers.
- Sub-grouping by timezone within a listing prefix (would silence the IE/NL multi-venue ETF findings, which we want to surface).
- Changes to other rules (E006, E010, E014, …).
- Changes to the CLI, output formats, or exit codes.

---

## Addendum (2026-04-28): Per-session comparison

The smoke test against the real `after.json` (rollout notes file: `2026-04-28-config-linter-intl-equities-rollout-notes.md`) revealed a design gap. `_get_schedule_signature` builds one tuple from a feed's entire `marketSchedules` list. Different feeds within `Equity.US` legitimately have different session sets (some are REGULAR-only, some are OVER_NIGHT-only, some carry all four). Whole-tuple comparison flagged 122 STABLE Equity.US feeds as drift — a CI blocker driven entirely by session-set differences rather than wrong schedules.

### Refinement

Replace whole-tuple comparison with per-session bucketing. The bucket key becomes:

```
bucket_key = group_key + (session,)
```

where `group_key` is unchanged (`("equity", prefix)`, `("equity", prefix, futures_root)`, `(asset_type, futures_root)`, or `(asset_type,)`), and `session` is whatever string appears in `marketSchedules[].session` (REGULAR, PRE_MARKET, POST_MARKET, OVER_NIGHT, …).

A feed appears once per session it has. A feed missing a session simply doesn't participate in that bucket — it incurs no penalty for the omission. (W001 still flags STABLE US equities missing extended sessions.)

### Rule semantics

- **E011** fires when a bucket has 2+ STABLE entries with 2+ distinct schedule strings. One finding is emitted per (feed, session) deviation. Message format:
  ```
  <SESSION> schedule disagrees with group (<group_label>): N distinct schedules across M STABLE feeds
  ```
- **W003** fires when a bucket has 2+ STABLE+COMING_SOON entries with a clear majority (i.e., the most common schedule has count ≥ 2). Message format:
  ```
  <SESSION> schedule deviates from (<group_label>) majority
  ```

`_get_schedule_signature` is removed; only the per-session bucketing remains.

### Behavior change matrix

| Case                                                                | Pre-refinement       | Post-refinement                          |
| ------------------------------------------------------------------- | -------------------- | ---------------------------------------- |
| Two feeds, all 4 sessions, REGULAR drifts                           | 1 finding (tuple)    | 1 finding (REGULAR)                      |
| REGULAR-only feed vs REGULAR+OVER_NIGHT feed, same REGULAR schedule | E011 fires (tuple ≠) | silent (per-session match)               |
| Two feeds with identical REGULAR but different OVER_NIGHT           | 1 finding (tuple)    | 1 finding tagged OVER_NIGHT              |
| Feed with 2 wrong sessions                                          | 1 finding            | 2 findings (one per session) — by design |

### Smoke-test prediction

The 122 Equity.US E011 findings should drop to a small residual — only feeds whose REGULAR/PRE_MARKET/POST_MARKET/OVER_NIGHT schedule disagrees with same-session peers in the US group. Comparable drop on the 131 Equity.US W003 findings.

### Test impact

All 14 tests added in the original design continue to pass under per-session bucketing (they are all single-session test cases). Three new tests are added to pin the per-session-set behavior:

- E011 silent when feeds have different session SETS but matching per-session schedules.
- E011 fires on per-session drift within a single session inside the US group.
- E011 fires on extended-session drift (e.g., OVER_NIGHT mismatch with REGULAR matched).

### Follow-up: Index sub-namespace generalization

The post-refinement smoke test surfaced 2 E011 + 3 W003 findings on `Metal.Index.*` and `FX.Index.*` feeds. These are the non-equity analogue of `Equity.Index.*` — a separate sub-namespace within the asset class with intentionally different schedules (always-open index quotes vs spot/continuous trading hours). The original design only special-cased `Equity.<X>.*` for sub-prefixing.

The follow-up extends the group-key construction with a generic Index branch:

```python
elif len(sym_parts) >= 3 and sym_parts[1] == "Index":
    group_key = (asset_type, "Index", futures_root(sym)) if is_futures_symbol(sym) else (asset_type, "Index")
```

After this branch, `Metal.Index.GOLD/USD` lands in `("metal", "Index")`, separate from `Metal.XAU/USD`'s `("metal",)` group. Same for `FX.Index.*` and any future `<AssetClass>.Index.*` namespace.

Test coverage: `TestIndexSubNamespaceGrouping` (3 tests).

### Files touched in the refinement

| File                                                                             | Change                                                                                                                             |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `lib/config_lint.py`                                                             | Replace whole-tuple `group_signatures` with per-session `session_groups`; update message format; remove `_get_schedule_signature`. |
| `tests/test_config_lint.py`                                                      | Add 3 new tests; existing 14 unchanged.                                                                                            |
| `docs/config_linter.md`                                                          | Refresh example output and the "E011 vs W003" section to mention per-session granularity.                                          |
| `docs/superpowers/specs/2026-04-28-config-linter-intl-equities-rollout-notes.md` | Re-run smoke test, replace contents with new findings.                                                                             |
