# Asset Classes

## Benchmarkable Asset Classes

These have Datascope benchmark data available:

| Asset Class | Aliases | Notes |
|-------------|---------|-------|
| `fx` | - | Foreign exchange |
| `metals` | `metal` | Precious metals |
| `us-equities` | `equity-us` | US equities + equity index futures |
| `commodity` | - | Commodities + commodity futures |

## Non-Benchmarkable Asset Classes

These will return errors (no benchmark data):

| Asset Class | Description |
|-------------|-------------|
| `crypto` | Cryptocurrency |
| `crypto-redemption-rate` | Crypto redemption rates |
| `funding-rate` | Funding rates |
| `rates` | Interest rates |
| `nav` | Net asset value |

## Discovering Asset Classes

```bash
python quick_benchmark.py --csv your_file.csv --list-asset-classes
```

Output:
```
Asset classes in your_file.csv:
==================================================
  crypto                      494 feeds  [benchmarkable: N]
  fx                           50 feeds  [benchmarkable: Y]
  equity-us                    29 feeds  [benchmarkable: Y]
  metal                         2 feeds  [benchmarkable: Y]
==================================================
```

## Futures Support

Futures contracts are automatically detected by symbol pattern and use `datascope_futures_benchmark_data`.

**Pattern:** Symbol ends with `[MONTH_CODE][YEAR_DIGIT]`

**Month codes:**
| Code | Month | Code | Month |
|------|-------|------|-------|
| F | Jan | N | Jul |
| G | Feb | Q | Aug |
| H | Mar | U | Sep |
| J | Apr | V | Oct |
| K | May | X | Nov |
| M | Jun | Z | Dec |

**Year digit:** `5` = 2025, `6` = 2026, `7` = 2027

**Examples:**
| Symbol | Meaning |
|--------|---------|
| `CCH6` | Copper March 2026 |
| `EMH6` | E-Mini S&P 500 March 2026 |
| `WTIF6` | WTI Crude January 2026 |

**Supported futures:**
- Commodity: `CC` (Copper), `WTI`, `BRENT`
- Equity index: `EM` (E-Mini S&P), `NM` (Nasdaq Mini), `DM` (Dow Mini)
