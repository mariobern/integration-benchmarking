# Asset Classes

> **Last updated:** 2026-03-02
>
> **Rule:** Update this date every time this file is modified.

## Feed Counts (from lazer_symbols.json)

| Asset Type               | Feeds | Benchmarkable |
| ------------------------ | ----- | ------------- |
| `equity`                 | 1648  | Yes           |
| `crypto`                 | 733   | No            |
| `fx`                     | 290   | Yes           |
| `crypto-redemption-rate` | 189   | No            |
| `commodity`              | 83    | Yes           |
| `rates`                  | 25    | Yes           |
| `kalshi`                 | 19    | No            |
| `funding-rate`           | 15    | No            |
| `metal`                  | 13    | Yes           |
| `crypto-index`           | 8     | No            |
| `nav`                    | 6     | No            |
| `custom`                 | 5     | No            |

## Benchmarkable Asset Classes

These have Datascope benchmark data available:

| Asset Class     | Aliases               | Notes                              |
| --------------- | --------------------- | ---------------------------------- |
| `fx`            | -                     | Foreign exchange (290 feeds)       |
| `metals`        | `metal`               | Precious metals (13 feeds)         |
| `us-equities`   | `equity-us`           | US equities + equity index futures |
| `commodity`     | -                     | Commodities + commodity futures    |
| `us-treasuries` | `treasuries`, `rates` | US Treasury bonds (yield values)   |

## Non-Benchmarkable Asset Classes

These will return errors (no benchmark data):

| Asset Class              | Description                          |
| ------------------------ | ------------------------------------ |
| `crypto`                 | Cryptocurrency (733 feeds)           |
| `crypto-redemption-rate` | Crypto redemption rates (189 feeds)  |
| `crypto-index`           | Crypto indices (8 feeds)             |
| `funding-rate`           | Funding rates (15 feeds)             |
| `nav`                    | Net asset value (6 feeds)            |
| `kalshi`                 | Kalshi prediction markets (19 feeds) |
| `custom`                 | Custom/internal feeds (5 feeds)      |

## Asset Class Normalization

The CLI accepts aliases that normalize to canonical names (see `lib/config.py`):

| Input        | Canonical       |
| ------------ | --------------- |
| `metal`      | `metals`        |
| `equity-us`  | `us-equities`   |
| `rates`      | `us-treasuries` |
| `treasuries` | `us-treasuries` |

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
| ---- | ----- | ---- | ----- |
| F    | Jan   | N    | Jul   |
| G    | Feb   | Q    | Aug   |
| H    | Mar   | U    | Sep   |
| J    | Apr   | V    | Oct   |
| K    | May   | X    | Nov   |
| M    | Jun   | Z    | Dec   |

**Year digit:** `5` = 2025, `6` = 2026, `7` = 2027

### Commodity Futures (Pyth Code -> Datascope RIC)

| Pyth Code | RIC Root | Commodity          | Exchange   | Example               |
| --------- | -------- | ------------------ | ---------- | --------------------- |
| `CC`      | `HG`     | Copper             | COMEX      | `CCH6` -> `HGH26`     |
| `WTI`     | `CL`     | WTI Crude Oil      | NYMEX      | `WTIJ6` -> `CLJ26`    |
| `BRENT`   | `LCO`    | Brent Crude Oil    | ICE        | `BRENTM6` -> `LCOM26` |
| `NGD`     | `NG`     | Natural Gas        | NYMEX      | `NGDH6` -> `NGH26`    |
| `AL`      | `ALI`    | Aluminum           | LME/COMEX  | `ALH6` -> `ALIH26`    |
| `NL`      | `MNI`    | Nickel             | LME        | `NLH6` -> `MNIH26`    |
| `LE`      | `MPB`    | Lead               | LME        | `LEM6` -> `MPBM26`    |
| `TI`      | `MSN`    | Tin                | LME        | `TIH6` -> `MSNH26`    |
| `CO`      | `C`      | Corn               | CBOT       | `COH6` -> `CH26`      |
| `RS`      | `SB`     | Raw Sugar No. 11   | ICE US     | `RSK6` -> `SBK26`     |
| `GO`      | `LGO`    | Low Sulphur Gasoil | ICE Europe | `GOH6` -> `LGOH26`    |
| `PL`      | `PA`     | Palladium          | NYMEX      | `PLM6` -> `PAM26`     |
| `PT`      | `PL`     | Platinum           | NYMEX      | `PTJ6` -> `PLJ26`     |
| `UR`      | `UX`     | Uranium            | COMEX      | `URH6` -> `UXH26`     |
| `NID`     | `NK`     | Nikkei 225         | CME        | `NIDH6` -> `NKH26`    |

### Equity Index Futures (Pyth Code -> Datascope RIC)

| Pyth Code | RIC Root | Index                  | Example              |
| --------- | -------- | ---------------------- | -------------------- |
| `EM`      | `ES`     | E-Mini S&P 500         | `EMH6` -> `ESH26`    |
| `NM`      | `NQ`     | Nasdaq 100 Mini        | `NMH6` -> `NQH26`    |
| `DM`      | `YM`     | Dow Jones Mini         | `DMH6` -> `YMH26`    |
| `US500`   | `ES`     | S&P 500 (alias for EM) | `US500H6` -> `ESH26` |
| `US100`   | `NQ`     | Nasdaq 100 (alias)     | `US100H6` -> `NQH26` |
| `US30`    | `YM`     | Dow Jones (alias)      | `US30H6` -> `YMH26`  |

### Metal Spot RICs

| Pyth Symbol     | RIC    | Metal     |
| --------------- | ------ | --------- |
| `Metal.XAU/USD` | `XAU=` | Gold      |
| `Metal.XAG/USD` | `XAG=` | Silver    |
| `Metal.XPT/USD` | `XPT=` | Platinum  |
| `Metal.XPD/USD` | `XPD=` | Palladium |

### FX RIC Patterns

| Pattern               | RIC Format        | Example                |
| --------------------- | ----------------- | ---------------------- |
| USD pair              | `{CCY}=`          | `EURUSD` -> `EUR=`     |
| EUR/GBP/JPY cross     | `{BASE}{QUOTE}=`  | `EURGBP` -> `EURGBP=`  |
| AUD/NZD/CAD/CHF cross | `{BASE}{QUOTE}=R` | `AUDCAD` -> `AUDCAD=R` |
| Dollar Index          | `.DXY`            | `USDXY` -> `.DXY`      |

### US Treasury RICs

| Pyth Symbol   | RIC           | Tenor   |
| ------------- | ------------- | ------- |
| `Rates.US3M`  | `US3MT=RRPS`  | 3-month |
| `Rates.US2Y`  | `US2YT=RRPS`  | 2-year  |
| `Rates.US5Y`  | `US5YT=RRPS`  | 5-year  |
| `Rates.US10Y` | `US10YT=RRPS` | 10-year |
| `Rates.US30Y` | `US30YT=RRPS` | 30-year |
