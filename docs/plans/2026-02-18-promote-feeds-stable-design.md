# Design: Promote Ready Feeds to Stable

**Date:** 2026-02-18
**Status:** Approved

## Problem

98 US equity tickers in `feeds_ready_170226_summary.md` passed benchmark + uptime checks across 5 consecutive trading days (2026-02-09 to 2026-02-13). These feeds need to be promoted from `COMING_SOON` to `STABLE` in the Lazer config (`after.json`), with per-ticker `allowedPublisherIds` set to the consistent (all-5-days) publishers and `minPublishers` set to 2.

## Approach

A Python script (`update_lazer_symbols.py`) that:

1. Parses `feeds_ready_170226_summary.md` to extract the 98 tickers and their per-ticker consistent publisher ID lists
2. Loads `after.json` (the Lazer shard config)
3. For each ticker, finds the matching feed by `metadata.name`
4. Guards: only modifies feeds where `state == "COMING_SOON"`
5. Applies three changes per feed:
   - `state`: `"COMING_SOON"` -> `"STABLE"`
   - `allowedPublisherIds`: replaced with the ticker's consistent publishers (sorted integers)
   - `minPublishers`: set to `2`
6. Writes modified `after.json` (with backup to `after.json.bak`)
7. Prints summary of changes

## CLI

```bash
python3 update_lazer_symbols.py --summary feeds_ready_170226_summary.md --config after.json [--dry-run]
```

## Safety

- `--dry-run` mode: prints changes without writing
- Backup created before overwriting
- Only `COMING_SOON` feeds are modified (already-stable feeds are skipped)
- All 98 tickers validated as present in config

## Input Format

The markdown table in `feeds_ready_170226_summary.md`:
```
| # | Ticker | Consistent Publishers | Count | Additional (some days) |
|---|--------|----------------------|-------|------------------------|
| 1 | **AIQ** | 19, 21, 22, 65, 71 | 5 | 12, 26, 35, 44 |
```

## Output

Modified `after.json` with only the three fields changed per feed. All other fields preserved exactly.
