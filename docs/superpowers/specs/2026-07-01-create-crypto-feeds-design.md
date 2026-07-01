# Create 12 crypto COMING_SOON feeds (3407–3419) in `lazer.json`

Date: 2026-07-01
Status: Approved

## Goal

Add 12 new crypto spot price feeds to `lazer.json`, modeled exactly on
existing feed **3329** (`Crypto.SPCXX/USD`), with per-feed data drawn from
`crypto.csv`. All new feeds are `COMING_SOON`.

## Inputs

- **`lazer.json`** — the Lazer config to modify. Top-level dict; feeds live in
  the `feeds` array, sorted ascending by `feedId`.
- **Template feed 3329** — the spot `/USD` block used as the structural
  template (same template used for the prior xStocks batch, see
  `2026-06-29-create-xstocks-feeds-design.md`).
- **`crypto.csv`** — 12 data rows, header `feed_id,name,description,cmc_id`
  (plus trailing empty columns). Column 2 (`name`) is `TICKER/USD`.

## Feed-ID collision and remap

The CSV's `feed_id` column requests the contiguous range 3407–3418. Feed
**3409 already exists** in `lazer.json` as an unrelated feed
(`Equity.US.ECHO/USD`, EchoStar Corp, `COMING_SOON`) — it must not be touched
or overwritten.

Decision: the row that maps to 3409 (`ADI/USD`) is **assigned feedId 3419**
instead (the next free ID after the requested range). All other rows keep
their CSV `feed_id` unchanged. No other collisions exist — verified no
existing feed shares any target `symbol` or `metadata.name`.

Final ID mapping:

| feed_id (final) | CSV row (`name`)     |
| ---------------- | -------------------- |
| 3407              | BEAT/USD              |
| 3408              | YLDS/USD              |
| 3410              | U/USD                 |
| 3411              | STABLE/USD            |
| 3412              | BFUSD/USD             |
| 3413              | HTX/USD               |
| 3414              | M/USD                 |
| 3415              | LAB/USD               |
| 3416              | WBT/USD               |
| 3417              | RAIN/USD              |
| 3418              | ANSEM/USD             |
| 3419              | ADI/USD (remapped from 3409) |

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

| Field                       | Value                     | Source / rule                                          |
| --------------------------- | -------------------------- | ------------------------------------------------------- |
| `feedId`                    | 3407, 3408, 3410–3419      | CSV `feed_id`, except ADI/USD remapped to 3419 (see above) |
| `symbol`                    | `Crypto.{TICKER}/USD`      | CSV `name` column, ticker = text before `/USD`           |
| `metadata.name`             | `{TICKER}USD`               | same ticker                                              |
| `metadata.description`      | trimmed CSV `description`  | CSV, used **verbatim** — not reformatted into xStock-style `<NAME> XSTOCK / US DOLLAR` wording, since these are real crypto tokens, not tokenized equities |
| `metadata.cmc_id.uintValue` | CSV `cmc_id` as string     | CSV                                                      |
| `state`                     | `COMING_SOON`               | requirement (template is `STABLE`)                       |
| `minChannel.rate`           | `0.200000000s`              | requirement (already matches template)                   |

### Copied verbatim from 3329

`expiryTime`, `exponent` (-8), `isEnabledInShard` (true), `kind` (PRICE), the
entire `marketSchedules` array (including `allowedPublisherIds`
`[59, 71, 24, 29, 65, 22, 19, 80]`, the empty-identifier `benchmarkMapping`,
`marketSchedule`, and `session: REGULAR`), `minPublishers` (3),
`metadata.asset_type` (crypto), `metadata.instrument_type` (spot),
`metadata.quote_currency` (USD).

## Approach

A small one-off Python script (run from the scratchpad; not added to the
CLAUDE.md Scripts table) — same mechanics as the prior xStocks batch
(`2026-06-29-create-xstocks-feeds-design.md`):

1. Load `lazer.json`; locate feed 3329 as the template object.
2. Parse `crypto.csv` (skip header; ignore trailing empty columns; skip the
   row whose `feed_id` is 3409, remapping it to feedId 3419 instead).
3. For each row, `copy.deepcopy(template)` and apply the overrides above.
4. Serialize each new feed with `json.dumps(indent=2)` and re-indent every
   line by +4 spaces to match the file's feed-object nesting (feed `{` sits at
   4-space indent, keys at 6).
5. Splice the serialized blocks into the raw file text at **two** insertion
   points, to preserve global ascending `feedId` order without touching the
   existing feed 3409:
   - immediately after feed 3406's closing block: insert 3407, 3408
   - immediately after feed 3409's closing block (feed 3409 itself untouched):
     insert 3410, 3411, 3412, 3413, 3414, 3415, 3416, 3417, 3418, 3419 (in that
     order — ADI/USD last, at 3419)

This mirrors the repo's `lib/json_surgery.py` convention (raw-text block
insertion, rest of the file byte-for-byte unchanged) and keeps the diff
minimal.

## Verification

- **Pre-flight**: assert feeds 3407, 3408, 3410–3419 don't already exist, and
  that feed 3409 exists and remains an equity feed (sanity check it's the
  expected untouched feed).
- **Post-write**:
  - `json.load` the modified file → still valid JSON.
  - `len(feeds)` increased by exactly 12.
  - Feed 3409 unchanged (still `Equity.US.ECHO/USD`).
  - All 12 new feeds present with the expected `feedId` / `symbol` / `name` /
    `state` / `cmc_id`.
  - Spot-check 2–3 generated blocks field-by-field against 3329.
  - `git diff --stat` shows only added lines in `lazer.json` (12 feed blocks),
    no incidental reformatting elsewhere, and feed 3409's lines are not part
    of the diff.
  - Feeds remain sorted ascending by `feedId`.

## Scope / Out of scope

- **In scope**: 12 spot `/USD` feeds, 1:1 with the CSV rows (one remapped ID).
- **Out of scope**: any change to existing feeds (especially feed 3409); any
  reformatting of `metadata.description`; promoting these to `STABLE`;
  publisher-list tuning (copy 3329 verbatim per decision).
