# Volume Profile Tool

Assesses **liquidity profile** of US equities by computing per-session trading volume and classifying tickers into liquidity tiers. Supports both Datascope-onboarded feeds and non-onboarded tickers (via yfinance fallback).

## When to Use

| Scenario                                                  | Use This Tool                                       |
| --------------------------------------------------------- | --------------------------------------------------- |
| Evaluate whether a ticker has enough liquidity for launch | Yes                                                 |
| Check if extended-hours sessions are viable for a ticker  | Yes                                                 |
| Compare liquidity across many tickers at once             | Yes                                                 |
| Evaluate price quality or publisher performance           | Use `feed_readiness.py` or `publisher_benchmark.py` |

## Usage

```bash
# From ticker list
python3 volume_profile.py --tickers AAPL,MSFT,NVDA --date 2026-03-04

# From file (one ticker per line)
python3 volume_profile.py --ticker-file us_equity_tickers.txt --date 2026-03-04

# Multi-day average (up to 5 days)
python3 volume_profile.py --tickers AAPL,MSFT --date 2026-03-04 --days 5

# Custom output path
python3 volume_profile.py --tickers AAPL --date 2026-03-04 --output output_csv/vol.csv
```

## Arguments

| Argument        | Description                           | Default                                    |
| --------------- | ------------------------------------- | ------------------------------------------ |
| `--tickers`     | Comma-separated ticker list           | -                                          |
| `--ticker-file` | Text file, one ticker per line        | -                                          |
| `--date`        | Reference trading date (`YYYY-MM-DD`) | Yesterday                                  |
| `--days`        | Trading days to average (1-5)         | `1`                                        |
| `--output`      | CSV output path                       | `output_csv/volume_profile_YYYY-MM-DD.csv` |

Either `--tickers` or `--ticker-file` is required (mutually exclusive).

## Data Sources

Tickers are resolved against Lazer `feeds_metadata_latest`. The data source depends on whether a ticker has a `pyth_lazer_id`:

| Source    | When Used                     | Volume Coverage                              | Limitations                                |
| --------- | ----------------------------- | -------------------------------------------- | ------------------------------------------ |
| Datascope | Ticker resolves to Lazer feed | Real share volume per tick, all sessions     | None (primary source)                      |
| yfinance  | Ticker not in Lazer           | Regular session measured; extended estimated | 60-day lookback, rate limits, no overnight |

The `data_source` column in the output indicates provenance per row.

### yfinance Extended-Hours Volume Estimation

yfinance 5-minute bars return volume only for the regular session (pre-market and after-hours volume is always 0). To estimate extended-hours volume:

1. Fetch daily (1d) total volume — includes all sessions
2. Fetch 5-minute regular session volume — accurate
3. **Extended volume** = `daily_vol - regular_vol`
4. Split between pre-market and after-hours proportionally by **active bar count** (bars with price change in each session)

This is an estimate, not measured volume. The `pre_price_activity` and `ah_price_activity` columns indicate how actively a ticker trades in each session (fraction of bars with price movement, 0.0 to 1.0).

## Session Boundaries

| Session     | Time (ET)         | Datascope       | yfinance             |
| ----------- | ----------------- | --------------- | -------------------- |
| Pre-market  | 4:00 AM - 9:30 AM | Measured        | Estimated from delta |
| Regular     | 9:30 AM - 4:00 PM | Measured        | Measured             |
| After-hours | 4:00 PM - 8:00 PM | Measured        | Estimated from delta |
| Overnight   | 8:00 PM - 4:00 AM | Lazer obs count | N/A                  |

UTC boundaries are computed dynamically to handle EST/EDT transitions.

## Liquidity Tiers

Based on total daily dollar volume (`close_price × total_vol`):

| Tier   | Threshold   | Meaning                          |
| ------ | ----------- | -------------------------------- |
| HIGH   | >= $50M/day | Very liquid, institutional-grade |
| MEDIUM | $5M - $50M  | Moderately liquid                |
| LOW    | < $5M       | Thin liquidity                   |

## Session Recommendations

Informational labels based on tier, after-hours percentage, and overnight observations:

| Condition                                 | Recommendation              |
| ----------------------------------------- | --------------------------- |
| HIGH tier + AH > 1% + overnight obs > 100 | 24/5 viable                 |
| HIGH tier + AH > 1%                       | Regular + Extended          |
| MEDIUM tier + AH > 0.5%                   | Regular + Extended (review) |
| Everything else                           | Regular only                |

These are not hard pass/fail gates — they are directional guidance for release decisions.

## Output

### CSV Columns

| Column                    | Type      | Description                                                    |
| ------------------------- | --------- | -------------------------------------------------------------- |
| `ticker`                  | str       | Stock ticker                                                   |
| `pyth_lazer_id`           | int/blank | Feed ID (blank for yfinance-only tickers)                      |
| `date`                    | str       | Trading date                                                   |
| `close_price`             | float     | Last trade price near 4 PM ET                                  |
| `pre_market_vol`          | int       | Shares traded 4:00-9:30 AM ET                                  |
| `pre_market_dollar_vol`   | float     | close_price × pre_market_vol                                   |
| `regular_vol`             | int       | Shares traded 9:30 AM-4:00 PM ET                               |
| `regular_dollar_vol`      | float     | close_price × regular_vol                                      |
| `after_hours_vol`         | int       | Shares traded 4:00-8:00 PM ET                                  |
| `after_hours_dollar_vol`  | float     | close_price × after_hours_vol                                  |
| `overnight_benchmark_obs` | int/blank | Publisher update count 8 PM-4 AM ET (Datascope tickers only)   |
| `total_vol`               | int       | pre + regular + after_hours                                    |
| `total_dollar_vol`        | float     | close_price × total_vol                                        |
| `pre_pct`                 | float     | pre_market_vol / total_vol × 100                               |
| `regular_pct`             | float     | regular_vol / total_vol × 100                                  |
| `after_hours_pct`         | float     | after_hours_vol / total_vol × 100                              |
| `pre_price_activity`      | float     | Fraction of pre-market bars with price change (yfinance only)  |
| `ah_price_activity`       | float     | Fraction of after-hours bars with price change (yfinance only) |
| `liquidity_tier`          | str       | HIGH / MEDIUM / LOW                                            |
| `session_recommendation`  | str       | Informational label                                            |
| `data_source`             | str       | `datascope` or `yfinance`                                      |
| `days_sampled`            | int       | Number of days averaged (multi-day mode only)                  |

### HTML Report

A self-contained `.html` file is generated alongside the CSV (same path, `.html` extension). No external dependencies.

Includes:

- **Summary bar** — count of tickers per liquidity tier
- **Sortable table** — click column headers to sort, search box to filter by ticker
- **Session proportion bars** — CSS-only horizontal bars showing pre/regular/AH volume split
- **Decision matrix** — reference table with tier thresholds and recommendation guide

### Console Summary

Printed to stderr with tier distribution, top 5 tickers by dollar volume, and warnings for missing data or unresolved tickers.

## Multi-Day Averaging

When `--days N` is specified (2-5), the script fetches `N` calendar days ending at `--date` and averages all numeric columns. Weekend/holiday dates return no data and are skipped. The `days_sampled` column is added to the output.

```bash
python3 volume_profile.py --tickers AAPL,GOOGL --date 2026-03-04 --days 5
```

## Examples

### Evaluate a batch of tickers for 24/5 viability

```bash
# Create ticker file
echo -e "AAPL\nGOOGL\nMSFT\nAMZN\nMETA\nNVDA\nTSLA\nJPM\nV\nWMT" > tickers.txt

# Run volume profile
python3 volume_profile.py --ticker-file tickers.txt --date 2026-03-03

# Check results
# - HIGH tier + "24/5 viable" = good candidate for 24/5 release
# - Look at after_hours_pct and overnight_benchmark_obs for extended session confidence
```

### Check a non-onboarded ticker

```bash
python3 volume_profile.py --tickers ASTS --date 2026-03-03

# Output will show data_source=yfinance
# Check pre_price_activity and ah_price_activity for extended-hours viability
# A value > 0.8 (80% of bars with price movement) indicates active extended trading
```
