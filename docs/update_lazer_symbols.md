# Feed Promotion (update_lazer_symbols.py)

Promotes feeds from `COMING_SOON` to `STABLE` in a Lazer shard config (`after.json`). Uses a benchmark summary markdown as input to determine which tickers to promote and what publisher allowlists to set.

## Usage

```bash
# Dry run (preview changes without writing)
python3 update_lazer_symbols.py --summary feeds_ready_170226_summary.md --config after.json --dry-run

# Apply changes (creates backup at after.json.bak)
python3 update_lazer_symbols.py --summary feeds_ready_170226_summary.md --config after.json
```

## Arguments

| Argument | Description | Required |
|----------|-------------|----------|
| `--summary` | Path to feeds_ready summary markdown file | Yes |
| `--config` | Path to after.json config file | Yes |
| `--dry-run` | Print changes without writing to file | No |

## What It Does

For each ticker in the summary markdown:

1. Finds the matching feed in `after.json` by `metadata.name`
2. **Guard**: only modifies feeds where `state == "COMING_SOON"` (skips already-STABLE feeds)
3. Applies three changes per feed:
   - `state`: `"COMING_SOON"` -> `"STABLE"`
   - `allowedPublisherIds`: set to the ticker's consistent publishers (sorted integers)
   - `minPublishers`: set to `2`
4. Creates a backup at `{config}.bak` before writing

## Input Format

The summary markdown must contain a table in this format:

```
| # | Ticker | Consistent Publishers | Count | Additional (some days) |
|---|--------|----------------------|-------|------------------------|
| 1 | **AIQ** | 19, 21, 22, 65, 71 | 5 | 12, 26, 35, 44 |
| 2 | **AAPL** | 19, 21, 22 | 3 | 65 |
```

Only the "Consistent Publishers" column is used. The "Additional" column is ignored.

## Surgical JSON Modification

The script uses regex-based surgical replacements instead of `json.dumps` to preserve the original protobuf-JSON formatting of `after.json`. This avoids massive diffs when the file is reformatted.

Only the three target fields are changed per feed block; all other fields and formatting are preserved exactly.

## Safety Features

- `--dry-run` mode previews all changes without writing
- Backup created automatically before overwriting (`after.json.bak`)
- Only `COMING_SOON` feeds are modified (already-STABLE feeds are skipped with a log message)
- Handles feeds missing the `allowedPublisherIds` field by inserting it
- Warns about tickers not found in the config

## Output

Console output shows per-ticker results:

```
  OK: AAPL (feedId=922) -> STABLE, pubs=[19, 21, 22], minPub=2
  SKIP: AIQ (state=STABLE, not COMING_SOON)
  WARNING: XYZ not found in config

==================================================
SUMMARY
==================================================
  Modified:             95
  Skipped (not coming_soon): 3
  Not found in config:  0
  Total processed:      98/98
```

## Edge Cases

- **Duplicate feed names** (e.g., HODL has both US and CA feeds): the script uses last-match-wins for `metadata.name` lookups. Verify correct feed was promoted when duplicates exist.
- **Missing `allowedPublisherIds` field**: automatically inserted after the opening `{` of the feed block.

## Running Tests

```bash
pytest tests/test_update_lazer_symbols.py -v
```
