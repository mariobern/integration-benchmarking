# Exchange Configuration Guide

This guide explains how to configure exchanges in the `pyth-lazer-governance` repo.

## What Exchanges Do

Today, every feed carries its own full copy of market session schedules (timezone, weekly hours, holidays). This means holiday updates require touching every feed individually. The MLK Day 2026 update touched ~1,902 feeds.

Exchanges let you define the schedule once and have feeds inherit it. A holiday update becomes editing one exchange entry in `after.json` instead of touching thousands of feeds.

## Concepts

### Exchange

An exchange represents a trading venue + asset classification combination. The tuple `(name, asset_class, asset_subclass, asset_sector)` must be unique. The same exchange name can appear multiple times with different classifications:

| Example        | name   | asset_class   | asset_subclass | asset_sector  |
| -------------- | ------ | ------------- | -------------- | ------------- |
| US equities    | NASDAQ | EQUITY        | COMMON_STOCK   | TECHNOLOGY    |
| US equity ETFs | NASDAQ | EQUITY        | ETF            | BROAD_MARKET  |
| Energy futures | CME    | FUTURE        | ENERGY         | OIL           |
| Ag futures     | CME    | FUTURE        | AGRICULTURAL   | AGRICULTURAL  |
| All crypto     | Crypto | (unspecified) | (unspecified)  | (unspecified) |

### Sessions

Each exchange defines schedule templates for one or more sessions:

| Session       | Typical use         |
| ------------- | ------------------- |
| `REGULAR`     | Main trading hours  |
| `PRE_MARKET`  | Before regular open |
| `POST_MARKET` | After regular close |
| `OVER_NIGHT`  | Overnight/extended  |

### Schedule String Format

The schedule string on exchange sessions uses the same format as the `marketSchedule` field on individual feed market session entries.

```
timezone;day0,day1,day2,day3,day4,day5,day6;holiday1,holiday2,...
```

- **Timezone**: IANA timezone (e.g., `America/New_York`, `UTC`)
- **Days**: 7 comma-separated values for Mon through Sun
  - `O` = fully open
  - `C` = fully closed
  - `0930-1600` = open during time range
  - `0000-0400&2000-2400` = multiple ranges in one day
- **Holidays**: optional, comma-separated `MMDD/kind` entries
  - `0101/C` = Jan 1 closed
  - `1127/0930-1300` = Nov 27 early close
  - `0619/O` = Jun 19 open (overrides a closure)

### Inheritance

When a feed sets `exchangeId` and declares a market session **without** a `marketSchedule` string, the schedule is inherited from the exchange. The feed can optionally add `scheduleOverrides` to modify specific holidays.

If a feed provides an explicit `marketSchedule` string, that takes priority and the exchange schedule is ignored for that session.

## How To: Create an Exchange

### 1. Create a governance proposal

Follow the standard [governance workflow](https://github.com/pyth-network/pyth-lazer-governance#how-to-create-a-proposal-via-a-web-browser) to create a proposal.

### 2. Add the exchange to the `exchanges` array in `after.json`

If `after.json` doesn't have an `"exchanges"` key yet, add it at the top level alongside `"feeds"`, `"publishers"`, etc. The governance tool will diff `before.json` and `after.json` and generate the appropriate `addExchange` transaction automatically.

```json
{
  "exchanges": [
    {
      "exchangeId": 1,
      "name": "NASDAQ",
      "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
      "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
      "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
      "sessions": [
        {
          "session": "REGULAR",
          "marketSchedule": "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1127/0930-1300,1224/0930-1300,1225/C"
        },
        {
          "session": "PRE_MARKET",
          "marketSchedule": "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
        },
        {
          "session": "POST_MARKET",
          "marketSchedule": "America/New_York;1600-2000,1600-2000,1600-2000,1600-2000,1600-2000,C,C;0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
        },
        {
          "session": "OVER_NIGHT",
          "marketSchedule": "America/New_York;0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,0000-0400,C,2000-2400;0118/C,0119/2000-2400,0215/C,0216/2000-2400,0402/0000-0400,0403/C,0524/C,0525/2000-2400,0618/0000-0400,0619/C,0702/0000-0400,0703/C,0906/C,0907/2000-2400,1125/0000-0400,1126/2000-2400,1224/0000-0400,1225/C,1231/0000-0400,0101/C"
        }
      ]
    }
  ],
  "feeds": [...],
  ...
}
```

### Required fields

| Field           | Required         | Notes                                                       |
| --------------- | ---------------- | ----------------------------------------------------------- |
| `exchangeId`    | yes              | Unique numeric ID. Pick something that doesn't conflict.    |
| `name`          | yes              | Human-readable name (e.g., `"NASDAQ"`, `"CME"`, `"Crypto"`) |
| `sessions`      | yes (at least 1) | Schedule templates for each session                         |
| `assetClass`    | no               | Defaults to `UNSPECIFIED`                                   |
| `assetSubclass` | no               | Defaults to `UNSPECIFIED`                                   |
| `assetSector`   | no               | Defaults to `UNSPECIFIED`                                   |
| `metadata`      | no               | Optional key/value pairs (region, mic_code, etc.)           |

## How To: Migrate a Feed to Use Exchange Inheritance

Once an exchange exists in the state, edit the feed in `after.json` to reference it and remove the inline schedules. The governance tool generates the diff transaction automatically.

### Before (feed with inline schedules)

```json
{
  "feedId": 922,
  "symbol": "Equity.US.AAPL/USD",
  "marketSchedules": [
    {
      "session": "REGULAR",
      "marketSchedule": "America/New_York;0930-1600,...;0101/C,...",
      "allowedPublisherIds": [12, 14, 19, 20],
      "minPublishers": 3
    },
    {
      "session": "PRE_MARKET",
      "marketSchedule": "America/New_York;0400-0930,...;0101/C,...",
      "allowedPublisherIds": [19, 20, 22],
      "minPublishers": 2
    }
  ]
}
```

### After (feed inheriting from exchange)

```json
{
  "feedId": 922,
  "symbol": "Equity.US.AAPL/USD",
  "exchangeId": 1,
  "marketSchedules": [
    {
      "session": "REGULAR",
      "allowedPublisherIds": [12, 14, 19, 20],
      "minPublishers": 3
    },
    {
      "session": "PRE_MARKET",
      "allowedPublisherIds": [19, 20, 22],
      "minPublishers": 2
    }
  ]
}
```

Key changes:

- Added `"exchangeId": 1`
- Removed `"marketSchedule"` from each session (schedule is now inherited)
- `allowedPublisherIds`, `minPublishers`, and `benchmarkMapping` stay on the feed (always feed-level)

## How To: Add a New Feed with Exchange Inheritance

In `after.json`, add the feed with `exchangeId` set and sessions without `marketSchedule` strings:

```json
{
  "feedId": 5000,
  "symbol": "Equity.US.NVDA/USD",
  "exchangeId": 1,
  "expiryTime": "5.000000000s",
  "exponent": -5,
  "kind": "PRICE",
  "state": "STABLE",
  "isEnabledInShard": true,
  "minPublishers": 3,
  "minChannel": { "rate": "0.200000000s" },
  "metadata": {
    "items": [
      { "key": "asset_type", "value": { "stringValue": "equity" } },
      { "key": "name", "value": { "stringValue": "NVIDIA" } },
      { "key": "description", "value": { "stringValue": "NVDA/USD" } }
    ]
  },
  "marketSchedules": [
    {
      "session": "REGULAR",
      "allowedPublisherIds": [12, 14, 19],
      "minPublishers": 3
    },
    {
      "session": "PRE_MARKET",
      "allowedPublisherIds": [19, 22],
      "minPublishers": 2
    },
    {
      "session": "POST_MARKET",
      "allowedPublisherIds": [19, 22],
      "minPublishers": 2
    },
    { "session": "OVER_NIGHT", "allowedPublisherIds": [13], "minPublishers": 1 }
  ]
}
```

No `marketSchedule` strings needed. The feed declares which sessions it participates in and the schedules come from exchange 1.

## How To: Update Exchange Schedules (Holiday Updates)

Instead of editing every feed in `after.json`, edit the exchange entry once. To update holidays for the new year, find the exchange in `after.json` and update its session `marketSchedule` strings:

```json
{
  "exchangeId": 1,
  "name": "NASDAQ",
  "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
  "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
  "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
  "sessions": [
    {
      "session": "REGULAR",
      "marketSchedule": "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;0101/C,0119/C,0217/C,0418/C,0526/C,0619/C,0704/C,0901/C,1127/0930-1300,1225/C"
    },
    {
      "session": "PRE_MARKET",
      "marketSchedule": "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;0101/C,0119/C,0217/C,0418/C,0526/C,0619/C,0704/C,0901/C,1127/C,1225/C"
    },
    {
      "session": "POST_MARKET",
      "marketSchedule": "America/New_York;1600-2000,1600-2000,1600-2000,1600-2000,1600-2000,C,C;0101/C,0119/C,0217/C,0418/C,0526/C,0619/C,0704/C,0901/C,1127/C,1225/C"
    },
    {
      "session": "OVER_NIGHT",
      "marketSchedule": "America/New_York;0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,0000-0400,C,2000-2400;0118/C,0119/2000-2400,0217/C,0418/C,0526/C,0619/C,0704/C,0901/C,1127/C,1225/C"
    }
  ]
}
```

All feeds referencing this exchange automatically pick up the new schedules. No feed-level changes needed.

**Important**: When editing sessions, always include all sessions. The governance tool treats the sessions list as a full replacement. Omitting a session removes it.

## How To: Per-Feed Schedule Overrides

For feeds that mostly follow the exchange but need specific holiday modifications, add `scheduleOverrides` to the relevant session in `after.json`:

```json
{
  "feedId": 2050,
  "exchangeId": 1,
  "marketSchedules": [
    {
      "session": "REGULAR",
      "allowedPublisherIds": [12, 14, 19],
      "minPublishers": 3,
      "scheduleOverrides": {
        "holidayOverrides": ["0315/C"]
      }
    }
  ]
}
```

This feed inherits the exchange REGULAR schedule but is additionally closed on March 15.

Override examples:

- `"0315/C"` - add a closure (stock halted)
- `"0619/O"` - remove a closure (ETF trades through Juneteenth)
- `"0703/0930-1300"` - replace a holiday with an early close

Overrides only apply when inheriting. If a feed has an explicit `marketSchedule` string, overrides are ignored.

## How To: Remove an Exchange

Remove the exchange entry from the `exchanges` array in `after.json`. The governance tool will generate a `removeExchange` transaction.

This will be **rejected** if any feed still references the exchange. You must first migrate all feeds off it (either to a different exchange or back to inline schedules).

## Classification Enum Reference

### ExchangeAssetClass

| Value                              | Use for                                  |
| ---------------------------------- | ---------------------------------------- |
| `EXCHANGE_ASSET_CLASS_UNSPECIFIED` | Crypto, FX, or anything that doesn't fit |
| `EXCHANGE_ASSET_CLASS_EQUITY`      | Stocks, ETFs                             |
| `EXCHANGE_ASSET_CLASS_FUTURE`      | Futures contracts                        |

### ExchangeAssetSubclass

| Value                                  | Use for                             |
| -------------------------------------- | ----------------------------------- |
| `EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED`  | Default / not applicable            |
| `EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK` | Individual stocks                   |
| `EXCHANGE_ASSET_SUBCLASS_ETF`          | Exchange-traded funds               |
| `EXCHANGE_ASSET_SUBCLASS_ENERGY`       | Energy futures (WTI, Brent, natgas) |
| `EXCHANGE_ASSET_SUBCLASS_METALS`       | Metal futures                       |
| `EXCHANGE_ASSET_SUBCLASS_EQUITY`       | Equity index futures (E-mini)       |
| `EXCHANGE_ASSET_SUBCLASS_FIXED_INCOME` | Bond futures, rates                 |
| `EXCHANGE_ASSET_SUBCLASS_FX`           | FX futures                          |
| `EXCHANGE_ASSET_SUBCLASS_AGRICULTURAL` | Ag futures (cocoa, coffee, wheat)   |

### ExchangeAssetSector

| Value                                | Use for                  |
| ------------------------------------ | ------------------------ |
| `EXCHANGE_ASSET_SECTOR_UNSPECIFIED`  | Default / not applicable |
| `EXCHANGE_ASSET_SECTOR_TECHNOLOGY`   | Tech stocks              |
| `EXCHANGE_ASSET_SECTOR_FINANCIALS`   | Financial stocks         |
| `EXCHANGE_ASSET_SECTOR_BROAD_MARKET` | Broad index ETFs         |
| `EXCHANGE_ASSET_SECTOR_OIL`          | Oil futures              |
| `EXCHANGE_ASSET_SECTOR_METALS`       | Metal futures            |
| `EXCHANGE_ASSET_SECTOR_INDEX`        | Index futures            |
| `EXCHANGE_ASSET_SECTOR_RATES`        | Rate futures             |
| `EXCHANGE_ASSET_SECTOR_FX`           | FX                       |
| `EXCHANGE_ASSET_SECTOR_AGRICULTURAL` | Agricultural futures     |

## Suggested Rollout Plan

1. **Create exchanges** for the subset of a subset of schedules with few consumers
2. **Migrate feeds in that subset**
3. **Verify** via the Pyth app (or any UI that fetches the [`/v1/symbols`](https://pyth.dourolabs.app/v1/symbols) endpoint) that the resolved schedules for migrated feeds match expectations exactly, this is the end of the testing phase, then move on to feeds with actual consumers.
4. **Create exchanges** for the major schedule groups (start with US equities)
5. **Migrate feeds incrementally** by asset class, starting with equities that all share the same schedule
6. **Verify** via the Pyth app (or any UI that fetches the [`/v1/symbols`](https://pyth.dourolabs.app/v1/symbols) endpoint) that the resolved schedules for migrated feeds match expectations exactly
7. **Next holiday update**: edit the exchange in `after.json` instead of individual feeds
