# KR/JP Support for `--set-ric-mapping` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `tools/edit-config/edit_config.py --set-ric-mapping` so it matches Korean (`.KS`) and Japanese (`.T`) RICs to feed symbols, not just Hong Kong (`.HK`), and accepts CSVs with only a `RIC` column — so `prune.txt` (27 `RIC,Feed ID` rows) can backfill `lazer_new.json`'s empty `datascope_ric` identifiers unmodified.

**Architecture:** Two small, independent changes inside `tools/edit-config/edit_config_lib/ric_csv.py`: (1) generalize `derive_symbol_prefixes()` from a single hardcoded `.HK` branch to a small table of `(RIC suffix, exchange code)` pairs covering HK/KR/JP; (2) relax `load_ric_csv()`'s required-columns check from `(Ticker, RIC, Exchange Code)` to just `(RIC,)`. Nothing downstream (`SetRicMapping` in `config_ops.py`, the CLI wiring in `edit_config.py`) changes — both already operate on a plain `dict[prefix, ric]` / already-parsed `RicEntry` list and are agnostic to which exchanges are represented.

**Tech Stack:** Python 3, stdlib `csv`, `pytest`. No new dependencies.

## Global Constraints

- `derive_symbol_prefixes()` must keep returning `[]` (not raise) for RICs it doesn't recognize — existing HK behavior and the "silent skip" contract in `SetRicMapping` depend on this.
- The `Ticker` and `Exchange Code` CSV columns must remain accepted when present (existing HK fixture `hk-syms-sample.csv` must keep passing unmodified) — only the _requirement_ is relaxed, not the fields.
- No changes to `config_ops.py`, `config_editor.py`, `config_text_surgery.py`, or the CLI's `--set-ric-mapping`/`--from-csv` operation wiring — this is a data-layer change only, per the design's Non-goals section.
- Ticker portion of a matched RIC must be all-digits before deriving a prefix (same guard as the existing HK case) — e.g. `AAPL.O` must not match anything.

---

## Task 1: Generalize `derive_symbol_prefixes()` to KR/JP

**Files:**

- Modify: `tools/edit-config/edit_config_lib/ric_csv.py:58-69`
- Test: `tools/edit-config/tests/test_ric_csv.py`

**Interfaces:**

- Consumes: nothing new (pure function, same signature `derive_symbol_prefixes(ric: str) -> list[str]`).
- Produces: `derive_symbol_prefixes()` now also returns two prefixes for `.KS` RICs (`Equity.KR.<code>-KR/`, `Equity.KR.<code>/`) and `.T` RICs (`Equity.JP.<code>-JP/`, `Equity.JP.<code>/`), in addition to the existing `.HK` behavior. `build_prefix_index()` (unchanged, `tools/edit-config/edit_config_lib/ric_csv.py:72-82`) automatically picks these up since it just calls `derive_symbol_prefixes()` per entry.

- [ ] **Step 1: Write the failing tests**

Add to `tools/edit-config/tests/test_ric_csv.py` (after `test_derive_symbol_prefixes_hk`, before `test_derive_symbol_prefixes_unknown_suffix_returns_empty`):

```python
def test_derive_symbol_prefixes_kr():
    assert derive_symbol_prefixes("005930.KS") == [
        "Equity.KR.005930-KR/",
        "Equity.KR.005930/",
    ]
    assert derive_symbol_prefixes("000660.KS") == [
        "Equity.KR.000660-KR/",
        "Equity.KR.000660/",
    ]


def test_derive_symbol_prefixes_jp():
    assert derive_symbol_prefixes("7203.T") == [
        "Equity.JP.7203-JP/",
        "Equity.JP.7203/",
    ]
    assert derive_symbol_prefixes("6758.T") == [
        "Equity.JP.6758-JP/",
        "Equity.JP.6758/",
    ]


def test_derive_symbol_prefixes_non_digit_ticker_returns_empty():
    assert derive_symbol_prefixes("ABCD.KS") == []
    assert derive_symbol_prefixes("ABCD.T") == []
```

Also update the existing unknown-suffix test to add a case that could plausibly collide with the new `.T` suffix (a RIC ending in `.T` embedded in a longer non-numeric-ticker exchange suffix, and a totally unrelated suffix), so the guard is exercised alongside the new logic:

Modify `test_derive_symbol_prefixes_unknown_suffix_returns_empty` (`tools/edit-config/tests/test_ric_csv.py:66-68`) to:

```python
def test_derive_symbol_prefixes_unknown_suffix_returns_empty():
    assert derive_symbol_prefixes("AAPL.O") == []
    assert derive_symbol_prefixes("EUR=") == []
```

(No change needed to this test's body — `AAPL.O` already exercises "unknown suffix" since `.O` isn't `.HK`/`.KS`/`.T`. Leaving it as-is confirms the generalized suffix table doesn't accidentally widen matching.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/edit-config && python3 -m pytest tests/test_ric_csv.py -v -k "kr or jp or non_digit"`
Expected: FAIL — `derive_symbol_prefixes("005930.KS")` returns `[]` instead of the two KR prefixes (current code only handles `.HK`).

- [ ] **Step 3: Generalize the implementation**

Replace `derive_symbol_prefixes()` in `tools/edit-config/edit_config_lib/ric_csv.py:58-69`:

```python
_SUFFIX_TO_EXCHANGE = {
    ".HK": "HK",
    ".KS": "KR",
    ".T": "JP",
}


def derive_symbol_prefixes(ric: str) -> list[str]:
    """Map a RIC to the candidate Lazer feed symbol prefixes.

    Supports HK (`NNNN.HK`), KR (`NNNN.KS`), and JP (`NNNN.T`) equities: each
    maps to both `Equity.<EXCH>.NNNN-<EXCH>/` (legacy form) and
    `Equity.<EXCH>.NNNN/` (current form). Returns [] for RICs we don't know
    how to map, or whose ticker portion isn't all-digits.
    """
    for suffix, exchange in _SUFFIX_TO_EXCHANGE.items():
        if ric.endswith(suffix):
            head = ric[: -len(suffix)]
            if head.isdigit():
                return [f"Equity.{exchange}.{head}-{exchange}/", f"Equity.{exchange}.{head}/"]
            return []
    return []
```

Note: `dict` iteration order in Python 3.7+ is insertion order, and none of `.HK`/`.KS`/`.T` is a suffix of another, so iteration order doesn't affect correctness here — but the early `return []` on a non-digit head (once a suffix matches) preserves the original HK behavior of not falling through to try other suffixes on the same RIC.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/edit-config && python3 -m pytest tests/test_ric_csv.py -v`
Expected: PASS — all tests in the file, including the pre-existing HK ones (`test_derive_symbol_prefixes_hk`, `test_build_prefix_index_hk`, `test_build_prefix_index_filters_non_hk`).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/ric_csv.py tools/edit-config/tests/test_ric_csv.py
git commit -m "$(cat <<'EOF'
feat(edit-config): derive KR/JP symbol prefixes for --set-ric-mapping

Generalizes derive_symbol_prefixes() from an HK-only branch to a
suffix table covering .HK/.KS/.T, so RICs like 005930.KS and 7203.T
resolve to Equity.KR.*/Equity.JP.* feed-symbol prefixes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Relax `load_ric_csv()` required columns to just `RIC`

**Files:**

- Modify: `tools/edit-config/edit_config_lib/ric_csv.py:26-55`
- Test: `tools/edit-config/tests/test_ric_csv.py`
- Test fixture: `tools/edit-config/tests/fixtures/ric-only-sample.csv` (new)

**Interfaces:**

- Consumes: nothing new.
- Produces: `load_ric_csv(path: str) -> list[RicEntry]` (signature unchanged). `RicEntry.ticker` / `RicEntry.exchange_code` are now `""` when the source CSV lacks those columns, instead of the load failing with `LoadError`.

- [ ] **Step 1: Add a RIC-only fixture and write the failing tests**

Create `tools/edit-config/tests/fixtures/ric-only-sample.csv`:

```csv
RIC,Feed ID
005930.KS,2179
7203.T,2080
```

Add to `tools/edit-config/tests/test_ric_csv.py` (after `test_load_ric_csv_raises_on_missing_columns`):

```python
def test_load_ric_csv_accepts_ric_only_columns():
    entries = load_ric_csv(str(FIXTURES / "ric-only-sample.csv"))
    assert len(entries) == 2
    assert entries[0] == RicEntry(ticker="", ric="005930.KS", exchange_code="")
    assert entries[1] == RicEntry(ticker="", ric="7203.T", exchange_code="")


def test_load_ric_csv_still_raises_when_ric_column_missing(tmp_path):
    p = tmp_path / "no-ric.csv"
    p.write_text("Ticker,Exchange Code\n700,HKG\n", encoding="utf-8")
    with pytest.raises(LoadError, match="missing required column"):
        load_ric_csv(str(p))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/edit-config && python3 -m pytest tests/test_ric_csv.py -v -k "ric_only or ric_column_missing"`
Expected: FAIL on `test_load_ric_csv_accepts_ric_only_columns` — current code raises `LoadError: ... missing required column(s): Ticker, Exchange Code` because `_REQUIRED_COLUMNS = ("Ticker", "RIC", "Exchange Code")`.

- [ ] **Step 3: Relax the required-columns check**

In `tools/edit-config/edit_config_lib/ric_csv.py`, change line 26:

```python
_REQUIRED_COLUMNS = ("Ticker", "RIC", "Exchange Code")
```

to:

```python
_REQUIRED_COLUMNS = ("RIC",)
```

No other changes needed in `load_ric_csv()` — it already reads `Ticker`/`Exchange Code` via `row.get("Ticker") or ""` / `row.get("Exchange Code") or ""` (`tools/edit-config/edit_config_lib/ric_csv.py:45-46`), which already tolerates the column being absent from `reader.fieldnames` (`DictReader.get` on a missing key just returns `None`, and `None or ""` is `""`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/edit-config && python3 -m pytest tests/test_ric_csv.py -v`
Expected: PASS — full file, including `test_load_ric_csv_raises_on_missing_columns` (which now only fails because it's missing `RIC`, not `Ticker`/`Exchange Code` — the test still passes since `Ticker,Foo` header has no `RIC` column either).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/ric_csv.py tools/edit-config/tests/test_ric_csv.py tools/edit-config/tests/fixtures/ric-only-sample.csv
git commit -m "$(cat <<'EOF'
feat(edit-config): allow RIC-only CSVs for --set-ric-mapping

Ticker and Exchange Code were required columns but never read by the
matching logic (derive_symbol_prefixes only uses RIC). Relaxing the
required-columns check to just RIC lets prune.txt-shaped
(RIC,Feed ID) files load without reformatting.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Update docs and CLI help text

**Files:**

- Modify: `docs/edit_config.md:155-177`
- Modify: `tools/edit-config/edit_config.py:162-166`

**Interfaces:**

- Consumes: nothing (docs/help-text only, no runtime behavior).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Update the CLI `--from-csv` help string**

In `tools/edit-config/edit_config.py`, change lines 162-166:

```python
    p.add_argument(
        "--from-csv",
        type=str,
        help="CSV path for --set-ric-mapping (LSEG-style: requires Ticker, RIC, Exchange Code columns).",
    )
```

to:

```python
    p.add_argument(
        "--from-csv",
        type=str,
        help="CSV path for --set-ric-mapping (requires a RIC column; Ticker and Exchange Code are optional).",
    )
```

- [ ] **Step 2: Update `docs/edit_config.md`'s `--set-ric-mapping` section**

Change `docs/edit_config.md:155-158` from:

```markdown
**Contrast with `--set-ric-mapping`** — `--set-ric-mapping` is HK-only, matches
feeds by symbol prefix from a CSV, writes one RIC to every slot, and only fills
_empty_ slots. `--set-ric` resolves RICs automatically by feed ID, differentiates
day vs overnight slots, and overwrites non-empty values that differ.
```

to:

```markdown
**Contrast with `--set-ric-mapping`** — `--set-ric-mapping` matches feeds by
symbol prefix from a CSV (HK, KR, and JP equities), writes one RIC to every
slot, and only fills _empty_ slots. `--set-ric` resolves RICs automatically by
feed ID, differentiates day vs overnight slots, and overwrites non-empty
values that differ.
```

Change `docs/edit_config.md:175-177` from:

```markdown
The CSV must have `Ticker`, `RIC`, and `Exchange Code` columns. v1 supports HK
equities only — rows whose RIC does not map to a known feed-symbol prefix are
reported as unmatched in the summary.
```

to:

```markdown
The CSV must have a `RIC` column; `Ticker` and `Exchange Code` are optional
(accepted if present, ignored by matching). Supports HK (`NNNN.HK`), KR
(`NNNN.KS`), and JP (`NNNN.T`) equities — rows whose RIC does not map to a
known feed-symbol prefix are reported as unmatched in the summary.
```

- [ ] **Step 3: Run the full edit-config test suite as a sanity check**

Run: `cd tools/edit-config && python3 -m pytest tests/ -v`
Expected: PASS — all tests, confirming the docs/help-text-only change didn't touch behavior (this suite includes `test_edit_config_cli.py`, `test_config_ops.py`, `test_config_editor.py`, etc., none of which assert on help-string content).

- [ ] **Step 4: Commit**

```bash
git add docs/edit_config.md tools/edit-config/edit_config.py
git commit -m "$(cat <<'EOF'
docs(edit-config): document KR/JP support in --set-ric-mapping

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Apply `prune.txt` to `lazer_new.json`

**Files:**

- Read only: `prune.txt`, `lazer_new.json`
- No test file — this task is a real-data verification/rollout step, not new library code.

**Interfaces:**

- Consumes: `derive_symbol_prefixes()` (Task 1), `load_ric_csv()` (Task 2) — both exercised indirectly through the `edit_config.py` CLI.
- Produces: the edited `lazer_new.json` (25 `datascope_ric.identifier` slots filled) and a `.bak` backup file.

- [ ] **Step 1: Run a dry-run and inspect the plan**

Run: `python3 tools/edit-config/edit_config.py --config lazer_new.json --set-ric-mapping --from-csv prune.txt --dry-run`

Expected: the dry-run summary reports 25 changes (empty → filled `datascope_ric.identifier`), 0 warnings, and the diff shows exactly the 25 feed IDs identified during design as having an empty slot (`2179, 2213, 2214, 2222, 2259, 2246, 2186, 2250, 2211, 2193, 2180, 2175, 2058, 2162, 2043, 2114, 2064, 2092, 2105, 2063, 2161, 2078, 2056, 2149, 1990`). Feeds `2166` and `2080` (already correct) must NOT appear in the diff (silent NOOP per `SetRicMapping` semantics). If the actual output differs from this — e.g. a different change count, or warnings — stop and re-diagnose before applying; do not proceed to Step 2 with an unexplained mismatch.

- [ ] **Step 2: Apply the change**

Run: `python3 tools/edit-config/edit_config.py --config lazer_new.json --set-ric-mapping --from-csv prune.txt --apply`

Expected: exit code 0, a `lazer_new.json.bak` backup created, and the same 25-change summary as the dry-run.

- [ ] **Step 3: Spot-check the written values**

Run:

```bash
python3 -c "
import json
with open('lazer_new.json') as f:
    data = json.load(f)
by_id = {f['feedId']: f for f in data['feeds']}
checks = [(2179, '005930.KS'), (1990, '4506.T'), (2166, '000660.KS'), (2080, '7203.T')]
for fid, expected in checks:
    ident = by_id[fid]['marketSchedules'][0]['benchmarkMapping']['datascope_ric']['identifiers'][0]['identifier']
    status = 'OK' if ident == expected else 'MISMATCH'
    print(fid, ident, expected, status)
"
```

Expected: all four rows print `OK` — two from the newly-filled set (`2179`, `1990`), two that were already correct and should be untouched (`2166`, `2080`).

- [ ] **Step 4: Run the config linter as a final sanity gate**

Run: `python3 tools/config-linter/config_linter.py --config lazer_new.json`
Expected: no new errors attributable to this change (pre-existing unrelated lint findings, if any, are out of scope).

- [ ] **Step 5: Commit the updated config**

`lazer_new.json` is a large generated/state file — confirm it is not gitignored before committing (the repo's git status at session start showed `lazer.json` as `D` (deleted/gitignored-tracked) and `lazer_new.json`/`lazer_prune.json` as untracked `??`, so check current tracking status first):

```bash
git status lazer_new.json lazer_new.json.bak
```

If `lazer_new.json` is meant to be tracked, commit it (excluding the `.bak` backup file):

```bash
git add lazer_new.json
git commit -m "$(cat <<'EOF'
chore(config): backfill KR/JP datascope_ric identifiers from prune.txt

Fills 25 empty datascope_ric.identifier slots on Equity.KR.*/Equity.JP.*
COMING_SOON feeds using tools/edit-config/edit_config.py --set-ric-mapping.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

If `lazer_new.json` is untracked/gitignored by convention in this repo (as `lazer.json` appears to be, per the `fix(plans): drop invalid git-commit step for gitignored lazer.json` commit in recent history), skip this step — leave the file updated on disk without committing, matching that established convention.

---

## Self-Review Notes

- **Spec coverage:** All five spec decisions are covered — matching strategy (Task 1), prefix shape incl. legacy `-KR`/`-JP` suffix (Task 1), CSV required columns (Task 2), no changes to `SetRicMapping`/CLI wiring (verified by Task 3 only touching docs/help text, Task 1/2 leaving `config_ops.py` untouched), docs update (Task 3). The Verification section's cross-check (feed-id lookup vs. prefix derivation agreement) is exercised for real in Task 4 against the actual `lazer_new.json`/`prune.txt`.
- **Placeholder scan:** no TBD/TODO; every step has literal code, commands, and expected output.
- **Type consistency:** `derive_symbol_prefixes(ric: str) -> list[str]` and `RicEntry(ticker, ric, exchange_code)` signatures are unchanged from the existing code and used identically across Tasks 1, 2, and 4.
