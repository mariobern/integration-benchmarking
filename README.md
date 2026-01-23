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
| `--include-asset-class CLASS [CLASS ...]` | Only process these asset classes | All |
| `--exclude-asset-class CLASS [CLASS ...]` | Skip these asset classes | None |
| `--list-asset-classes` | List asset classes in CSV and exit | - |

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

## Asset Class Filtering

CSV files may contain feeds from multiple asset classes, but not all asset classes have benchmark data available. Use the filtering options to process only supported asset classes.

### Discovering Asset Classes

First, check what asset classes are in your CSV file:

```bash
python quick_benchmark.py --csv publisher_11_feeds.csv --list-asset-classes
```

Output:
```
Asset classes in publisher_11_feeds.csv:
==================================================
  crypto                      494 feeds  [benchmarkable: N]
  crypto-redemption-rate      145 feeds  [benchmarkable: N]
  fx                           50 feeds  [benchmarkable: Y]
  equity-us                    29 feeds  [benchmarkable: Y]
  rates                        15 feeds  [benchmarkable: N]
  commodity                    11 feeds  [benchmarkable: Y]
  funding-rate                  9 feeds  [benchmarkable: N]
  metal                         2 feeds  [benchmarkable: Y]
  nav                           1 feeds  [benchmarkable: N]
==================================================
  TOTAL                       756 feeds

Benchmarkable asset classes: commodity, fx, metals, us-equities
```

### Asset Classes with Benchmark Data

| Asset Class | Has Benchmark Data |
|-------------|-------------------|
| `fx` | Yes |
| `metals` / `metal` | Yes |
| `us-equities` / `equity-us` | Yes |
| `commodity` | Yes |
| `crypto` | No |
| `crypto-redemption-rate` | No |
| `funding-rate` | No |
| `rates` | No |
| `nav` | No |

### Filtering Examples

```bash
# Include only benchmarkable asset classes
python quick_benchmark.py --csv feeds.csv --include-asset-class fx metals us-equities commodity

# Exclude asset classes without benchmark data
python quick_benchmark.py --csv feeds.csv --exclude-asset-class crypto crypto-redemption-rate funding-rate rates nav

# Process only FX feeds
python quick_benchmark.py --csv feeds.csv --include-asset-class fx

# Process FX and metals only
python quick_benchmark.py --csv feeds.csv --include-asset-class fx metals metal
```

> **Note:** Asset class names are normalized automatically. For example, `metal` and `metals` are treated as the same, as are `equity-us` and `us-equities`.

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

# List asset classes in a CSV file
python quick_benchmark.py --csv publisher_11_feeds.csv --list-asset-classes

# Process only FX and metals feeds from a mixed CSV
python quick_benchmark.py --csv publisher_11_feeds.csv --include-asset-class fx metals

# Exclude crypto feeds (no benchmark data available)
python quick_benchmark.py --csv publisher_11_feeds.csv --exclude-asset-class crypto crypto-redemption-rate
```

---

## Single Publisher Benchmark Tool

A faster benchmark tool for evaluating a **single publisher's** data quality. Use this when you only need to evaluate one publisher instead of all publishers for a feed.

### When to Use This Tool

| Scenario | Use This Tool |
|----------|---------------|
| Evaluate one specific publisher | `publisher_benchmark.py` ✓ |
| Check if a feed has enough publishers | `quick_benchmark.py` |
| Onboard a new publisher | `publisher_benchmark.py` ✓ |
| Full feed readiness assessment | `quick_benchmark.py` |

### Why It's Faster

- `quick_benchmark.py` queries **all publishers** for each feed (slower, gives feed readiness)
- `publisher_benchmark.py` queries **one publisher** only (faster, gives publisher quality)

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

#### Step 2: Prepare Your Input CSV

Create or use a CSV file with three columns (no header):

```csv
feed_id,date,mode
327,2025-10-06,fx
340,2025-10-02,fx
346,2025-10-02,metals
```

#### Step 3: Run the Benchmark

**Option A: Use filename convention (recommended)**

Name your file `publisher_{id}_feeds.csv` and the script extracts the publisher ID automatically:

```bash
python publisher_benchmark.py --csv publisher_55_feeds.csv
```

**Option B: Specify publisher ID explicitly**

```bash
python publisher_benchmark.py --csv feeds.csv --publisher-id 55
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--csv FILE` | CSV file with feeds to evaluate (required) | - |
| `--publisher-id ID` | Publisher ID to evaluate | Extracted from filename |
| `--output FILE` | Output CSV path | `publisher_{id}_benchmark_results.csv` |
| `--workers N` | Parallel workers for faster processing | `4` |
| `--include-asset-class CLASS [CLASS ...]` | Only process these asset classes | All |
| `--exclude-asset-class CLASS [CLASS ...]` | Skip these asset classes | None |
| `--list-asset-classes` | List asset classes in CSV and exit | - |

### Understanding the Output

Results are saved to `publisher_{id}_benchmark_results.csv` (or your specified output file):

| Column | Meaning |
|--------|---------|
| `publisher_id` | The publisher that was evaluated |
| `feed_id` | The feed that was evaluated |
| `date` | Evaluation date |
| `mode` | Asset class (fx, metals, etc.) |
| `symbol` | Feed symbol (e.g., EUR/USD) |
| `passes` | `True` if RMSE/spread ≤ 1.0 |
| `n_observations` | Number of matched data points |
| `rmse` | Root Mean Square Error vs benchmark |
| `mean_spread` | Average benchmark spread |
| `rmse_over_spread` | RMSE divided by spread (pass threshold: ≤ 1.0) |
| `error` | Error message if evaluation failed |
| `execution_time_ms` | Processing time in milliseconds |

### Pass/Fail Criteria

- **Publisher PASSES** if: `rmse_over_spread <= 1.0`
- Minimum 100 observations required for valid evaluation

### Examples

```bash
# Basic usage with filename convention
python publisher_benchmark.py --csv publisher_55_feeds.csv

# Explicit publisher ID
python publisher_benchmark.py --csv feeds.csv --publisher-id 55

# Faster processing with more workers
python publisher_benchmark.py --csv publisher_55_feeds.csv --workers 8

# Custom output file
python publisher_benchmark.py --csv publisher_55_feeds.csv --output results.csv

# List asset classes first
python publisher_benchmark.py --csv publisher_55_feeds.csv --list-asset-classes

# Only evaluate FX and metals feeds
python publisher_benchmark.py --csv publisher_55_feeds.csv --include-asset-class fx metals

# Exclude unsupported asset classes
python publisher_benchmark.py --csv publisher_55_feeds.csv --exclude-asset-class crypto funding-rate rates
```

### Complete Workflow Example

```bash
# 1. Discover what feeds a publisher has
python publisher_feeds.py --publisher-id 55

# 2. Check what asset classes are benchmarkable
python publisher_benchmark.py --csv publisher_55_feeds.csv --list-asset-classes

# 3. Run benchmark on supported asset classes only
python publisher_benchmark.py --csv publisher_55_feeds.csv --include-asset-class fx metals us-equities commodity

# 4. Check results
cat publisher_55_benchmark_results.csv
```

### Publisher Benchmark Troubleshooting

#### "Could not extract publisher ID from filename"

**Cause:** Your CSV filename doesn't match the expected pattern.

**Solutions:**
1. Rename your file to `publisher_{id}_feeds.csv` (e.g., `publisher_55_feeds.csv`)
2. Or use `--publisher-id` explicitly:
   ```bash
   python publisher_benchmark.py --csv my_feeds.csv --publisher-id 55
   ```

#### "No publisher data found for publisher X"

**Cause:** The publisher didn't publish any data for this feed on this date.

**Solutions:**
1. Verify the publisher ID is correct
2. Verify the publisher was active on the specified date
3. Check if the feed ID is correct

#### "Insufficient observations (N < 100)"

**Cause:** Not enough data points matched between publisher and benchmark.

**Solutions:**
1. This can happen during market closures or partial trading days
2. Try a different date with full market hours
3. Check if the benchmark data exists for this feed/date

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
| `--date-offset DAYS` | Days to subtract from query date (for benchmark data availability) | `1` |

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
345,2026-01-22,metal
346,2026-01-22,metal
1163,2026-01-22,equity-us
1780,2026-01-22,equity-hk
```

| Column | Description |
|--------|-------------|
| `price_id` | The Pyth Lazer feed ID |
| `date` | Date for benchmarking (query date minus `--date-offset`, default 1 day) |
| `asset_class` | Type of asset (crypto, fx, metal, equity-us, equity-gb, etc.) |

> **Note:** The date is offset by default because Datascope benchmark data is typically only available up to the previous day. If you run the script on 2026-01-23, the output dates will be 2026-01-22 by default. Use `--date-offset 0` if you need same-day dates.

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

# Use 2-day offset for older benchmark data
python publisher_feeds.py --publisher-id 29 --date-offset 2

# No date offset (same day as query)
python publisher_feeds.py --publisher-id 29 --date-offset 0
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
- For CSV files with mixed asset classes, use `--list-asset-classes` to check which have benchmark data:
  ```bash
  python quick_benchmark.py --csv your_file.csv --list-asset-classes
  ```
- Use `--include-asset-class` to filter to only benchmarkable asset classes:
  ```bash
  python quick_benchmark.py --csv your_file.csv --include-asset-class fx metals us-equities commodity
  ```

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
