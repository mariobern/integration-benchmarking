# Pyth Lazer Feed Benchmark Tools

Evaluate Pyth Network Lazer publisher data quality against external benchmarks (Datascope).

## Prerequisites

- Python 3.10+
- ClickHouse database credentials (ask your team lead)

## Quick Start

```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# Windows: venv\Scripts\activate.bat

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp config.yaml.sample config.yaml
# Edit config.yaml with your ClickHouse credentials

# 4. Run a benchmark
python quick_benchmark.py --csv price_id_list.csv
```

## Tools

| Tool | Purpose | Documentation |
|------|---------|---------------|
| `quick_benchmark.py` | Evaluate all publishers for a feed (feed readiness) | [Details](docs/quick_benchmark.md) |
| `publisher_benchmark.py` | Evaluate a single publisher (faster) | [Details](docs/publisher_benchmark.md) |
| `publisher_feeds.py` | Discover feeds for a publisher | [Details](docs/publisher_feeds.md) |

## Input CSV Format

CSV with three columns (no header):

```csv
feed_id,date,mode
327,2025-10-06,fx
1163,2025-10-02,us-equities
346,2025-10-02,metals
```

## Pass/Fail Criteria

- **Publisher PASSES** if: `nrmse < 0.01` OR (`nrmse < 0.05` AND `hit_rate >= 98%`)
- **Feed is READY** if: `passing_publishers >= target_pub_count` (default: 4)

## Quick Examples

```bash
# Evaluate all publishers for feeds in a CSV
python quick_benchmark.py --csv price_id_list.csv

# Evaluate a single feed
python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx

# Evaluate one publisher across multiple feeds (faster)
python publisher_benchmark.py --csv publisher_55_feeds.csv

# Include extended hours for US equities (pre-market + after-hours)
python publisher_benchmark.py --csv publisher_55_feeds.csv --extended-hours

# Discover what feeds a publisher published on a specific date
python publisher_feeds.py --publisher-id 29 --date 2026-01-28

# List asset classes in a CSV (check what's benchmarkable)
python quick_benchmark.py --csv feeds.csv --list-asset-classes

# Filter to only benchmarkable asset classes
python quick_benchmark.py --csv feeds.csv --include-asset-class fx metals us-equities commodity
```

## Asset Classes

| Benchmarkable | Not Benchmarkable |
|---------------|-------------------|
| `fx`, `metals`, `us-equities`, `commodity` | `crypto`, `funding-rate`, `rates`, `nav` |

See [Asset Classes](docs/asset-classes.md) for futures support and details.

## Troubleshooting

See [Troubleshooting Guide](docs/troubleshooting.md) for common issues.

**Quick fixes:**
- `config.yaml not found` → `cp config.yaml.sample config.yaml`
- `EOF occurred in violation of protocol` → Check hostname in config.yaml
- `No benchmark data found` → Use `--list-asset-classes` to check availability
