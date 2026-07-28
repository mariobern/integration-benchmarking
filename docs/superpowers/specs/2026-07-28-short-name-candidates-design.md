# generate_short_name_candidates — Shorter Display Names for HK/JP/KR/CN Equities

**Date:** 2026-07-28
**Status:** Design approved, pending implementation plan
**Module:** `generate_short_name_candidates.py` (repo root)

## Background & Motivation

`rename_numeric_feed_names.py` (see
[2026-07-28-numeric-feed-name-rename-design.md](2026-07-28-numeric-feed-name-rename-design.md))
replaced numeric `metadata.name` values for HK/JP/KR/CN equities with the full company
name derived from `metadata.description`. That design explicitly rejected minting short
mnemonic tickers in bulk, on the grounds that these exchanges don't issue alphabetic
tickers and there was no verifiable source for an abbreviation.

This design revisits that specific point: is there an authoritative, low-cost source for
shorter display names after all? The answer turned out to be market-dependent.

### Research findings

**HK and KR have official short-name conventions; JP and CN do not.**

- HKEX publishes an official English "Stock Short Name" (≤8 characters) for every listed
  company, used on the exchange's own quote pages.
- KRX has an equivalent official abbreviated English name convention.
- JPX (Tokyo) and SSE/SZSE (Shanghai/Shenzhen) publish no equivalent English
  abbreviation standard.

**Yahoo Finance's `shortName` field reflects this split, and is already reachable in
this repo.** `isin_resolver.py` already depends on `yfinance` (`requirements.txt:
yfinance>=1.1.0`) and already reads `info.get("longName") or info.get("shortName")` for
US tickers. Live-testing the same field against 20 real HK/KR feeds pulled from
`lazer-state.json` (10 each) resolved 20/20, producing genuinely compact,
exchange-native abbreviations: `SK TELECOM → SKTelecom`, `HYUNDAI MOTOR → HyundaiMtr`,
`HSBC HOLDINGS PLC → HSBC HOLDINGS`. Against 20 JP/CN feeds in the same test, Yahoo's
`shortName` was either byte-identical to the long legal name (JP) or a naive fixed-width
truncation that sometimes cuts mid-word (CN, e.g. `ADVANCED MICRO-FABRICATION EQUI`) —
strictly no better, and sometimes worse, than the description-derived name the existing
script already produces.

**For JP/CN, stripping trailing legal-entity words from the existing derived name works
well instead.** Tested against all 251 real JP/CN candidate feeds in `lazer-state.json`:
213 (85%) produce a clean, recognizable result by iteratively removing a small
vocabulary of trailing corporate-designator words — `TOYOTA MOTOR CORPORATION → TOYOTA
MOTOR`, `SOFTBANK GROUP CORP → SOFTBANK GROUP`, `NINTENDO CO LTD → NINTENDO`. No network
call needed for this path.

## Goal

Produce a review CSV proposing shorter names for HK/JP/KR/CN equity feeds — HK/KR from
Yahoo Finance's `shortName`, JP/CN from suffix-stripping — for a human to curate into the
existing, version-controlled `feed_name_overrides.csv`. This tool never writes to any
config file itself.

## Scope

**In scope:**

- New standalone script `generate_short_name_candidates.py` at repo root.
- Two independently-testable strategy functions, one per data source.
- CSV output of proposed changes plus a console skip/reason report.
- Unit tests `tests/test_generate_short_name_candidates.py`, `yfinance` calls mocked.
- Docs: `docs/generate_short_name_candidates.md` plus a row in the CLAUDE.md Scripts
  table.

**Out of scope:**

- Writing to `lazer-state.json`, `feed_name_overrides.csv`, or any other config file.
  This tool's entire output is a CSV for human review; merging accepted rows into
  `feed_name_overrides.csv` is a manual step, after which the existing
  `rename_numeric_feed_names.py --apply --name-overrides feed_name_overrides.csv` path
  (unchanged) applies them.
- Live network calls for JP/CN (suffix-stripping is offline-only by design; see
  Research findings above for why Yahoo doesn't help there).
- Automatic resolution of share-class markers (`-W`, `-S`, `-UW` suffixes Yahoo attaches
  to some HK tickers) — these carry real meaning (e.g. weighted voting rights) and are
  left in place, flagged in `notes` for the reviewer.
- Integration into `edit_config.py` or `rename_numeric_feed_names.py` itself — kept as a
  separate script so the existing script's fully-offline, deterministic, idempotent
  round-trip guarantee is never entangled with a live network dependency.

## Design

### 1. Candidate selection

Runs over every feed whose `symbol` starts with one of the configured prefixes
(`Equity.HK.`, `Equity.JP.`, `Equity.KR.`, `Equity.CN.` by default, overridable via
repeatable `--symbol-prefix` as in the existing script). Unlike
`rename_numeric_feed_names.py`, this tool does **not** require the current
`metadata.name` to still be numeric — it operates on the canonical company name derived
from `metadata.description` via the imported `derive_name()`, so it works identically
whether a feed has already been renamed (STABLE, long name in place) or not
(COMING_SOON, still numeric). This matches how `feed_name_overrides.csv` is already
allowed to target either kind of feed.

### 2. HK/KR strategy — `suggest_from_yahoo(feed)`

```
ticker = name.zfill(4) + ".HK"                      # HK
ticker = name + ".KS"                                # KR, retry ".KQ" on not-found
```

- Query `yfinance.Ticker(ticker).info["shortName"]`.
- Normalize before comparing/emitting:
  1. Insert a space at camelCase boundaries: `(?<=[a-z])(?=[A-Z])` (lower→upper) and
     `(?<=[A-Z])(?=[A-Z][a-z])` (acronym→word), e.g. `HyundaiMtr → Hyundai Mtr`,
     `SKTelecom → SK Telecom`.
  2. Replace `.` and `,` with a space (handles `CO.,LTD.` → `CO LTD` without gluing
     words together).
  3. Collapse repeated whitespace, strip, uppercase.
- Skip and report (not added to the output CSV) when: the ticker isn't found on any
  suffix tried, `shortName` is missing/empty, or the normalized result is identical to
  the feed's current `metadata.name`.
- `notes` flags a detected trailing share-class marker (single letter after a hyphen,
  e.g. `-W`, `-S`) so the reviewer knows it was preserved intentionally, not missed.

### 3. JP/CN strategy — `suggest_from_suffix_strip(base_name)`

`base_name` is always `derive_name(feed)`'s result (the full company name from
`description`), never the raw current `metadata.name`.

Iteratively pop the last whitespace-delimited token while it (case-insensitively, with
trailing `.`/`,` stripped) is in:

```
CORP, CORPORATION, LTD, LIMITED, INC, CO, COMPANY,
HOLDINGS, HLDGS, PLC, KAISHA, KABUSHIKI
```

or is a bare `&` left dangling after a pop (`MITSUI & CO → MITSUI`, not `MITSUI &`).
Stop when the last token isn't in the vocabulary, or only one token remains (never
strip a name down to nothing).

Deliberately excluded from the vocabulary: `GROUP`, `INDUSTRIES`, `HEAVY` and similar —
these are conventionally part of how the company is actually referred to (`SOFTBANK
GROUP`, `MITSUBISHI HEAVY INDUSTRIES`), not legal-entity boilerplate like `INC`/`LTD`.

Skip (no CSV row) if no token was ever popped — the name is unchanged, which is the
correct outcome for index-tracker/ETF descriptions and malformed source data (e.g. a
missing space producing `COLTD` as a single token) that don't match the vocabulary.
These are left for manual handling via `feed_name_overrides.csv`, consistent with the
"skip and report, never guess" philosophy of the existing script.

### 4. Output

`name_override_candidates.csv` (not committed — a working artifact, like
`price_id_list.csv` from `generate_price_list.py`):

```csv
feed_id,symbol,current_name,proposed_name,source,notes
1610,Equity.HK.0005/HKD,0005,HSBC HOLDINGS,yahoo_shortname,
2176,Equity.KR.005380/KRW,005380,HYUNDAI MOTOR,yahoo_shortname,
1934,Equity.HK.2057/HKD,2057,ZTO EXPRESS,yahoo_shortname,share_class_suffix_stripped_by_yahoo
2080,Equity.JP.7203/JPY,TOYOTA MOTOR CORPORATION,TOYOTA MOTOR,suffix_stripped,
```

Console summary: counts by source, plus a skip list with per-feed reasons (ticker not
found, no `shortName`, no suffix matched, KOSPI/KOSDAQ both failed, etc.) — the same
shape of report as `rename_numeric_feed_names.py`'s existing change/skip tables, for
consistency.

### 5. Error handling

- Network/lookup failures for an individual feed (timeout, ticker not found on either
  KOSPI/KOSDAQ suffix, malformed response) are a per-feed skip with a reason, never a
  crash — mirrors the existing script's per-feed skip-and-report behavior for currency
  mismatches.
- The script is read-only with respect to config: it never opens the config file for
  writing, and has no `--apply` flag at all.

## Testing

`tests/test_generate_short_name_candidates.py`, fixture-based:

1. Yahoo path: camelCase-boundary normalization (`HyundaiMtr`, `SKTelecom`,
   `SamsungHvyInd` cases).
2. Yahoo path: punctuation cleanup (`CO.,LTD.` → `CO LTD`, not `COLTD`).
3. Yahoo path: KOSPI lookup fails, KOSDAQ (`.KQ`) retry succeeds.
4. Yahoo path: both suffixes fail — skip with reason.
5. Yahoo path: normalized result equals current name — skip, no row emitted.
6. Yahoo path: share-class suffix (`-W`) detected and flagged in `notes`, value
   unchanged.
7. Suffix-strip: single-suffix cases (`CORP`, `LTD`, `INC`, `CO`, `HOLDINGS`, `PLC`).
8. Suffix-strip: multi-word iterative case (`... HOLDINGS INC` → strips both).
9. Suffix-strip: `KABUSHIKI KAISHA` two-word Japanese legal form strips fully.
10. Suffix-strip: dangling `&` cleanup (`MITSUI & CO → MITSUI`, not `MITSUI &`).
11. Suffix-strip: `GROUP`/`INDUSTRIES`/`HEAVY` are never stripped.
12. Suffix-strip: no vocabulary match — skip, no row emitted.
13. Suffix-strip: never strips down to an empty name.
14. Feed outside configured prefixes is never touched.

All `yfinance` calls are mocked throughout this suite — no real network access.

Real-data smoke test (manual, not asserted in CI): dry run against `lazer-state.json`
and eyeball a sample of each source's output for plausibility.

Per CLAUDE.md, the repo-root `pytest -q` fails on a pre-existing conftest name clash, so
this suite is run on its own:

```bash
pytest tests/test_generate_short_name_candidates.py -v
```

## Definition of Done

- [ ] `generate_short_name_candidates.py` implemented, read-only (no `--apply`, ever).
- [ ] All 14 automated unit tests pass (`yfinance` mocked).
- [ ] `docs/generate_short_name_candidates.md` written; CLAUDE.md Scripts table updated.
- [ ] `pre-commit run --files <changed files>` passes.
