# Short Name Candidates (generate_short_name_candidates.py)

Proposes shorter display names for Hong Kong, Japan, South Korea and mainland China
equity feeds, for a human to review before adding to `feed_name_overrides.csv`. This
script never writes to any Lazer config file.

HKEX and KRX publish an official English short/abbreviated name per listed company;
Yahoo Finance's `shortName` field reflects this and is reachable via `yfinance`
(already a repo dependency). JPX and SSE/SZSE publish no equivalent, so JP/CN feeds are
handled instead by stripping trailing corporate-designator words (`CORP`, `LTD`, `INC`,
`CO`, `HOLDINGS`, etc.) off the name `rename_numeric_feed_names.py` already derives from
`metadata.description`.

See `docs/superpowers/specs/2026-07-28-short-name-candidates-design.md` for the full
design and the measurements behind it.

## Usage

```bash
python3 generate_short_name_candidates.py --config lazer-state.json

# Write to a specific path
python3 generate_short_name_candidates.py --config lazer-state.json \
    --output name_override_candidates.csv

# Narrow to one market
python3 generate_short_name_candidates.py --config lazer-state.json \
    --symbol-prefix Equity.KR.
```

## Arguments

| Argument          | Description                             | Required | Default                                                |
| ----------------- | --------------------------------------- | -------- | ------------------------------------------------------ |
| `--config`        | Path to the Lazer config JSON           | Yes      | —                                                      |
| `--symbol-prefix` | Symbol namespace to process; repeatable | No       | `Equity.HK.`, `Equity.JP.`, `Equity.KR.`, `Equity.CN.` |
| `--output`        | Where to write the review CSV           | No       | `name_override_candidates.csv`                         |

## Strategies

**HK / KR — Yahoo Finance `shortName`.** Builds a Yahoo ticker from the numeric
exchange code in `symbol` (HK: zero-padded to 4 digits + `.HK`; KR: code + `.KS`,
retrying `.KQ` on a KOSDAQ listing), fetches `shortName`, and normalizes it: inserts a
space at camelCase boundaries (`HyundaiMtr` → `HYUNDAI MTR`), replaces stray punctuation
with spaces (`CO.,LTD.` → `CO LTD`), collapses whitespace, uppercases. Share-class
markers (`-W`, `-S`, `-UW`) are preserved and flagged in `notes` rather than stripped,
since they carry real meaning.

**JP / CN — corporate-suffix stripping.** Works off the same description-derived name
`rename_numeric_feed_names.py` already produces, so it runs identically whether the
feed's current `metadata.name` is still numeric or already renamed. Iteratively removes
trailing words in `{CORP, CORPORATION, LTD, LIMITED, INC, CO, COMPANY, HOLDINGS, HLDGS,
PLC, KAISHA, KABUSHIKI}` plus a dangling `&`. Deliberately never strips `GROUP`,
`INDUSTRIES`, or `HEAVY` — these are conventionally part of how a company is actually
referred to, not legal-entity boilerplate. A feed with no matching suffix produces no
candidate (left for manual handling via `feed_name_overrides.csv`).

## Output

`name_override_candidates.csv` — not committed, a working artifact:

```csv
feed_id,symbol,current_name,proposed_name,source,notes
1610,Equity.HK.0005/HKD,0005,HSBC HOLDINGS,yahoo_shortname,
2080,Equity.JP.7203/JPY,7203,TOYOTA MOTOR,suffix_stripped,
```

Copy the rows you accept into `feed_name_overrides.csv`; they then flow through the
existing `rename_numeric_feed_names.py --apply --name-overrides feed_name_overrides.csv`
path unchanged.

## Tests

```bash
pytest tests/test_generate_short_name_candidates.py -v
```

All `yfinance` calls are mocked — no real network access in the test suite.
