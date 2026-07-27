# rename_numeric_feed_names — Human-Readable Names for Number-Denominated Equities

**Date:** 2026-07-28
**Status:** Design approved, pending implementation plan
**Module:** `rename_numeric_feed_names.py` (repo root)

## Background & Motivation

Feeds for equities listed in Hong Kong, Japan, South Korea and mainland China carry a
purely numeric `metadata.name`, because those exchanges issue numeric instrument codes
rather than alphabetic tickers. Feed 3520 is representative:

```
symbol          Equity.CN.688825/CNY
name            688825
description     CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN
quote_currency  CNY
```

`688825` is unreadable in any list, report or dashboard that surfaces `metadata.name`.
The company name is already present in `metadata.description`, suffixed with the
spelled-out quote currency.

### Why not short mnemonic tickers

The initial instinct was to mint short alphabetic codes (`CXMT` for Changxin Memory
Technologies). This does not generalize:

- HKEX, TSE, KRX, SSE and SZSE **do not issue alphabetic tickers**. The number _is_ the
  official identifier. Bloomberg renders it `700 HK Equity`; Refinitiv `0700.HK`. The
  Datascope RICs already in the config confirm this — all numeric roots (`688825.SS`).
- `CXMT` is a company brand abbreviation, not an exchange identifier. No exchange,
  vendor or reference-data feed publishes it as such, so there is no source to join
  against.
- It is not mechanically derivable: an acronym of `CHANGXIN MEMORY TECHNOLOGIES` yields
  `CMT`, not `CXMT` (the `X` comes from the Chinese romanization 长鑫).
- Of the 452 affected feeds, only a few dozen have any recognized latin abbreviation.
  For `TAISEI CORP`, `YUHAN` or `SUZHOU EVERBRIGHT PHOTONICS CO LTD`, a minted code
  would be an unverifiable private identifier — strictly worse than the real exchange
  number it replaced.

### Existing precedent in the config

The company-name convention is already live. Feeds 3293–3303 (STABLE, US equities)
were added with exactly this shape:

```
Equity.US.WOLF/USD   name: WOLFSPEED INC          desc: WOLFSPEED INC / US DOLLAR
Equity.US.SIRI/USD   name: SIRIUSXM HOLDINGS INC  desc: SIRIUSXM HOLDINGS INC / US DOLLAR
Equity.US.NOK/USD    name: NOKIA OYJ              desc: NOKIA OYJ / US DOLLAR
```

This change applies the same convention to the number-denominated markets, which never
received it. The exchange code is never lost — it remains in `symbol`.

## Findings from `lazer-state.json` (3,627 feeds)

All figures below were measured against the live config on 2026-07-28.

**Affected feeds — 452 total:**

| Symbol prefix | Numeric names | Total feeds |
| ------------- | ------------- | ----------- |
| `Equity.JP.`  | 235           | 236         |
| `Equity.KR.`  | 101           | 107         |
| `Equity.HK.`  | 100           | 105         |
| `Equity.CN.`  | 16            | 16          |

By state: 344 `COMING_SOON`, 108 `STABLE`. The 12 feeds in these prefixes that are _not_
candidates (8 `INACTIVE`, 4 `COMING_SOON`) carry non-numeric names — deprecated feeds and
index futures such as `Equity.KR.KSM6/KRW`.

**Description structure is uniform.** All 452 descriptions contain exactly one `" / "`
separator (space-slash-space), and the trailing segment always matches the feed's
`quote_currency`:

| quote_currency | Description tail   | Count |
| -------------- | ------------------ | ----- |
| JPY            | `JAPANESE YEN`     | 235   |
| KRW            | `SOUTH KOREAN WON` | 101   |
| HKD            | `HONG KONG DOLLAR` | 100   |
| CNY            | `CHINESE YUAN`     | 16    |

Zero feeds are missing a description.

**Name collisions — exactly 2 pairs**, both same-issuer dual listings:

```
GIGADEVICE SEMICONDUCTOR INC   3339 Equity.CN.603986/CNY  |  3360 Equity.HK.3986/HKD
MONTAGE TECHNOLOGY CO LTD      3341 Equity.CN.688008/CNY  |  3358 Equity.HK.6809/HKD
```

Checked against all 3,627 feeds: zero collisions with any feed outside the candidate
set. `metadata.name` is already non-unique in production — 83 distinct names are shared
across 176 feeds, including genuinely ambiguous cases (`BA` = both Boeing and BAE
Systems; `AAL` = both American Airlines and Anglo American).

**JSON round-trip is byte-clean.** `json.dumps(data, indent=2, ensure_ascii=False)`
reproduces the file exactly, with no trailing newline. `ensure_ascii=False` is
load-bearing: the file contains 9 non-ASCII characters (all in FX/crypto descriptions,
none in the candidate set) that the default `ensure_ascii=True` would escape into
`\uXXXX` across otherwise-untouched lines.

**Data quirks to handle:** several descriptions carry trailing whitespace (`'CJ CORP '`,
`'LG CORP '`), so derivation must strip.

## Goal

Replace the numeric `metadata.name` with the company name for the 452 affected feeds,
deriving it from `metadata.description` minus the currency suffix, with a
version-controlled override file for hand-curated exceptions.

For feed 3520: `688825` → `CHANGXIN MEMORY TECHNOLOGIES`.

## Scope

**In scope:**

- New standalone script `rename_numeric_feed_names.py` at repo root.
- Committed override file `feed_name_overrides.csv` at repo root, pre-filled with the
  4 dual-listing disambiguation rows.
- Unit tests `tests/test_rename_numeric_feed_names.py`.
- Docs: `docs/rename_numeric_feed_names.md` plus a row in the CLAUDE.md Scripts table.

**Out of scope:**

- `metadata.symbol` is never modified. The exchange code remains in
  `Equity.CN.688825/CNY`, so the numeric identifier is never lost.
- `metadata.description` is never modified. The full company name is always preserved
  there, and the existing description typos (`INDUSTRIAL AND COMMERICAL BANK OF CHINA`,
  `ABCELERRA BIOLOGICS INC`, `CAMBRICORD TECHNOLOGIES CORP LTD`) are left as-is.
- No other metadata field, feed, or config file is touched.
- Minting short mnemonic tickers in bulk. Individual mnemonics such as `3520,CXMT` are
  supported through the override file, on demand.
- Integration into `tools/edit-config/edit_config.py`. This is a standalone one-off
  script by explicit decision.

## Design

### 1. File I/O

Read with `encoding="utf-8"`, `json.loads`, mutate the in-memory document, then write
`json.dumps(data, indent=2, ensure_ascii=False)` with `encoding="utf-8"` and **no
trailing newline**. Because the round-trip is byte-identical, the only difference
between the input and output files is the changed `"name":` lines.

The no-trailing-newline requirement does not conflict with the repo's `end-of-file-fixer`
pre-commit hook: config files are gitignored (`.gitignore:45` → `lazer*.json`), so the
hook never sees them.

### 2. Selection guard

A feed is a candidate if and only if all three conditions hold:

1. `symbol` starts with one of the configured prefixes. Default set:
   `Equity.HK.`, `Equity.JP.`, `Equity.KR.`, `Equity.CN.`. Overridable via a repeatable
   `--symbol-prefix` flag for markets added later.
2. `metadata.name` matches `^[0-9]+[A-Za-z]?$`.
3. `metadata.description` contains at least one `" / "` separator (space-slash-space).

Condition 2 makes the script **idempotent**: once renamed, a feed no longer matches, so
a second run is a no-op. This matters because 344 of the 452 are `COMING_SOON` and the
script will be re-run as further feeds land.

### 3. Derivation

```python
head, sep, tail = description.rpartition(" / ")
name = head.strip()
```

`rpartition` splits on the last separator, so a company name containing `" / "` would be
preserved rather than truncated. `.strip()` handles the trailing-whitespace cases.

**Currency validation.** The derived `tail` must equal the expected currency name for
the feed's `quote_currency`:

```
CNY → CHINESE YUAN      HKD → HONG KONG DOLLAR
JPY → JAPANESE YEN      KRW → SOUTH KOREAN WON
```

All 452 feeds pass this check today. Its purpose is forward safety: if a feed arrives
with a malformed description, an unmapped `quote_currency`, or from a market not in the
table, the feed is **skipped and reported** rather than having a mangled value written
into `name`. An unmapped currency is a skip with an explanatory message, not a crash.

A derived name that is empty after stripping is also a skip-with-report.

### 4. Override file

`--name-overrides <path>`, a CSV with header `feed_id,name`:

```csv
feed_id,name
3339,GIGADEVICE SEMICONDUCTOR INC (CN)
3360,GIGADEVICE SEMICONDUCTOR INC (HK)
3341,MONTAGE TECHNOLOGY CO LTD (CN)
3358,MONTAGE TECHNOLOGY CO LTD (HK)
```

Overrides are applied after rule-based derivation and take precedence over it.

**An override may target any feed under the configured symbol prefixes, whether or not
it is a current candidate.** This is deliberate. After the bulk rename runs, feed 3520's
name is `CHANGXIN MEMORY TECHNOLOGIES` and is no longer numeric; a candidates-only rule
would make it impossible to later pin `CXMT`. Prefix-scoping keeps the blast radius
tight while leaving that door open.

Validation, all fatal and checked before any write:

- `feed_id` must parse as an integer and exist in the config.
- The target feed's `symbol` must start with a configured prefix.
- `name` must be non-empty after stripping.
- No duplicate `feed_id` values within the CSV.
- Missing file, absent header row, or missing required columns are load errors.

The file is loaded only when `--name-overrides` is passed. There is no implicit default
path — the same command must behave identically regardless of working directory. The
committed `feed_name_overrides.csv` exists so the disambiguation rows are
version-controlled and reviewed; the duplicate-name warning (§6) is the backstop that
catches a forgotten flag.

### 5. Dual-listing disambiguation

The two colliding pairs are disambiguated by appending the **symbol's market segment**
in parentheses — `(CN)` and `(HK)`, taken from `Equity.CN.` / `Equity.HK.`.

`(CN)` is used rather than `(SH)` despite both mainland RICs being Shanghai (`.SS`):
2 of the 16 CN feeds have no RIC yet, Shenzhen listings are plausible later, and the
symbol segment is the field that actually establishes feed identity.

**This is done through override rows, not automatic collision detection.** Automatic
suffixing interacts badly with the idempotency guard: when a new dual listing lands
later, its already-renamed sibling is no longer a candidate and cannot be touched,
producing an asymmetric pair —

```
existing feed  →  FOO CORP         (bare, untouchable)
new feed       →  FOO CORP (HK)    (suffixed)
```

— which misleadingly implies the bare entry is the primary listing when it is merely
the one added first. Correcting that would require rewriting already-renamed feeds on
every run, breaking idempotency and permanently widening the blast radius to serve four
rows. Explicit override rows give the same result with none of that, and guarantee a
name never changes as a side effect of adding an unrelated feed.

### 6. Safety and reporting

**Dry-run by default; `--apply` writes.** This follows `edit_config.py` rather than the
older `--dry-run`-flag convention, so the failure mode is inaction.

**Backup.** Before writing, copy the config to `<config>.bak`. Suppressible with
`--no-backup`.

**Console report:**

- A change table: `feed_id`, `symbol`, old name, new name, source (`rule` or `override`).
- A skipped-feed list with a per-feed reason.
- A warning block for any resulting duplicate name, listing every feed sharing it:

```
WARNING  duplicate name 'GIGADEVICE SEMICONDUCTOR INC'
           3339  Equity.CN.603986/CNY
           3360  Equity.HK.3986/HKD
```

Duplicates are a **warning, not an error** — `metadata.name` is already non-unique
across 176 feeds in production, and the two pairs here refer to the same issuer. The
warning is actionable: it fires, you add override rows, it clears.

- A summary line: changed, skipped, and duplicate-name warnings.

**Two-stage verification (as built).** This section originally specified a single
post-write check; during implementation, a Task 4 review round found that a line-level
check alone cannot catch a new name applied to the wrong feed (a value swap between two
renamed feeds is invisible to a check that only compares changed values as an unordered
multiset). `verify_feed_names` was added to close that gap, and verification was split
into two stages so a dry run is checked too, not just `--apply`. The section below
describes what shipped, not the original one-check design.

- **Before writing** (`verify_text`, runs on every invocation including dry runs):
  textual only. Asserts the line count is unchanged, that the number of differing lines
  equals the number of planned changes, that every differing line is a `"name":` line,
  and that the multiset of changed values matches the plan. It proves no line outside
  the expected `"name":` lines moved, but it cannot distinguish a feed's
  `metadata.name` from `exchanges[].name`, and — because it only compares values as a
  set — it cannot detect two changed feeds having their new names swapped.

- **After writing** (`verify_on_disk`, `--apply` only): re-reads the file from disk and
  asserts it parses as JSON, that the feed count is unchanged, re-runs `verify_text`,
  then runs `verify_feed_names`. `verify_feed_names` is JSON-path-aware — it diffs
  `metadata.name` per `feedId` between the before and after data and asserts the set of
  changed feeds exactly matches the plan, each with its intended new name. This is what
  actually catches a wrong-feed / swapped-name write; the pre-write text check cannot.

Any failure at either stage aborts loudly with exit code 1. Because the feed-count and
JSON-parse checks, and `verify_feed_names` itself, only run post-write, a dry run's
safety guarantee is weaker than `--apply`'s: it only has the line-level proof, not the
JSON-path-aware one.

### 7. Known consumer of `metadata.name`

`update_lazer_symbols.py:98` builds a `name → feedId` dictionary, which is last-write-
wins on duplicates. This is pre-existing behaviour — it already collides on `BA` and
`AAL` today — and that script operates on the old config format and never touches these
feeds. No new hazard, noted here so it is not rediscovered as a surprise.

## Testing

`tests/test_rename_numeric_feed_names.py`, fixture-based on a small synthetic config:

1. Happy path — numeric name replaced by description minus currency.
2. Trailing whitespace in description is stripped (`'CJ CORP '` → `CJ CORP`).
3. Idempotency — a second run over already-renamed output produces zero changes.
4. Currency mismatch — description tail not matching `quote_currency` is skipped and
   reported.
5. Unmapped `quote_currency` is skipped and reported, not raised.
6. Empty derived name is skipped and reported.
7. Feed outside the configured prefixes is never touched.
8. Override applied to a current candidate wins over the derived name.
9. Override applied to an already-renamed (non-candidate) feed is accepted.
10. Override targeting an out-of-prefix feed is a fatal error.
11. Duplicate `feed_id` in the override CSV is a fatal error.
12. Malformed override CSV (missing header/column, missing file) is a load error.
13. Duplicate resulting names emit a warning and still write.
14. Untouched feeds are byte-identical after a write.
15. Dry-run writes nothing and creates no backup.

Real-data smoke test: dry-run against `lazer-state.json` and assert exactly 452 changes
and 2 duplicate warnings (or 0 warnings and 4 override-sourced changes when
`feed_name_overrides.csv` is supplied).

Per CLAUDE.md, the repo-root `pytest -q` fails on a pre-existing conftest name clash, so
this suite is run on its own:

```bash
pytest tests/test_rename_numeric_feed_names.py -v
```

## Definition of Done

- [ ] `rename_numeric_feed_names.py` implemented, dry-run by default.
- [ ] `feed_name_overrides.csv` committed with the 4 disambiguation rows.
- [ ] All 15 unit tests plus the smoke test pass.
- [ ] Dry-run against `lazer-state.json` reports exactly 452 changes, 0 skips.
- [ ] With `--name-overrides feed_name_overrides.csv`, 0 duplicate warnings.
- [ ] `docs/rename_numeric_feed_names.md` written; CLAUDE.md Scripts table updated.
- [ ] `pre-commit run --files <changed files>` passes.
