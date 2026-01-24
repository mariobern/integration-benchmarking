# Publisher Feeds Discovery Tool

Discovers all feeds that a specific publisher is currently publishing. Generates CSV files compatible with the benchmark tools.

## Usage

```bash
# Get all feeds for a publisher
python publisher_feeds.py --publisher-id 29

# Filter by asset class
python publisher_feeds.py --publisher-id 29 --asset-class metal

# Custom output file
python publisher_feeds.py --publisher-id 29 --output my_feeds.csv

# Larger time window for less active publishers
python publisher_feeds.py --publisher-id 32 --time-window 60
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--publisher-id` | Publisher ID to query (required) | - |
| `--output` | Output CSV path | `publisher_{id}_feeds.csv` |
| `--time-window` | Minutes to look back | 1 |
| `--asset-class` | Filter by asset class | All |
| `--date-offset` | Days to subtract from query date | 1 |

## Output Format

CSV with three columns (no header):

```csv
price_id,date,asset_class
345,2026-01-22,metal
346,2026-01-22,metal
1163,2026-01-22,equity-us
```

> **Note:** Date is offset by 1 day by default because benchmark data is typically available up to the previous day.

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
