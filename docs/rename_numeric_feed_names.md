# Numeric Feed Name Rename (rename_numeric_feed_names.py)

Replaces the purely numeric `metadata.name` on Hong Kong, Japan, South Korea and mainland China equity feeds with the company name, derived from `metadata.description` minus its spelled-out currency suffix.

Those exchanges issue numeric instrument codes rather than alphabetic tickers, so `metadata.name` reads as `688825` instead of `CHANGXIN MEMORY TECHNOLOGIES`. The exchange code is never lost — it stays in `symbol` (`Equity.CN.688825/CNY`) — and `metadata.description` is never modified.

## Usage

```bash
# Dry run (default) — preview every change
python3 rename_numeric_feed_names.py --config lazer-state.json

# Apply, with the committed disambiguation overrides
python3 rename_numeric_feed_names.py --config lazer-state.json \
    --name-overrides feed_name_overrides.csv --apply

# Narrow to one market
python3 rename_numeric_feed_names.py --config lazer-state.json \
    --symbol-prefix Equity.JP.
```

## Arguments

| Argument           | Description                                | Required | Default                                                |
| ------------------ | ------------------------------------------ | -------- | ------------------------------------------------------ |
| `--config`         | Path to the Lazer config JSON              | Yes      | —                                                      |
| `--symbol-prefix`  | Symbol namespace to process; repeatable    | No       | `Equity.HK.`, `Equity.JP.`, `Equity.KR.`, `Equity.CN.` |
| `--name-overrides` | CSV of hand-curated names (`feed_id,name`) | No       | —                                                      |
| `--apply`          | Write changes (otherwise dry run)          | No       | False                                                  |
| `--no-backup`      | Skip the `<config>.bak` copy               | No       | False                                                  |

## Selection Rule

A feed is renamed when all three hold:

1. Its `symbol` starts with a configured prefix.
2. Its `metadata.name` matches `^[0-9]+[A-Za-z]?$`.
3. Its `metadata.description` splits on `" / "` with a tail matching the feed's `quote_currency`.

Condition 2 makes the script idempotent — once renamed, a feed stops matching, so re-running is a no-op. This matters because most affected feeds are `COMING_SOON` and go live over time.

| quote_currency | Expected description tail |
| -------------- | ------------------------- |
| CNY            | `CHINESE YUAN`            |
| HKD            | `HONG KONG DOLLAR`        |
| JPY            | `JAPANESE YEN`            |
| KRW            | `SOUTH KOREAN WON`        |

A feed whose tail does not match, whose currency is unmapped, or whose derived name is empty is **skipped and reported** — never written with a mangled value.

## Override File

`feed_name_overrides.csv` pins names by hand. It takes precedence over the rule and bypasses the currency check.

```csv
feed_id,name
3339,GIGADEVICE SEMICONDUCTOR INC (CN)
3360,GIGADEVICE SEMICONDUCTOR INC (HK)
```

Use it for short codes where one genuinely exists (`3520,CXMT`) and to disambiguate dual listings. An override may target any in-scope feed, including one already renamed, so a code can be pinned after the bulk run.

The file must be passed explicitly with `--name-overrides`; there is no implicit default path.

## Duplicate Names

Two same-issuer dual listings derive identical names (GigaDevice and Montage, each listed in both Shanghai and Hong Kong). The script prints a warning naming every feed involved and still writes — `metadata.name` is already non-unique across the config. Adding override rows clears the warning.

## Safety

- Dry run is the default; `--apply` writes.
- The config is backed up to `<config>.bak` first, unless `--no-backup`.
- Serialization is byte-identical to the stored format, so only the changed `"name":` lines differ.

Verification runs in two stages.

**Before writing** — so a dry run catches problems too — `verify_text` asserts that the line count is unchanged, that the number of differing lines equals the number of planned changes, that every differing line is a `"name":` line, and that the changed values match the plan.

**After writing** (`--apply` only), `verify_on_disk` re-reads the file from disk and asserts it parses, that the feed count is unchanged, re-runs `verify_text`, and then runs `verify_feed_names`. That last check is JSON-path-aware: it confirms the set of feeds whose `metadata.name` changed is exactly the planned set, with each new name on its intended feed. It is what catches a name applied to the wrong feed — a swap between two renamed feeds is invisible to the line-level check, which only compares values as an unordered multiset — and it ignores unrelated `name` keys elsewhere in the config, such as `exchanges[].name`.

Any failure aborts with exit code 1. A post-write failure leaves the `.bak` for recovery.

## Tests

```bash
pytest tests/test_rename_numeric_feed_names.py -v
```

The real-data smoke tests skip automatically when `lazer-state.json` is absent, since config files are gitignored.

See `docs/superpowers/specs/2026-07-28-numeric-feed-name-rename-design.md` for the full design and the measurements behind it.
