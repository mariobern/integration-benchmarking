# Create 34 xStocks COMING_SOON feeds (3375–3408) in `lazer_new.json`

Date: 2026-06-29
Status: Approved

## Goal

Add 34 new xStocks spot price feeds (feed IDs 3375–3408) to `lazer_new.json`,
modeled exactly on existing feed **3329** (`Crypto.SPCXX/USD`), with per-feed
data drawn from `xstocks.csv`. All new feeds are `COMING_SOON`.

## Inputs

- **`lazer_new.json`** — the Lazer config to modify. Top-level dict; feeds live
  in the `feeds` array, sorted ascending by `feedId`.
- **Template feed 3329** — the spot `/USD` block used as the structural template.
- **`xstocks.csv`** — 34 data rows, header `feed_id,name,description,cmc_id`
  (plus trailing empty columns). Covers feed IDs 3375–3408 exactly.

## Template (feed 3329, verbatim)

```json
{
  "expiryTime": "5.000000000s",
  "exponent": -8,
  "feedId": 3329,
  "isEnabledInShard": true,
  "kind": "PRICE",
  "marketSchedules": [
    {
      "allowedPublisherIds": [59, 71, 24, 29, 65, 22, 19, 80],
      "benchmarkMapping": {
        "coinpaprika_symbol": {
          "identifiers": [
            { "identifier": "", "validFrom": "1970-01-01T00:00:00.000000000Z" }
          ]
        }
      },
      "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
      "session": "REGULAR"
    }
  ],
  "metadata": {
    "asset_type": "crypto",
    "cmc_id": { "uintValue": "40218" },
    "description": "SPACE EXPLORATION TECHNOLOGY CORP XSTOCK / US DOLLAR",
    "instrument_type": "spot",
    "name": "SPCXXUSD",
    "quote_currency": "USD"
  },
  "minChannel": { "rate": "0.200000000s" },
  "minPublishers": 3,
  "state": "STABLE",
  "symbol": "Crypto.SPCXX/USD"
}
```

## Per-feed field overrides

Every field not listed here is copied **verbatim** from feed 3329.

| Field                       | Value                     | Source / rule                                |
| --------------------------- | ------------------------- | -------------------------------------------- |
| `feedId`                    | 3375–3408                 | CSV `feed_id`                                |
| `symbol`                    | `Crypto.{TICKER}/USD`     | CSV `name` (ticker), e.g. `Crypto.ADBEX/USD` |
| `metadata.name`             | `{TICKER}USD`             | CSV `name`, e.g. `ADBEXUSD`                  |
| `metadata.description`      | trimmed CSV `description` | CSV, e.g. `ADOBE XSTOCK / US DOLLAR`         |
| `metadata.cmc_id.uintValue` | CSV `cmc_id` as string    | CSV                                          |
| `state`                     | `COMING_SOON`             | requirement (template is `STABLE`)           |
| `minChannel.rate`           | `0.200000000s`            | requirement (already matches template)       |

The CSV `name` values already include the trailing `X` (e.g. `ADBEX`,
matching the template's `SPCXX`). The CSV `description` has a leading space that
must be stripped.

### Copied verbatim from 3329

`expiryTime`, `exponent` (-8), `isEnabledInShard` (true), `kind` (PRICE),
the entire `marketSchedules` array (including `allowedPublisherIds`
`[59, 71, 24, 29, 65, 22, 19, 80]`, the empty-identifier `benchmarkMapping`,
`marketSchedule`, and `session: REGULAR`), `minPublishers` (3),
`metadata.asset_type` (crypto), `metadata.instrument_type` (spot),
`metadata.quote_currency` (USD).

## Approach

A small one-off Python script (run from the scratchpad; not added to the
CLAUDE.md Scripts table):

1. Load `lazer_new.json`; locate feed 3329 as the template object.
2. Parse `xstocks.csv` (skip header; ignore trailing empty columns).
3. For each row, `copy.deepcopy(template)` and apply the overrides above.
4. Serialize each new feed with `json.dumps(indent=2)` and re-indent every line
   by +4 spaces to match the file's feed-object nesting (feed `{` sits at
   4-space indent, keys at 6).
5. Splice the 34 serialized blocks into the raw file text immediately after
   feed 3374's closing block (sorted position, before the next feed), using
   raw-text block insertion so the rest of the 5 MB file stays byte-for-byte
   unchanged. This mirrors the repo's `lib/json_surgery.py` convention and keeps
   the diff minimal.

Building each feed by deep-copying the template dict (rather than constructing
from scratch) guarantees identical key order and field set; `json.dumps`
preserves insertion order.

## Verification

- **Pre-flight**: assert no existing feed uses IDs 3375–3408 (confirmed: none).
- **Post-write**:
  - `json.load` the modified file → still valid JSON.
  - `len(feeds)` increased by exactly 34.
  - All 34 new feeds present with the expected `feedId` / `symbol` / `name` /
    `state` / `cmc_id`.
  - Spot-check 2–3 generated blocks field-by-field against 3329.
  - `git diff --stat` shows only added lines in `lazer_new.json` (34 feed
    blocks), no incidental reformatting elsewhere.

## Scope / Out of scope

- **In scope**: 34 spot `/USD` feeds, 1:1 with the CSV rows.
- **Out of scope**: `.RR` redemption-rate feeds (the requested range is
  spot-only); any change to existing feeds; promoting these to `STABLE`;
  publisher-list tuning (copy 3329 verbatim per decision).
