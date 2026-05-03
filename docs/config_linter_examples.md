# Config Linter — Trigger Examples

Companion to [`config_linter.md`](config_linter.md). For each rule emitted by `config_linter.py`, this document shows the smallest config fragment that would trigger it, the resulting message, and the most common reasons a rule does **not** fire when you might expect it to.

Examples are minimal: only the fields needed to trigger the rule are shown. Assume each fragment is one entry inside the top-level `feeds` (or `publishers`) array of `after.json`. State defaults to `STABLE` unless noted.

---

## Errors

### E001 — Duplicate `feedId`

Two feed entries share the same `feedId`. Runs on **all** feeds, including `INACTIVE`.

```json
{ "feedId": 327, "symbol": "FX.EURUSD/USD", "state": "STABLE",  ... }
{ "feedId": 327, "symbol": "FX.GBPUSD/USD", "state": "INACTIVE", ... }
```

> `E001  feedId 327 is duplicated (feeds[12], feeds[418])`

---

### E002 — Duplicate `symbol` within STABLE/COMING_SOON

Two **active-pipeline** feeds share the same `symbol`. `INACTIVE` feeds are excluded so a retired feed's symbol can be reused.

```json
{ "feedId": 1163, "symbol": "Equity.US.NVDA/USD", "state": "STABLE",      ... }
{ "feedId": 9999, "symbol": "Equity.US.NVDA/USD", "state": "COMING_SOON", ... }
```

> `E002  symbol 'Equity.US.NVDA/USD' duplicated in STABLE/COMING_SOON feeds (feedIds: 1163, 9999)`

**Does not trigger** if one of the two feeds is `INACTIVE`.

---

### E003 — References unknown `publisherId`

A feed's `allowedPublisherIds` (top-level or session-level) contains an id that is not present in the top-level `publishers` array.

```json
{
  "feedId": 327,
  "symbol": "FX.EURUSD/USD",
  "state": "STABLE",
  "allowedPublisherIds": [55, 71, 9999] // 9999 is not declared in `publishers`
}
```

> `E003  references unknown publisherIds: [9999]`

Session-level variant emits `session REGULAR: references unknown publisherIds: [...]`.

**Does not trigger** on `INACTIVE` feeds.

---

### E004 — `minPublishers >= publisher count` (no fault tolerance)

A `STABLE` non-exempt feed sets `minPublishers` to a value ≥ the number of allowed publishers, leaving zero headroom. A single publisher dropping out would knock the feed offline.

```json
{
  "feedId": 1163,
  "symbol": "Equity.US.NVDA/USD",
  "state": "STABLE",
  "metadata": { "asset_type": "equity" },
  "minPublishers": 5,
  "allowedPublisherIds": [10, 20, 30, 40, 50] // count = 5, min = 5
}
```

> `E004  minPublishers (5) >= publisher count (5), no fault tolerance`

Session-level variant: `session REGULAR: minPublishers (3) >= publisher count (3)`.

**Exempt asset types** (no headroom required): `funding-rate`, `custom`, `crypto-redemption-rate`, `nav`, `crypto-index`, `kalshi`. **Does not trigger** on non-STABLE feeds.

---

### E005 — STABLE feed with no publishers

A `STABLE` feed has an empty `allowedPublisherIds` array.

```json
{
  "feedId": 458,
  "symbol": "Crypto.BTC/USD",
  "state": "STABLE",
  "allowedPublisherIds": []
}
```

> `E005  STABLE feed with no publishers`

---

### E006 — Non-equity feed has extended sessions

A non-equity feed declares `PRE_MARKET`, `POST_MARKET`, or `OVER_NIGHT` sessions. These are exclusively meaningful for US equities.

```json
{
  "feedId": 346,
  "symbol": "Metal.XAU/USD",
  "state": "STABLE",
  "metadata": { "asset_type": "metal" },
  "marketSchedules": [
    { "session": "REGULAR", "marketSchedule": "..." },
    { "session": "PRE_MARKET", "marketSchedule": "..." }
  ]
}
```

> `E006  non-equity (metal) has extended sessions: ['PRE_MARKET']`

---

### E007 — Missing required field

A feed is missing one or more of: `feedId`, `symbol`, `state`, `kind`, `metadata.asset_type`. Applies to **all** feeds.

```json
{
  "feedId": 2279,
  "symbol": "Equity.US.DMH6/USD",
  "state": "STABLE",
  "kind": "PRICE",
  "metadata": { "description": "..." }
}
```

> `E007  missing required fields: metadata.asset_type`

---

### E008 — Session publisher not in top-level list

A session's `allowedPublisherIds` contains an id that is **valid** (declared in `publishers`) but not present in the feed's top-level `allowedPublisherIds`. Different from E003: that one catches references to publishers the system doesn't know about; E008 catches references to publishers the system knows but this feed does not declare.

```json
{
  "feedId": 1163,
  "state": "STABLE",
  "allowedPublisherIds": [10, 20, 30],
  "marketSchedules": [
    {
      "session": "REGULAR",
      "allowedPublisherIds": [10, 20, 99] // 99 valid globally, not in [10,20,30]
    }
  ]
}
```

> `E008  session REGULAR: publisherIds [99] not in top-level list`

---

### E009 — STABLE feed references `.Test`-named publisher

A `STABLE` feed references a publisher whose `name` ends in `.test` (case-insensitive). Test publishers should never appear on production feeds.

```json
// publishers entry
{ "publisherId": 49, "name": "AcmeMM.Test", "keyType": "PROD" }

// feed entry
{
  "feedId": 458, "symbol": "Crypto.JITOSOL/USD", "state": "STABLE",
  "allowedPublisherIds": [49]
}
```

> `E009  STABLE feed references .Test-suffixed publishers: [49]`

Compare with **W007**, which fires on `keyType == "TEST"` instead of `name` suffix.

---

### E010 — Duplicate session in `marketSchedules`

Two sub-checks, both emit `E010`.

**(a) Same `session` value repeats across entries:**

```json
"marketSchedules": [
  { "session": "REGULAR", "marketSchedule": "America/New_York;0930-1600;..." },
  { "session": "REGULAR", "marketSchedule": "Europe/London;0800-1630;..." }
]
```

> `E010  duplicate session(s) in marketSchedules: ['REGULAR']`

**(b) The whole `(session, marketSchedule)` tuple is repeated:**

```json
"marketSchedules": [
  { "session": "PRE_MARKET", "marketSchedule": "America/New_York;0400-0930;..." },
  { "session": "PRE_MARKET", "marketSchedule": "America/New_York;0400-0930;..." }
]
```

> `E010  duplicate verbatim marketSchedules entry`

**Does not trigger** on `INACTIVE` feeds. Also does not trigger on duplicate JSON keys _within a single object_ — `json.loads` silently keeps only the last value, so the duplicate is gone before the linter ever runs.

---

### E011 — Schedule inconsistency within asset group

Within a peer group of `STABLE` feeds (grouped by `(asset_type, equity_listing_prefix?, futures_root?)`), two or more feeds use distinct `marketSchedule` strings for the same session. Every minority feed is flagged; the majority schedule is treated as the reference.

```json
// Group key: ("equity", "US")  --  US equity spot peer group
{ "feedId": 1163, "symbol": "Equity.US.NVDA/USD", "state": "STABLE",
  "marketSchedules": [{ "session": "REGULAR",
    "marketSchedule": "America/New_York;0930-1600;..." }] }

{ "feedId": 1775, "symbol": "Equity.US.XLK/USD",  "state": "STABLE",
  "marketSchedules": [{ "session": "REGULAR",
    "marketSchedule": "America/New_York;0930-1559;..." }] }   // off-by-one
```

> `E011  REGULAR schedule disagrees with group (equity, US): 2 distinct schedules across 2 STABLE feeds`

**Does not trigger** if all peers agree, if a session has only one STABLE feed, or if the deviating feed is `COMING_SOON` (that's W003 territory).

---

### E012 — Duplicate `metadata.hermes_id`

Two non-INACTIVE feeds share the same `metadata.hermes_id`.

```json
{ "feedId":  964, "metadata": { "hermes_id": "abc...", "asset_type": "equity" }, ... }
{ "feedId": 3126, "metadata": { "hermes_id": "abc...", "asset_type": "equity" }, ... }
```

> `E012  hermes_id 'abc...' duplicated across feedIds: 964, 3126`

---

### E013 — COMING_SOON futures past every `validTo`

A `COMING_SOON` feed with a futures-pattern symbol where **every** `validTo` found anywhere under `marketSchedules[*].benchmarkMapping.*.identifiers[]` is earlier than the linter's current UTC clock. The fix is to flip `state` to `INACTIVE`.

```json
{
  "feedId": 2973,
  "symbol": "Commodities.ALH6/USD",
  "state": "COMING_SOON",
  "marketSchedules": [
    {
      "session": "REGULAR",
      "benchmarkMapping": {
        "datascope_ric": {
          "identifiers": [
            {
              "identifier": "ALH26",
              "validFrom": "2025-12-15T00:00:00Z",
              "validTo": "2026-03-27T17:00:00Z"
            } // already in the past
          ]
        }
      }
    }
  ]
}
```

> `E013  COMING_SOON futures feed has expired (latest validTo: 2026-03-27T17:00:00+00:00); change state to INACTIVE`

**Does not trigger** when at least one `validTo` is in the future, when no identifiers have a `validTo` at all, on `STABLE` or `INACTIVE` feeds, or on non-futures symbols.

---

### E014 — STABLE benchmarkable feed missing `benchmarkMapping`

A `STABLE` feed whose asset type is one of `equity`, `fx`, `metal`, `commodity`, `rates` has a session without a populated `benchmarkMapping`.

```json
{
  "feedId": 327,
  "symbol": "FX.EURUSD/USD",
  "state": "STABLE",
  "metadata": { "asset_type": "fx" },
  "marketSchedules": [
    { "session": "REGULAR", "marketSchedule": "..." } // no benchmarkMapping
  ]
}
```

> `E014  REGULAR session missing benchmarkMapping`

**Does not trigger** on `OVER_NIGHT` sessions (US-equity overnight uses publisher 32 peer comparison, not Datascope), on non-benchmarkable asset types (`crypto`, `funding-rate`, etc.), or on non-STABLE feeds.

---

### E015 — `corporateActions` schema violation

Each entry in `corporateActions[]` is validated against the schema for its `eventType`. The only known type today is `SPLIT`. Five trigger paths:

**(a) Missing `eventType`:**

```json
"corporateActions": [{ "adjustmentFactorNumerator": "2" }]
```

> `E015  corporateActions[0]: missing required field 'eventType'`

**(b) Missing top-level required field for SPLIT:**

```json
"corporateActions": [{
  "eventType": "SPLIT",
  "adjustmentFactorNumerator": "2",
  "rejectionThresholdBips": "100",
  "rejectionWindow": "600.000000000s",
  "activation": { "usEquityExDate": { "exDate": "2026-05-15" } }
  // missing adjustmentFactorDenominator
}]
```

> `E015  corporateActions[0]: missing required field 'adjustmentFactorDenominator'`

**(c) Missing nested required structure:**

```json
"corporateActions": [{
  "eventType": "SPLIT", "adjustmentFactorNumerator": "2",
  "adjustmentFactorDenominator": "1", "rejectionThresholdBips": "100",
  "rejectionWindow": "600.000000000s"
  // missing the entire `activation` object
}]
```

> `E015  corporateActions[0]: missing required field 'activation'`

**(d) Invalid format on a numeric field:**

```json
"corporateActions": [{
  "eventType": "SPLIT", "adjustmentFactorNumerator": "2.5", ...
}]
```

> `E015  corporateActions[0]: 'adjustmentFactorNumerator' has invalid format '2.5' (expected positive numeric string)`

**(e) Invalid `rejectionWindow` or `exDate` format:**

```json
"rejectionWindow": "600s"        // must be N.Ns, e.g. "600.000000000s"
```

> `E015  corporateActions[0]: 'rejectionWindow' has invalid format '600s' (expected N.Ns)`

```json
"activation": { "usEquityExDate": { "exDate": "05/15/2026" } }   // must be YYYY-MM-DD
```

> `E015  corporateActions[0]: 'exDate' has invalid format '05/15/2026' (expected YYYY-MM-DD)`

**Does not trigger** if `eventType` is unknown — that emits `W009` instead, deferring schema validation until the linter is updated.

---

### E016 — Identifier date range overlap

Two consecutive identifiers within the same `(session, vendor)` overlap in time. Identifiers are sorted by `validFrom` and pairs are checked.

**(a) Overlapping ranges:**

```json
"identifiers": [
  { "identifier": "ESH6", "validFrom": "2025-12-15T00:00:00Z", "validTo": "2026-03-21T00:00:00Z" },
  { "identifier": "ESM6", "validFrom": "2026-03-15T00:00:00Z", "validTo": "2026-06-20T00:00:00Z" }
]
```

> `E016  session REGULAR: datascope_ric identifiers 'ESH6' and 'ESM6' have overlapping date ranges`

**(b) Non-last identifier missing `validTo`:**

```json
"identifiers": [
  { "identifier": "ESH6", "validFrom": "2025-12-15T00:00:00Z" },
  { "identifier": "ESM6", "validFrom": "2026-03-15T00:00:00Z", "validTo": "2026-06-20T00:00:00Z" }
]
```

> `E016  session REGULAR: datascope_ric identifier 'ESH6' has no validTo but is followed by 'ESM6'`

**Does not trigger** on vendors with fewer than 2 identifiers, on `INACTIVE` feeds, or when only the **last** identifier omits `validTo` (legitimate open-ended current contract).

---

### E017 — Duplicate `publisherId` in publishers array

Two entries in the top-level `publishers` array share the same `publisherId`.

```json
"publishers": [
  { "publisherId": 55, "name": "AcmeMM",  "keyType": "PROD" },
  { "publisherId": 55, "name": "BetaMM",  "keyType": "PROD" }
]
```

> `E017  publisherId 55 is duplicated (2 occurrences)`

The `feed_id` slot of the finding holds the duplicated id (so each duplicate id gets a unique key for diff-mode).

---

### E018 — Duplicate publisher `name` in publishers array

Two entries share the same `name` (case-sensitive).

```json
"publishers": [
  { "publisherId": 55, "name": "AcmeMM", "keyType": "PROD" },
  { "publisherId": 88, "name": "AcmeMM", "keyType": "PROD" }
]
```

> `E018  publisher name 'AcmeMM' is duplicated (2 occurrences)`

The `symbol` slot of the finding holds the duplicated name.

Both E017 and E018 mirror invariants enforced by the Rust governance tool's `diff_publishers`. They surface a readable error before the Rust tool's stack trace reaches CI.

---

### E019 — Dangling `exchangeId` reference

A feed sets `exchangeId` to a value that is not defined in the top-level `exchanges[]` array (or `exchanges[]` is missing entirely).

```json
"exchanges": [
  { "exchangeId": 1, "name": "NASDAQ", ... }
]

// feed
{ "feedId": 922, "symbol": "Equity.US.AAPL/USD", "exchangeId": 99999, ... }
```

> `E019  feed references exchangeId 99999 which is not defined in exchanges[]`

The id is rendered with `repr()` — string `"1"` and int `1` produce different messages, surfacing accidental type mismatches. When E019 fires for a feed, **E020 and W010 are skipped on the same feed** so the downstream symptoms do not drown out the root cause.

---

### E020 — Session has no schedule source

A feed session has neither an inline `marketSchedule` nor a resolvable inherited schedule. Two flavors:

**Case 1 — feed has no `exchangeId`:**

```json
{
  "feedId": 5000,
  "marketSchedules": [{ "session": "REGULAR", "allowedPublisherIds": [12] }]
}
```

> `E020  feed session REGULAR has no marketSchedule and feed has no exchangeId — no schedule source`

**Case 2 — feed has a resolvable `exchangeId`, but the exchange does not define that session:**

```json
"exchanges": [
  {
    "exchangeId": 1, "name": "NASDAQ",
    "sessions": [{ "session": "REGULAR", "marketSchedule": "America/New_York;..." }]
  }
]

// feed
{
  "feedId": 922, "exchangeId": 1,
  "marketSchedules": [
    { "session": "REGULAR" },
    { "session": "PRE_MARKET" }
  ]
}
```

> `E020  feed session PRE_MARKET has no marketSchedule and exchange 1 does not define a PRE_MARKET session`

Empty-string `marketSchedule: ""` counts as missing. **Does not trigger** when E019 already fired for the feed (the dangling reference is the underlying problem).

---

### E021 — Duplicate exchange tuple

Two **distinct** entries in `exchanges[]` share the same `(name, assetClass, assetSubclass, assetSector)` 4-tuple. Missing classification keys are normalized to their `…UNSPECIFIED` defaults before comparison.

```json
"exchanges": [
  {
    "exchangeId": 1, "name": "NASDAQ",
    "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
    "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
    "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
    ...
  },
  {
    "exchangeId": 2, "name": "NASDAQ",
    "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
    "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
    "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
    ...
  }
]
```

> `E021  duplicate exchange tuple (name=NASDAQ, class=EXCHANGE_ASSET_CLASS_EQUITY, subclass=EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK, sector=EXCHANGE_ASSET_SECTOR_TECHNOLOGY) on exchangeIds [1, 2]`

Same-id duplicates (two entries sharing both the id **and** the tuple) are reported only by **E021's sibling rule E023** — E021 requires distinct ids. Entries that fail E024 (missing `exchangeId` or `name`) are excluded.

---

### E022 — Invalid `holidayOverrides` syntax

A token inside `scheduleOverrides.holidayOverrides[]` does not match `MMDD/{C|O|HHMM-HHMM}`.

```json
{
  "feedId": 2050,
  "exchangeId": 1,
  "marketSchedules": [
    {
      "session": "REGULAR",
      "scheduleOverrides": {
        "holidayOverrides": ["0315/X", "1340/C", "0703/0930-1300"]
      }
    }
  ]
}
```

> `E022  holidayOverrides entry '0315/X' has invalid syntax: unknown kind 'X'` > `E022  holidayOverrides entry '1340/C' has invalid syntax: invalid month 13`

One finding **per bad token**. The third token (`0703/0930-1300`) is valid and produces no finding.

If `holidayOverrides` itself is the wrong type:

```json
"scheduleOverrides": { "holidayOverrides": "0315/C" }
```

> `E022  holidayOverrides must be a list of strings, got str`

Tokens are validated even when the session has an inline `marketSchedule` (in which case the overrides would actually be ignored at runtime, but typos are typos).

---

### E023 — Duplicate `exchangeId` in `exchanges[]`

Two or more entries share the same `exchangeId` value (regardless of name/class/subclass/sector).

```json
"exchanges": [
  { "exchangeId": 1, "name": "NASDAQ", ... },
  { "exchangeId": 1, "name": "BSE",    ... }
]
```

> `E023  duplicate exchangeId 1 appears on 2 entries in exchanges[]`

One finding per duplicate-id group (a 3-way duplicate emits one finding mentioning `appears on 3 entries`). The internal index keeps the **first** entry as canonical, so downstream rules (E019, E020, W010, W011) reason about the first entry while E023 names the collision. Entries that fail E024 are excluded.

---

### E024 — Missing required exchange field

An entry in `exchanges[]` is missing `exchangeId`, `name`, has an empty/missing `sessions` list, or is not an object at all.

```json
"exchanges": [
  "NASDAQ",                                          // not an object
  { "exchangeId": 1 },                               // missing name and sessions
  { "exchangeId": 2, "name": "X", "sessions": [] }   // empty sessions
]
```

> `E024  exchange entry at index 0 is not an object (got str)` > `E024  exchange entry at index 1 is missing required field 'name'` > `E024  exchange entry at index 1 has empty sessions list` > `E024  exchange entry at index 2 has empty sessions list`

One finding **per missing field per entry** — an entry missing both `exchangeId` and `name` produces two findings. Indices are 0-based and address position in the raw `exchanges[]` array (because the entry's own `exchangeId` may be the missing field).

E024 acts as a **gate** for E021/E023/E025: entries lacking `exchangeId` or `name` are excluded from those rules so the report doesn't pile spurious findings on top of a malformed entry. (An entry with empty `sessions` is still well-formed enough for E021/E023/E025 — the inheritance consequences surface as E020 case 2 on each affected feed.)

---

### E025 — Unknown enum value

`assetClass`, `assetSubclass`, or `assetSector` is set to a value not in the documented allowlist (see `Exchange_Configuration_Guide.md` "Classification Enum Reference"). Missing keys default to `…UNSPECIFIED` and are **not** flagged.

```json
{
  "exchangeId": 1,
  "name": "NASDAQ",
  "assetClass": "EXCHANGE_ASSET_CLASS_EQUTIY", // typo
  "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_BANANA"
}
```

> `E025  exchange 1 field assetClass='EXCHANGE_ASSET_CLASS_EQUTIY' is not a known enum value` > `E025  exchange 1 field assetSubclass='EXCHANGE_ASSET_SUBCLASS_BANANA' is not a known enum value`

One finding per offending field per entry. Entries that fail E024 are excluded.

---

## Warnings

### W001 — US equity missing extended sessions

A `STABLE` US equity feed lacks one or more of `REGULAR`, `PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT`.

```json
{
  "symbol": "Equity.US.NVDA/USD",
  "state": "STABLE",
  "marketSchedules": [
    { "session": "REGULAR", "marketSchedule": "..." }
    // PRE_MARKET, POST_MARKET, OVER_NIGHT missing
  ]
}
```

> `W001  STABLE US equity missing sessions: ['OVER_NIGHT', 'POST_MARKET', 'PRE_MARKET']`

---

### W002 — US equity using non-`America/New_York` timezone

A `STABLE` US equity has at least one `marketSchedule` whose first segment (the timezone) is not `America/New_York`.

```json
{
  "symbol": "Equity.US.NVDA/USD",
  "state": "STABLE",
  "marketSchedules": [
    { "session": "REGULAR", "marketSchedule": "America/Chicago;0830-1500;..." }
  ]
}
```

> `W002  US equity using timezone 'America/Chicago' instead of 'America/New_York'`

Fires once per feed (breaks on first offending schedule).

---

### W003 — Schedule deviates from asset-class majority

Across `STABLE + COMING_SOON` feeds in the same group, one feed has a schedule that differs from the most-common one. Like E011 but advisory and includes COMING_SOON. Only fires when a real majority exists (count > 1).

```json
// Group: ("equity", "US"), session REGULAR — 9 feeds use schedule A, 1 uses schedule B
{
  "feedId": 1775,
  "symbol": "Equity.US.XLK/USD",
  "state": "STABLE",
  "marketSchedules": [
    { "session": "REGULAR", "marketSchedule": "...slightly different..." }
  ]
}
```

> `W003  REGULAR schedule deviates from (equity, US) majority`

---

### W004 — COMING_SOON feed with no publishers

```json
{ "state": "COMING_SOON", "allowedPublisherIds": [] }
```

> `W004  COMING_SOON feed with no publishers`

The STABLE equivalent is `E005` (error, not warning).

---

### W005 — `minPublishers` leaves only 1 headroom

A `STABLE` non-exempt feed sets `minPublishers = count - 1`. One publisher down still works, but two would fail. Tighter setting than E004 demands but the same rule's softer cousin.

```json
{
  "state": "STABLE",
  "metadata": { "asset_type": "equity" },
  "allowedPublisherIds": [10, 20, 30, 40, 50],
  "minPublishers": 4 // count = 5, headroom = 1
}
```

> `W005  minPublishers (4) leaves only 1 headroom (5 publishers)`

Session-level variant: `session REGULAR: minPublishers (2) leaves only 1 headroom (3 publishers)`.

**Does not trigger** if `minPublishers == 0` (zero-headroom case is `E005`-ish) or on exempt asset types.

---

### W006 — Duplicate publisher within feed

The same id appears twice inside one feed's `allowedPublisherIds` list.

```json
{ "allowedPublisherIds": [10, 20, 30, 20] }
```

> `W006  duplicate publisherIds in feed: [20]`

---

### W007 — STABLE feed references `keyType=TEST` publisher

A `STABLE` feed lists a publisher whose `keyType` is `TEST` in the `publishers` array. Compare with **E009**, which fires on the publisher's _name_ suffix.

```json
// publishers entry
{ "publisherId": 71, "name": "TestMM", "keyType": "TEST" }

// feed
{ "state": "STABLE", "allowedPublisherIds": [71] }
```

> `W007  STABLE feed references TEST publishers: [71]`

---

### W009 — Unknown `corporateActions` event type

`corporateActions[i].eventType` is not in `_KNOWN_EVENT_TYPES` (currently only `SPLIT`). The schema is not validated for that entry — emitted instead of `E015` so the config change can pass CI while signaling that the linter needs to add support for the new event type.

```json
"corporateActions": [{ "eventType": "DIVIDEND", "amount": "0.50" }]
```

> `W009  corporateActions[0]: unknown eventType 'DIVIDEND', schema not validated`

---

### W010 — Inline `marketSchedule` shadows exchange

A feed sets `exchangeId` AND provides an inline `marketSchedule` for a session that the referenced exchange also defines. Per the protocol, the inline schedule takes priority and the exchange's schedule is silently ignored — usually a migration mistake (forgot to remove the inline string after switching to inheritance).

```json
"exchanges": [{
  "exchangeId": 1, "name": "NASDAQ",
  "sessions": [{ "session": "REGULAR", "marketSchedule": "America/New_York;..." }]
}]

// feed
{
  "feedId": 922, "exchangeId": 1,
  "marketSchedules": [{
    "session": "REGULAR",
    "marketSchedule": "America/New_York;...",   // shadows the exchange
    "allowedPublisherIds": [12, 14]
  }]
}
```

> `W010  feed session REGULAR has both inline marketSchedule and exchangeId 1; inline takes priority — exchange schedule unused for this session`

**Does not trigger** when the referenced exchange does not define that session (nothing to shadow), or when E019 or W011 fired for the feed (those are the cleaner summaries).

---

### W011 — `exchangeId` is dead code

A feed sets `exchangeId` but **every** session has its own inline `marketSchedule` — nothing inherits, so the `exchangeId` is unused noise.

```json
{
  "feedId": 922,
  "exchangeId": 1, // never inherits
  "marketSchedules": [
    { "session": "REGULAR", "marketSchedule": "America/New_York;..." },
    { "session": "PRE_MARKET", "marketSchedule": "America/New_York;..." }
  ]
}
```

> `W011  feed has exchangeId 1 but every session has an inline marketSchedule — exchangeId is unused`

When W011 fires for a feed, **W010 is suppressed on the same feed** to avoid emitting a per-session warning for every shadowed session in addition to the per-feed summary. **Does not trigger** on feeds with zero sessions (vacuous truth).

---

## Cross-rule cheatsheet

| Symptom in your config                                 | Rule to look for              |
| ------------------------------------------------------ | ----------------------------- |
| Same `feedId` on two feeds                             | E001                          |
| Same `symbol` on two non-INACTIVE feeds                | E002                          |
| `allowedPublisherIds` references id missing globally   | E003                          |
| Session lists a valid id absent from feed's top-level  | E008                          |
| `STABLE` references publisher named `*.test`           | E009                          |
| `STABLE` references publisher with `keyType=TEST`      | W007                          |
| `STABLE` feed has empty publishers                     | E005                          |
| `COMING_SOON` feed has empty publishers                | W004                          |
| `minPublishers >= count`                               | E004                          |
| `minPublishers == count - 1`                           | W005                          |
| Same publisher id twice in one feed                    | W006                          |
| Duplicate `marketSchedules` entry                      | E010                          |
| Two STABLE peers disagree on schedule                  | E011                          |
| Active feed disagrees with majority schedule           | W003                          |
| Non-equity has PRE/POST/OVERNIGHT session              | E006                          |
| US equity missing PRE/POST/OVERNIGHT                   | W001                          |
| US equity not in `America/New_York`                    | W002                          |
| Two non-INACTIVE feeds share `hermes_id`               | E012                          |
| `COMING_SOON` futures past all `validTo`               | E013                          |
| `STABLE` benchmarkable feed missing `benchmarkMapping` | E014                          |
| `corporateActions` entry malformed                     | E015 (known) / W009 (unknown) |
| Identifier date ranges overlap inside one vendor       | E016                          |
| Duplicate `publisherId` or publisher `name`            | E017 / E018                   |
| Feed `exchangeId` not in `exchanges[]`                 | E019                          |
| Session has no inline schedule and no inheritance      | E020                          |
| Two exchanges share `(name, class, subclass, sector)`  | E021                          |
| Bad token in `scheduleOverrides.holidayOverrides[]`    | E022                          |
| Two exchanges share the same `exchangeId`              | E023                          |
| Exchange entry missing `exchangeId`/`name`/`sessions`  | E024                          |
| Unknown `assetClass`/`assetSubclass`/`assetSector`     | E025                          |
| Inline schedule shadows exchange-provided schedule     | W010                          |
| `exchangeId` set but every session has inline schedule | W011                          |
