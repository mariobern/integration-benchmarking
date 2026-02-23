# Implementation Plan: Publisher Feeds Discovery Script

## Requirements Restatement

Build a script that:

1. Takes a **publisher_id** as input (e.g., publisher 32)
2. Queries ClickHouse to find **all feeds that publisher is publishing**
3. Uses data from the **last 1 minute** only
4. Outputs a CSV with 3 columns: `price_id`, `date`, `asset_class`
5. Output format similar to `price_id_metal.csv`

## Data Source Analysis

### Option 1: `feed_publisher_junction` table (RECOMMENDED)

- **Pros**: Pre-aggregated materialized view, very fast, tracks real-time publisher-feed relationships
- **Cons**: Uses `last_updated_at` for recency, may need FINAL for consistency
- **Query pattern**: Join with `feeds_metadata_latest` for asset_type

### Option 2: `publisher_updates` table (ALTERNATIVE)

- **Pros**: Raw data, can filter by exact time window (last 1 minute)
- **Cons**: Much larger table, slower for aggregation, billions of rows
- **Query pattern**: DISTINCT price_feed_id with time filter, join with feeds_metadata

### Recommendation

Use **`feed_publisher_junction`** as primary source because:

1. Already aggregated per publisher-feed pair
2. Has `last_updated_at` timestamp for recency filtering
3. Much faster than scanning `publisher_updates`
4. Real-time materialized view, updates continuously

However, to strictly satisfy "last 1 minute" requirement, we can either:

- Filter `feed_publisher_junction WHERE last_updated_at >= now() - INTERVAL 1 MINUTE`
- Or scan `publisher_updates` with time filter (slower but precise)

**Final choice**: Use `feed_publisher_junction` with recency filter. If empty, fall back to `publisher_updates`.

## Schema Mapping

| Output Column | Source                                                                 |
| ------------- | ---------------------------------------------------------------------- |
| `price_id`    | `feed_publisher_junction.feed_id`                                      |
| `date`        | `toDate(feed_publisher_junction.last_updated_at)`                      |
| `asset_class` | `feeds_metadata_latest.asset_type` (JOIN on `pyth_lazer_id = feed_id`) |

### Asset Type Values (from DB)

- crypto, fx, metal, commodity, equity, rates, nav, crypto-redemption-rate, crypto-index, funding-rate, kalshi, custom

## Implementation Phases

### Phase 1: Core Script Structure

1. Create `publisher_feeds.py` with argparse for CLI
2. Load config from `config.yaml` (reuse existing pattern)
3. Connect to Lazer ClickHouse (same as `quick_benchmark.py`)

### Phase 2: Query Implementation

1. Primary query using `feed_publisher_junction`:

   ```sql
   SELECT
       fpj.feed_id AS price_id,
       toDate(fpj.last_updated_at) AS date,
       fm.asset_type AS asset_class
   FROM feed_publisher_junction fpj
   FINAL
   LEFT JOIN feeds_metadata_latest fm ON fpj.feed_id = fm.pyth_lazer_id
   WHERE fpj.publisher_id = {publisher_id}
     AND fpj.last_updated_at >= now() - INTERVAL 1 MINUTE
   ORDER BY fm.asset_type, fpj.feed_id
   ```

2. Fallback query using `publisher_updates` (if junction returns nothing):
   ```sql
   SELECT DISTINCT
       pu.price_feed_id AS price_id,
       toDate(pu.publish_time) AS date,
       fm.asset_type AS asset_class
   FROM publisher_updates pu
   LEFT JOIN feeds_metadata_latest fm ON pu.price_feed_id = fm.pyth_lazer_id
   WHERE pu.publisher_id = {publisher_id}
     AND pu.publish_time >= now() - INTERVAL 1 MINUTE
   ORDER BY fm.asset_type, pu.price_feed_id
   ```

### Phase 3: Output Generation

1. Write results to CSV with header: `price_id,date,asset_class`
2. Default output filename: `publisher_{id}_feeds.csv`
3. Allow custom output path via `--output` flag

### Phase 4: CLI Arguments

| Argument         | Description            | Required                                 |
| ---------------- | ---------------------- | ---------------------------------------- |
| `--publisher-id` | Publisher ID to query  | Yes                                      |
| `--output`       | Output CSV path        | No (default: `publisher_{id}_feeds.csv`) |
| `--time-window`  | Time window in minutes | No (default: 1)                          |
| `--asset-class`  | Filter by asset class  | No (all by default)                      |

## Expected Output Example

```csv
price_id,date,asset_class
345,2026-01-23,metal
346,2026-01-23,metal
1780,2026-01-23,metal
1781,2026-01-23,metal
327,2026-01-23,fx
328,2026-01-23,fx
```

## Risks & Mitigations

| Risk                                | Likelihood | Mitigation                                   |
| ----------------------------------- | ---------- | -------------------------------------------- |
| Publisher not active in last minute | Medium     | Fallback to larger time window, show warning |
| feed_publisher_junction stale       | Low        | Fallback to publisher_updates                |
| Large number of feeds (>10k)        | Low        | Add pagination/limit option                  |
| Missing asset_type metadata         | Low        | Show "unknown" for NULL asset_type           |

## Testing Plan

1. Test with known active publisher (e.g., publisher 11, 19, 29)
2. Test with inactive publisher (e.g., publisher 32)
3. Test asset-class filter functionality
4. Verify output matches expected CSV format

## Files to Create

1. `publisher_feeds.py` - Main script

## Dependencies

- Uses existing `config.yaml` configuration
- Requires `clickhouse_connect` and `pyyaml` (already in requirements.txt)
