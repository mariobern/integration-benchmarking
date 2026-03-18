# Design: update_min_publishers — Automated minPublishers Enforcement

**Date:** 2026-03-18
**Status:** Draft
**Approach:** Standalone script (Approach A)

## Problem

Many feeds in `after.json` have `minPublishers: 1`, which allows a feed to remain online with only a single publisher. This creates price bias risk — the feed reflects one publisher's price rather than a consensus view of the market.

As of 2026-03-18, there are **830 STABLE feeds** in after.json. After excluding non-benchmarkable asset types (34 feeds) and extended-hours equities (81 feeds), **715 non-extended STABLE feeds** are eligible for evaluation. Of these, **102 need adjustment**: 88 feeds with `minPublishers: 1` (73 equity, 12 commodity, 3 crypto) and 14 feeds with `minPublishers: 2` that have 7+ publishers (target: 3). The remaining 613 already meet or exceed their target.

The 67 extended-hours equities with top-level `minPublishers: 1` are excluded — this value is intentional (see "Scope" section).

## Solution

A standalone script (`update_min_publishers.py`) that enforces a minimum `minPublishers` value based on the number of `allowedPublisherIds` for each feed.

## Rule Engine

| `allowedPublisherIds` count | Target `minPublishers` |
|-----------------------------|------------------------|
| 0-1                         | Skip (flag as NEEDS_ATTENTION) |
| 2-6                         | 2 |
| 7+                          | 3 |

The boundary (default: 7) is configurable via `--publisher-tier-cutoff`.

**No-downgrade rule:** Only increase `minPublishers`. The comparison uses the **parsed JSON** top-level `minPublishers` value (from `json.load()`), not any regex-matched value. If a feed already has `minPublishers` >= the target, it is skipped.

## Eligibility Filters

1. **State:** `STABLE` only (skip `COMING_SOON` and `INACTIVE`)
2. **Asset type exclusion:** Default exclusion list: `funding-rate`, `crypto-redemption-rate`, `nav`, `custom`, `crypto-index`, `kalshi`
3. **Asset type override:** `--asset-classes` flag acts as an **explicit allowlist** — only the listed asset types are processed; all others are skipped (bypasses the default exclusion list)
4. **Publisher count:** Feeds with fewer than 2 `allowedPublisherIds` are skipped and flagged as `NEEDS_ATTENTION`

## Scope: What Gets Modified

`after.json` has `minPublishers` at two levels:

- **Top-level:** Default for feeds without per-session overrides (crypto, fx, metal, commodity, rates, basic equities)
- **Per-session:** Inside `marketSchedules` entries for extended-hours US equities (REGULAR, PRE_MARKET, POST_MARKET, OVER_NIGHT). Session-specific values **override** the top-level value when present.

### Extended-hours equities are excluded from scope

Extended-hours equities (feeds with PRE_MARKET/POST_MARKET/OVER_NIGHT sessions in `marketSchedules`) are **entirely excluded** from modification. Reasons:

1. Their top-level `minPublishers: 1` is **intentional** — `update_config_from_summary.py` deliberately sets it to 1 because session-specific values override it.
2. Their REGULAR session `minPublishers` values are already correct (78 at 3, 3 at 2 — zero have `minPublishers: 1`).
3. Modifying the top-level value could interfere with the session override mechanism.

### Modification rules:

| Feed type | What to modify | Publisher count source |
|-----------|----------------|----------------------|
| Non-extended (crypto, fx, metal, commodity, rates, basic equities) | Top-level `minPublishers` | Top-level `allowedPublisherIds` |
| Extended-hours equities | **No modification** (excluded from scope) | — |

## CLI Interface

```
python3 update_min_publishers.py --config after.json [options]
```

### Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--config` | Yes | — | Path to the JSON config file |
| `--dry-run` | No | False | Preview changes without writing |
| `--output-csv` | No | `min_publishers_changes.csv` | Path for the change report CSV |
| `--asset-classes` | No | — | Explicit allowlist of asset types to process (overrides default exclusion list) |
| `--publisher-tier-cutoff` | No | 7 | Publisher count boundary: below → minPublishers=2, at or above → minPublishers=3 |

## CSV Report

Written in both dry-run and real mode for audit trail.

**Columns:** `feed_id, symbol, asset_type, old_min_publishers, new_min_publishers, allowed_publisher_count, status`

**`status` values:**
- `UPDATED` — minPublishers was increased
- `SKIPPED_EQUAL` — existing minPublishers already equals target
- `SKIPPED_HIGHER` — existing minPublishers exceeds target
- `NEEDS_ATTENTION` — fewer than 2 allowedPublisherIds

## Console Output

### Dry-run mode:
```
Scanning after.json...
  STABLE feeds: 830
  Excluded (asset type): 34 (funding-rate: 11, crypto-redemption-rate: 15, nav: 3, custom: 5)
  Excluded (extended-hours): 81
  Needs attention (<2 publishers): 0
  Eligible: 715

Changes:
  56 feeds: minPublishers 1 → 2 (< 7 publishers)
  32 feeds: minPublishers 1 → 3 (>= 7 publishers)
  14 feeds: minPublishers 2 → 3 (>= 7 publishers)
  613 feeds: skipped (already >= target)

[DRY RUN] No changes written. Review: min_publishers_changes.csv
```

### Write mode:
```
Backup: after.json.bak
Updated 102 feeds in after.json
Report: min_publishers_changes.csv
```

## JSON Modification Strategy

Follow the same surgical regex approach as existing scripts (`update_config_from_summary.py`, `update_lazer_symbols.py`):

1. **Parse with `json.load()`** to iterate feeds, determine eligibility, and compute target values
2. **Read file as raw string** for modifications (preserves exact formatting)
3. **Locate feed blocks** by searching for `"feedId": <id>` and tracking bracket depth
4. **Target the top-level `minPublishers` only:** Find the end position of the `marketSchedules` array within the feed block (by bracket-depth tracking), then apply the regex substitution only to the portion of the block **after** `marketSchedules` ends. This avoids accidentally modifying any session-level `minPublishers` that appears inside `marketSchedules`.
   - Regex: `re.sub(r'"minPublishers": \d+', f'"minPublishers": {new_val}', post_market_schedules_text, count=1)`
   - If no `marketSchedules` key exists, apply to the entire feed block with `count=1`
5. **Backup** original file to `<filename>.bak` before writing

No JSON re-serialization — output diff only shows `minPublishers` value changes.

**Idempotency:** Running the script twice produces no changes on the second run (all feeds will be SKIPPED_EQUAL or SKIPPED_HIGHER).

## File Structure

| File | Purpose |
|------|---------|
| `update_min_publishers.py` | Thin CLI wrapper (argparse + delegation to lib) |
| `lib/min_publishers.py` | Core logic: rule engine, eligibility checks, change computation, JSON modification |
| `tests/test_min_publishers.py` | Unit tests |

## Test Coverage

Tests in `tests/test_min_publishers.py`:

1. **Rule engine:** <7 publishers → 2, >=7 publishers → 3
2. **Rule engine — custom cutoff:** `--publisher-tier-cutoff 5` changes the boundary
3. **No-downgrade:** existing minPublishers=3 with 5 publishers stays at 3
4. **Eligibility — state:** only STABLE feeds processed
5. **Eligibility — exclusion list:** funding-rate, crypto-redemption-rate, nav, custom, crypto-index, kalshi skipped
6. **Eligibility — asset class allowlist:** `--asset-classes` overrides default exclusion
7. **Eligibility — NEEDS_ATTENTION:** feeds with <2 publishers flagged (both empty array and missing key)
8. **Extended-hours exclusion:** feeds with PRE_MARKET/POST_MARKET/OVER_NIGHT sessions are entirely skipped
9. **Non-extended feeds — top-level only:** top-level minPublishers modified, session-level minPublishers inside marketSchedules untouched
10. **Regex targeting:** for feeds with minPublishers in both marketSchedules and top-level, only the top-level value is changed
11. **Dry-run:** no file modification occurs
12. **CSV report:** correct columns, values, and all statuses represented
13. **Upgrade 2 → 3:** feed with minPublishers=2 and 8 publishers gets upgraded to minPublishers=3
14. **Backup:** original file backed up before writing
15. **Idempotency:** running the script twice produces no changes on the second run

## Edge Cases

- **Feed with `minPublishers` in both `marketSchedules[0]` and top-level:** The regex targets only the top-level value by operating on the text after the `marketSchedules` array. 37 of the 88 eligible feeds have this dual structure.
- **Feed with no `allowedPublisherIds` key:** Treated as 0 publishers → NEEDS_ATTENTION
- **Feed with empty `allowedPublisherIds` array `[]`:** Treated as 0 publishers → NEEDS_ATTENTION
- **Feed with no `marketSchedules`:** Treated as non-extended, top-level modification applies to entire block
- **Custom symbol prefix (e.g., `Custom.PRF1/USD`):** Caught by `custom` in exclusion list via `asset_type` metadata

## Asset Type Values Reference

Exact `metadata.asset_type` values in after.json: `crypto`, `equity`, `fx`, `metal`, `commodity`, `rates`, `funding-rate`, `crypto-redemption-rate`, `nav`, `custom`, `crypto-index`, `kalshi`. The `--asset-classes` flag and default exclusion list use these exact values.
