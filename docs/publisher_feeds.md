# Publisher Feeds Discovery Tool

Discovers all feeds that a specific publisher is publishing. Generates CSV files compatible with the benchmark tools.

## Usage

```bash
# Get all feeds a publisher is currently publishing
python publisher_feeds.py --publisher-id 29

# Use a larger time window (5 minutes)
python publisher_feeds.py --publisher-id 29 --time-window 5

# Filter by asset class
python publisher_feeds.py --publisher-id 29 --asset-class metal

# Custom output file
python publisher_feeds.py --publisher-id 29 --output my_feeds.csv
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--publisher-id` | Publisher ID to query (required) | - |
| `--output` | Output CSV path | `publisher_{id}_feeds.csv` |
| `--asset-class` | Filter by asset class | All |
| `--time-window` | Minutes to look back for recent activity | 1 |
| `--date-offset` | Days to subtract from query date for benchmark data availability | 1 |

### How Discovery Works

The script queries `feed_publisher_junction` (a small pre-aggregated metadata table) for feeds with recent activity within the time window. If no results are found, it falls back to querying `publisher_updates` with the same time window.

The daily batch runner uses this same approach with a 60-minute time window for broader publisher coverage.

## Output Format

CSV with three columns (no header):

```csv
price_id,date,asset_class
345,2026-01-22,metal
346,2026-01-22,metal
1163,2026-01-22,equity-us
```

> **Note:** The output date is offset by `--date-offset` days (default 1) because benchmark data is typically available up to the previous day.

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
# Generate feeds list
python publisher_feeds.py --publisher-id 29 --asset-class metal

# Run benchmark on those feeds
python quick_benchmark.py --csv publisher_29_feeds.csv
# or
python publisher_benchmark.py --csv publisher_29_feeds.csv
```
