# Pyth Lazer Feed Benchmark Tool

A tool to evaluate Pyth Network Lazer publisher data quality against external benchmarks (Datascope).

## Prerequisites

- **Python 3.10+** installed on your system
- **ClickHouse database credentials** for both Lazer and Analytics clusters (ask your team lead)

## Quick Start

### Step 1: Clone or Download the Repository

```bash
cd /path/to/integration-benchmarking
```

### Step 2: Create a Virtual Environment

This keeps dependencies isolated from your system Python.

```bash
python3 -m venv venv
```

### Step 3: Activate the Virtual Environment

**Linux/macOS:**
```bash
source venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
venv\Scripts\activate.bat
```

**Windows (PowerShell):**
```powershell
venv\Scripts\Activate.ps1
```

You should see `(venv)` at the beginning of your terminal prompt when activated.

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Configure Database Credentials

1. Copy the sample config file:
   ```bash
   cp config.yaml.sample config.yaml
   ```

2. Open `config.yaml` in a text editor and fill in your credentials:
   ```yaml
   lazer_clickhouse_prod:
     host: your-lazer-host.clickhouse.cloud
     user: your_username
     password: your_password
     port: 9440

   analytics_clickhouse:
     host: your-analytics-host.clickhouse.cloud
     user: your_username
     password: your_password
     port: 9440
   ```

   > **Note:** Get these credentials from your team. Never commit `config.yaml` to git.

### Step 6: Run the Benchmark

**Option A: Process multiple feeds from a CSV file**
```bash
python quick_benchmark.py --csv price_id_list.csv
```

**Option B: Process a single feed**
```bash
python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx
```

## Input CSV Format

Create a CSV file with three columns (no header required):

```
feed_id,date,mode
327,2025-10-06,fx
340,2025-10-02,fx
346,2025-10-02,metals
1163,2025-10-02,us-equities
```

| Column | Description | Example Values |
|--------|-------------|----------------|
| feed_id | The Pyth Lazer feed ID | `327`, `1163` |
| date | Evaluation date | `2025-10-06` |
| mode | Market type | `fx`, `metals`, `us-equities` |

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--csv FILE` | CSV file with feeds to evaluate | - |
| `--feed-id ID` | Single feed ID | - |
| `--date DATE` | Date for single feed (YYYY-MM-DD) | - |
| `--mode MODE` | Market type: `fx`, `metals`, `us-equities` | - |
| `--output FILE` | Output CSV path | `quick_benchmark_results.csv` |
| `--target-pub-count N` | Min publishers needed for "ready" | `4` |
| `--workers N` | Parallel workers for faster processing | `4` |

## Understanding the Output

Results are saved to `quick_benchmark_results.csv` (or your specified output file):

| Column | Meaning |
|--------|---------|
| `feed_id` | The feed that was evaluated |
| `ready` | `True` if feed has enough passing publishers |
| `passing_pub_count` | Number of publishers that passed |
| `failing_pub_count` | Number of publishers that failed |
| `passing_publishers` | IDs of passing publishers (semicolon-separated) |
| `error` | Error message if evaluation failed |

### Pass/Fail Criteria

- **Publisher PASSES** if: `RMSE / spread <= 1.0`
- **Feed is READY** if: `passing_publishers >= target_pub_count` (default: 4)

## Examples

```bash
# Basic usage with CSV
python quick_benchmark.py --csv price_id_list.csv

# Faster processing with more workers
python quick_benchmark.py --csv price_id_list.csv --workers 8

# Custom output file
python quick_benchmark.py --csv price_id_list.csv --output my_results.csv

# Require 6 publishers instead of 4
python quick_benchmark.py --csv price_id_list.csv --target-pub-count 6

# Evaluate a single FX feed
python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx

# Evaluate a single metals feed
python quick_benchmark.py --feed-id 346 --date 2025-10-02 --mode metals

# Evaluate a single US equities feed
python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities
```

---

## Publisher Feeds Discovery Tool

A tool to discover all feeds that a specific publisher is currently publishing. Useful for understanding what data a publisher provides and generating input CSV files for benchmarking.

### What It Does

- Queries ClickHouse to find all feeds a publisher is actively publishing
- Returns feed IDs with their dates and asset classes
- Outputs in CSV format compatible with the benchmark tool

### Step-by-Step Usage

#### Step 1: Activate Your Virtual Environment

If not already activated:

**Linux/macOS:**
```bash
cd /path/to/integration-benchmarking
source venv/bin/activate
```

**Windows:**
```cmd
venv\Scripts\activate.bat
```

#### Step 2: Run the Script

**Basic usage - get all feeds for a publisher:**
```bash
python publisher_feeds.py --publisher-id 29
```

**Filter by asset class:**
```bash
python publisher_feeds.py --publisher-id 29 --asset-class metal
```

**Specify custom output file:**
```bash
python publisher_feeds.py --publisher-id 29 --output my_feeds.csv
```

**Use larger time window (for less active publishers):**
```bash
python publisher_feeds.py --publisher-id 32 --time-window 60
```

#### Step 3: Check the Output

Results are saved to `publisher_{id}_feeds.csv` (or your specified output file).

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--publisher-id ID` | Publisher ID to query (required) | - |
| `--output FILE` | Output CSV path | `publisher_{id}_feeds.csv` |
| `--time-window MIN` | Time window in minutes to look back | `1` |
| `--asset-class TYPE` | Filter by asset class | All |

### Available Asset Classes

| Asset Class | Description |
|-------------|-------------|
| `crypto` | Cryptocurrency pairs (BTC/USD, ETH/USD, etc.) |
| `fx` | Foreign exchange pairs |
| `metal` | Precious metals (XAU/USD, XAG/USD, etc.) |
| `commodity` | Commodities (oil, gas, etc.) |
| `equity-us` | US equities (NYSE, NASDAQ, AMEX) |
| `equity-gb` | UK equities (London Stock Exchange) |
| `equity-hk` | Hong Kong equities |
| `equity-jp` | Japanese equities (Tokyo Stock Exchange) |
| `equity-de` | German equities (Deutsche Börse) |
| `equity-{cc}` | Other equities by ISO country code |
| `rates` | Interest rates |
| `nav` | Net asset values |
| `crypto-redemption-rate` | Crypto redemption rates |
| `crypto-index` | Crypto index values |
| `funding-rate` | Funding rates |

> **Note:** Equities are categorized by country using ISO 3166-1 alpha-2 codes based on symbol suffix.
> Symbols without a suffix (e.g., `AAPL`, `MSFT`) default to `equity-us`.
> Symbols with exchange suffixes are mapped accordingly: `.L` → `equity-gb`, `.HK` → `equity-hk`, `.T` → `equity-jp`, etc.

### Output Format

The output CSV has three columns (no header):

```csv
price_id,date,asset_class
345,2026-01-23,metal
346,2026-01-23,metal
1163,2026-01-23,equity-us
1780,2026-01-23,equity-hk
```

| Column | Description |
|--------|-------------|
| `price_id` | The Pyth Lazer feed ID |
| `date` | Date when the publisher last published this feed |
| `asset_class` | Type of asset (crypto, fx, metal, equity-us, equity-gb, etc.) |

### Examples

```bash
# Get all feeds for publisher 29
python publisher_feeds.py --publisher-id 29

# Get only metal feeds for publisher 29
python publisher_feeds.py --publisher-id 29 --asset-class metal

# Get FX feeds with custom output
python publisher_feeds.py --publisher-id 29 --asset-class fx --output price_id_fx.csv

# Get US equities only
python publisher_feeds.py --publisher-id 11 --asset-class equity-us

# Get Hong Kong equities only
python publisher_feeds.py --publisher-id 11 --asset-class equity-hk

# Query a less active publisher with 1-hour window
python publisher_feeds.py --publisher-id 32 --time-window 60

# Query with 24-hour window (1440 minutes)
python publisher_feeds.py --publisher-id 32 --time-window 1440
```

### Using Output with Benchmark Tool

The output can be used directly as input for the benchmark tool:

```bash
# Generate metal feeds list
python publisher_feeds.py --publisher-id 29 --asset-class metal --output price_id_metal.csv

# Run benchmark on those feeds
python quick_benchmark.py --csv price_id_metal.csv
```

### Publisher Feeds Troubleshooting

#### "No feeds found for publisher X in the last Y minute(s)"

**Cause:** The publisher hasn't published any data in the specified time window.

**Solutions:**
1. Increase the time window:
   ```bash
   python publisher_feeds.py --publisher-id 32 --time-window 60
   ```
2. Check if the publisher is currently active. Some publishers only run during market hours.
3. Verify the publisher ID is correct.

#### "config.yaml not found"

**Cause:** The configuration file is missing.

**Solution:** Copy the sample config and add your credentials:
```bash
cp config.yaml.sample config.yaml
# Edit config.yaml with your ClickHouse credentials
```

#### "EOF occurred in violation of protocol"

**Cause:** The ClickHouse hostname in `config.yaml` is incorrect.

**Solution:** Double-check the `host` value under `lazer_clickhouse_prod` in `config.yaml`.

#### Connection timeout or slow response

**Cause:** ClickHouse cluster might be cold-starting or under heavy load.

**Solutions:**
1. Wait a minute and try again
2. The script has built-in timeouts (60s connect, 300s query) - these should be sufficient for most cases

#### Empty output with no error

**Cause:** The publisher exists but has no feeds matching your criteria.

**Solutions:**
1. Try without the `--asset-class` filter to see all feeds
2. Increase `--time-window` to capture older data
3. Verify the publisher ID is correct

#### "Error querying ClickHouse: ..."

**Cause:** Database connection or query error.

**Solutions:**
1. Check your network connection
2. Verify credentials in `config.yaml` are correct
3. Ensure the ClickHouse service is accessible from your network

---

## Troubleshooting

### "externally-managed-environment" error

Your system Python is protected. Make sure you created and activated the virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

### "config.yaml not found"

Copy the sample config and add your credentials:
```bash
cp config.yaml.sample config.yaml
# Edit config.yaml with your credentials
```

### "EOF occurred in violation of protocol"

The ClickHouse hostname is incorrect. Double-check the `host` values in `config.yaml`.

### "No publisher data found" or "No benchmark data found"

- Verify the feed_id exists in the system
- Verify the date has data available
- Verify the mode matches the feed type (fx, metals, or us-equities)

### Connection timeout

The ClickHouse cluster might be cold-starting. Wait a minute and try again, or increase the timeout by editing the script's `connect_timeout` value.

## Deactivating the Virtual Environment

When you're done, you can deactivate the virtual environment:
```bash
deactivate
```

## Running Again Later

Each time you open a new terminal, activate the virtual environment before running:
```bash
cd /path/to/integration-benchmarking
source venv/bin/activate  # Linux/macOS
python quick_benchmark.py --csv price_id_list.csv
```
