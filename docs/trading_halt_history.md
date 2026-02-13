# LULD Trading Halt History

Downloads Limit Up-Limit Down (LULD) trading halt data from two sources:
1. **NASDAQ Trader RSS feed** — NASDAQ-listed securities only (market code `Q`)
2. **NYSE Historical Halt API** — All US exchanges (Nasdaq, NYSE, NYSE American, NYSE Arca, Cboe BZX)

When both sources are enabled (the default), the script cross-references NASDAQ-listed halts to validate data agreement between the two feeds.

LULD halts are SEC-mandated circuit breakers that trigger when a stock's price moves beyond its allowable trading band (typically 5-10% for large caps, 10-20% for small caps).

## Usage

```bash
# Download all LULD halts from the past year (both sources, default)
python trading_halt_history.py

# Custom lookback period (e.g., last 30 days)
python trading_halt_history.py --days 30

# Custom output path
python trading_halt_history.py --output my_halts.csv

# Slower request rate for NASDAQ RSS (be more polite to the server)
python trading_halt_history.py --delay 0.5

# NYSE API only (skip NASDAQ RSS — much faster, covers all exchanges)
python trading_halt_history.py --no-nasdaq-rss

# NASDAQ RSS only (original behavior, skip NYSE API)
python trading_halt_history.py --no-nyse

# Export cross-reference detail to CSV
python trading_halt_history.py --days 30 --xref-output xref.csv

# Adjust time tolerance for cross-reference matching
python trading_halt_history.py --time-tolerance 10
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--days` | Number of calendar days to look back | 365 |
| `--output` | Output CSV file path | `ludp_halts.csv` |
| `--delay` | Delay between NASDAQ RSS requests in seconds | 0.2 |
| `--no-nyse` | Skip NYSE API (original RSS-only behavior) | False |
| `--no-nasdaq-rss` | Skip NASDAQ RSS (NYSE API only) | False |
| `--xref-output` | Path for cross-reference detail CSV | None |
| `--time-tolerance` | Max seconds for halt time matching in cross-reference | 5 |

## Data Sources

### NASDAQ Trader RSS Feed

- **URL**: `https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate=MMDDYYYY`
- **Format**: RSS/XML with HTML table entries
- **Access**: Free, public, no authentication required
- **Coverage**: NASDAQ-listed securities only (market code `Q`)
- **Granularity**: One feed per calendar day; only business days contain data
- **Halt code**: `LUDP`

### NYSE Historical Halt API

- **URL**: `https://www.nyse.com/api/trade-halts/historical/download`
- **Format**: CSV download
- **Access**: Free, public, no authentication required
- **Coverage**: All US exchanges (Nasdaq, NYSE, NYSE American, NYSE Arca, Cboe BZX)
- **Granularity**: Single request for full date range — no day-by-day fetching
- **Halt code**: `LULD pause`

## How It Works

1. Fetches NASDAQ RSS halts day-by-day for the lookback period (unless `--no-nasdaq-rss`)
2. Fetches NYSE API halts in a single request for the full date range (unless `--no-nyse`)
3. Cross-references both sources on NASDAQ-listed halts (if both are present)
4. Merges all halts into a single deduplicated list with source attribution
5. Sorts results by date (ascending), then halt time (ascending)
6. Writes output CSV and prints summary + cross-reference report

Failed requests are retried up to 3 times with exponential backoff.

## Output Format

```csv
date,ticker,halt_time,resume_time,market,source
2025-02-10,BOWNU,09:30:18,09:35:18,Q,both
2025-02-10,BDRX,09:32:52,09:37:52,Q,nasdaq_rss
2025-02-10,KD,14:22:10,14:27:10,N,nyse
```

| Column | Description |
|--------|-------------|
| `date` | Halt date (YYYY-MM-DD) |
| `ticker` | Stock symbol |
| `halt_time` | Time halt began (HH:MM:SS ET) |
| `resume_time` | Time trading resumed (HH:MM:SS ET) |
| `market` | Exchange code (see table below) |
| `source` | Data source: `both`, `nasdaq_rss`, or `nyse` |

### Source Values

| Value | Meaning |
|-------|---------|
| `both` | Halt found in both NASDAQ RSS and NYSE API (matched) |
| `nasdaq_rss` | Halt only found in NASDAQ RSS feed |
| `nyse` | Halt only found in NYSE API (or non-Nasdaq exchange) |

### Market Codes

| Code | Exchange |
|------|----------|
| `Q` | NASDAQ |
| `N` | NYSE |
| `A` | NYSE American (AMEX) |
| `P` | NYSE Arca |
| `Z` | Cboe BZX (BATS) |

## Cross-Reference

When both sources are enabled, the script cross-references NASDAQ-listed halts (`market == "Q"`) between the two feeds.

### Matching Algorithm

1. Index NYSE API Nasdaq halts by `(date, ticker)`
2. For each RSS halt, find the best-matching NYSE halt by closest `halt_time`
3. If time difference <= `--time-tolerance` (default 5 seconds): **matched**
4. Unmatched RSS halts: **nasdaq_only**
5. Unmatched NYSE Nasdaq halts: **nyse_only**

### Cross-Reference Report

The console report shows:
- Matched / NASDAQ-only / NYSE-only counts and percentages
- Agreement rate
- Time difference distribution for matched halts
- First 10 examples of mismatches

### Cross-Reference CSV

Use `--xref-output xref.csv` to export per-halt cross-reference detail:

```csv
date,ticker,rss_halt_time,nyse_halt_time,rss_resume_time,nyse_resume_time,time_diff_sec,status
2025-02-10,BOWNU,09:30:18,09:30:18,09:35:18,09:35:18,0,matched
2025-02-10,XYZZ,09:45:03,,09:50:03,,, nasdaq_only
2025-02-10,ABCD,,10:15:30,,10:20:30,,nyse_only
```

## Halt Reason Codes

The script filters for LULD halts only:
- **NASDAQ RSS**: `LUDP` reason code
- **NYSE API**: `LULD pause` reason

Other common reason codes present in the feeds (all excluded):

| Code | Description |
|------|-------------|
| **LUDP** / **LULD pause** | Limit Up-Limit Down Pause (circuit breaker) |
| `M` | Volatility Trading Pause (Market-Wide Circuit Breaker) |
| `T1` | News Pending |
| `T2` | News Dissemination |
| `T12` | IPO Halt / Additional Information Requested |
| `T6` | Extraordinary Market Activity |
| `H10` | SEC Trading Suspension |
| `MWCB1` | Market-Wide Circuit Breaker Level 1 (7% S&P 500 decline) |

## Console Summary

After downloading, the script prints a halt summary and cross-reference report:

```
============================================================
LULD TRADING HALT SUMMARY
============================================================
Total LULD halts:    10,808
Unique tickers:      1,450
Date range:          2025-02-10 to 2026-02-09
Days with halts:     251

By exchange:
  Nasdaq             6,210  (57.5%)
  NYSE Arca          2,104  (19.5%)
  NYSE               1,520  (14.1%)
  NYSE American        640  (5.9%)
  Cboe BZX             334  (3.1%)

By source:
  both               5,890  (54.5%)
  nyse               4,598  (42.5%)
  nasdaq_rss           320  (3.0%)

Top 20 most-halted tickers:
  PHOE          88 halts
  ...
============================================================

============================================================
CROSS-REFERENCE REPORT (Nasdaq-Listed Only)
============================================================
Matched (both sources):   5,890
NASDAQ RSS only:            320
NYSE API only:              180
Total unique halts:       6,390
Agreement rate:            92.2%
...
============================================================
```

## Performance

| Mode | Requests | Time |
|------|----------|------|
| Both sources (default) | ~250 RSS + 1 NYSE API | ~2-3 minutes |
| NYSE API only (`--no-nasdaq-rss`) | 1 request | ~5 seconds |
| NASDAQ RSS only (`--no-nyse`) | ~250 requests | ~2-3 minutes |

## Typical Patterns

- **Most halts** occur in small-cap and micro-cap stocks with high volatility
- **Halts cluster** around market open (9:30-10:30 AM ET) when price discovery is most active
- **Duration**: Most LULD pauses last 5 minutes (the standard resumption period)
- **Repeat offenders**: Some tickers halt dozens of times per year, indicating persistent volatility
- **Seasonal patterns**: Earnings season and macro events correlate with higher halt counts
- **Exchange distribution**: ~57% Nasdaq, ~20% NYSE Arca, ~14% NYSE, ~6% NYSE American, ~3% Cboe BZX

## What Is LULD?

The Limit Up-Limit Down (LULD) mechanism was introduced by the SEC in 2012 to prevent extreme price moves. When a stock's price hits the upper or lower band:

1. A **Limit State** begins — trading continues but only at or within the band
2. If the price doesn't return within 15 seconds, a **Trading Pause** (LUDP) is triggered
3. Trading halts for 5 minutes, then reopens with an auction

Price bands are calculated from a reference price (typically the 5-minute rolling average):
- **Tier 1** (S&P 500, Russell 1000, high-volume ETPs): 5% during regular hours, 10% during open/close
- **Tier 2** (all other NMS stocks): 10% during regular hours, 20% during open/close

## Dependencies

- `feedparser` — RSS/XML parsing (NASDAQ RSS only)
- `pandas` — Business day generation (NASDAQ RSS only)

Both are listed in `requirements.txt`. The NYSE API uses only stdlib (`urllib`, `csv`, `io`).

## Troubleshooting

### No data returned for a date

Weekends and market holidays return empty feeds. The script only queries business days, but some holidays (e.g., Good Friday, Juneteenth) are not excluded by `pandas.bdate_range()` and will simply return 0 entries.

### Network timeouts

The script retries failed requests up to 3 times with exponential backoff (1s, 2s, 4s). If a request still fails, it is skipped with a warning and processing continues.

### NYSE API returns empty

The NYSE API may occasionally be unavailable. The script will retry 3 times and log an error if all attempts fail. Use `--no-nyse` to fall back to NASDAQ RSS only.

### Very slow execution

Use `--no-nasdaq-rss` for NYSE-API-only mode (single request, ~5 seconds). The NASDAQ RSS requires one request per business day (~250/year) which takes 2-3 minutes.
