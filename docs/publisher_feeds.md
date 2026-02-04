# Publisher Feeds Discovery Tool

Discovers all feeds that a specific publisher is publishing. Generates CSV files compatible with the benchmark tools.

## Usage

```bash
# Get all feeds a publisher published on a specific date
python publisher_feeds.py --publisher-id 29 --date 2026-01-28

# Filter by asset class
python publisher_feeds.py --publisher-id 29 --date 2026-01-28 --asset-class metal

# Custom output file
python publisher_feeds.py --publisher-id 29 --date 2026-01-28 --output my_feeds.csv

# Real-time discovery (current activity, last N minutes)
python publisher_feeds.py --publisher-id 29 --time-window 5
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--publisher-id` | Publisher ID to query (required) | - |
| `--date` | Target date (YYYY-MM-DD) to discover feeds published on that day | - |
| `--output` | Output CSV path | `publisher_{id}_feeds.csv` |
| `--asset-class` | Filter by asset class | All |
| `--time-window` | Minutes to look back (real-time mode, used when `--date` is not set) | 1 |
| `--date-offset` | Days to subtract from query date (real-time mode only) | 1 |

### Discovery Modes

- **Date-based** (`--date`): Queries `publisher_updates` for all feeds the publisher published on the specified date. This is the recommended mode for benchmarking, as it gives an accurate picture of what was actually published that day.
- **Real-time** (`--time-window`): Queries recent activity from `now()` minus the time window. Useful for checking what a publisher is currently publishing.

The daily batch runner uses date-based discovery automatically.

## Output Format

CSV with three columns (no header):

```csv
price_id,date,asset_class
345,2026-01-22,metal
346,2026-01-22,metal
1163,2026-01-22,equity-us
```

> **Note:** When using `--date`, the output date matches the target date. When using `--time-window`, the date is offset by `--date-offset` days (default 1) because benchmark data is typically available up to the previous day.

## Asset Classes

| Asset Class | Description |
|-------------|-------------|
| `crypto` | Cryptocurrency pairs |
| `fx` | Foreign exchange |
| `metal` | Precious metals |
| `commodity` | Commodities |
| `equity-us` | US equities |
| `equity-gb` | UK equities |
| `equity-hk` | Hong Kong equities |
| `equity-jp` | Japanese equities |
| `rates` | Interest rates |
| `nav` | Net asset values |
| `funding-rate` | Funding rates |

> Equities use ISO country codes based on symbol suffix (`.L` -> `equity-gb`, `.HK` -> `equity-hk`, etc.)

## Using with Benchmark Tools

```bash
# Generate feeds list for a specific date
python publisher_feeds.py --publisher-id 29 --date 2026-01-28 --asset-class metal

# Run benchmark on those feeds
python quick_benchmark.py --csv publisher_29_feeds.csv
# or
python publisher_benchmark.py --csv publisher_29_feeds.csv
```
