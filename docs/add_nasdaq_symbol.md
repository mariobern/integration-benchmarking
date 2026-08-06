# nasdaq_symbol Backfill (add_nasdaq_symbol.py)

Backfills `metadata.nasdaq_symbol = metadata.name` (verbatim) across Hong Kong,
mainland China, Japan, South Korea, and India equity feeds. These markets carry the
exchange-facing identifier downstream users read prices by in `metadata.name` -- a
numeric code for HK/CN/JP/KR, or the raw ticker for the handful of already-alphabetic
names (e.g. `NIFTYBEES`). `rename_numeric_feed_names.py` later overwrites
`metadata.name` with a human-readable company name for display, so this script must
run first, while `metadata.name` still holds the original identifier.

See `docs/superpowers/specs/2026-07-29-add-nasdaq-symbol-design.md` for the full design.

## Usage

```bash
# Dry run (default) -- prints the plan, writes nothing
python3 add_nasdaq_symbol.py --config lazer_jpkr.json

# Apply -- writes lazer_jpkr.json, keeps a .bak backup
python3 add_nasdaq_symbol.py --config lazer_jpkr.json --apply

# Narrow to one market
python3 add_nasdaq_symbol.py --config lazer_jpkr.json --symbol-prefix Equity.HK. --apply
```

## Arguments

| Argument          | Description                             | Required | Default                                                              |
| ----------------- | --------------------------------------- | -------- | -------------------------------------------------------------------- |
| `--config`        | Path to the Lazer config JSON           | Yes      | --                                                                   |
| `--symbol-prefix` | Symbol namespace to process; repeatable | No       | `Equity.HK.`, `Equity.CN.`, `Equity.JP.`, `Equity.KR.`, `Equity.IN.` |
| `--apply`         | Write changes (default is dry run)      | No       | off                                                                  |
| `--no-backup`     | Skip the `.bak` copy `--apply` makes    | No       | off                                                                  |

## Behavior

For every in-scope feed:

- **Already has `nasdaq_symbol`:** skipped, reported -- makes a second run a no-op.
- **`metadata.name` is empty:** skipped, reported -- nothing to copy.
- **`metadata.name` does not match the code embedded in `symbol`:** skipped, reported.
  `rename_numeric_feed_names.py` never touches `symbol`, so the code segment embedded
  in it (e.g. `0002` in `Equity.HK.0002/HKD`) is an exact fingerprint of the
  not-yet-renamed state. A mismatch means the feed has already been through
  `rename_numeric_feed_names.py` and copying `metadata.name` into `nasdaq_symbol` would
  put a display name where the exchange code belongs -- this is an exact check, not a
  whitespace heuristic, since some renamed display names are a single word (e.g.
  `HITACHI`, `CNOOC`) and would slip past a whitespace-only check.
- **Otherwise:** `metadata.nasdaq_symbol` is set to `metadata.name`, verbatim.

`metadata` dict keys are rebuilt in alphabetical order whenever `nasdaq_symbol` is
added, matching the existing convention on every metadata dict in the config
(`nasdaq_symbol` already sorts between `name` and `quote_currency`, as seen on US
equity feeds).

## Verification

Before writing, and again after writing to disk, the script re-parses the config and
confirms: the feed-id set is unchanged, every feed outside the planned change set has
a byte-identical `metadata` dict to before, and every feed in the change set gained
exactly the planned `nasdaq_symbol` value with nothing else altered. A `.bak` copy of
the original file is kept unless `--no-backup` is passed.

## Tests

```bash
pytest tests/test_add_nasdaq_symbol.py -v
```

Per CLAUDE.md, the repo-root `pytest -q` fails on a pre-existing conftest name clash,
so this suite is always run on its own.
