# Work Log — Q2 2026 (Apr 17 – May 27)

Notes on the commits, PRs, and scripts produced in this ~1.5-month window. Two
parts: a PR timeline grouped by theme, and a per-script reference (what each
tool does, when to use it, key flags).

Scope: PRs **#13–#36**. Earlier work (#1–#12, Feb–Mar 2026) — the `lib/`
refactor, feed-readiness/uptime tools, `volume_profile.py`, `update_min_publishers.py`,
and the first config-linter cut — predates this window and is not detailed here.

---

## Part A — PR Timeline by Theme

### Config Linter (`tools/config-linter/config_linter.py`)

Static validation for `after.json` (the Lazer feed config). Grew from a basic
rule set into an exchange-aware governance gate.

| PR  | Date   | What landed                                                                                                                                       |
| --- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| #13 | Apr 17 | Rule set E001–E016 / W001–W009 (the working linter baseline)                                                                                      |
| #14 | Apr 28 | International equities support + per-session schedule comparison for E011/W003; Index sub-namespace grouping extended to non-equity asset classes |
| #15 | Apr 28 | Baseline-diff mode — lint only what changed vs a `before.json` / git ref                                                                          |
| #16 | Apr 28 | E017/E018 publisher-uniqueness rules                                                                                                              |
| #17 | Apr 29 | Fix: skip publishers missing `publisherId` in `check_publishers`                                                                                  |
| #18 | Apr 29 | Fix: correct diff-mode suppression counts + key collisions                                                                                        |
| #20 | May 3  | Exchange-aware rules E019–E025 / W010–W011                                                                                                        |
| #21 | May 3  | Docs: E019–E025 / W010–W011 examples                                                                                                              |
| #22 | May 5  | Precision pass — tightened E004/E011/E013/E014/W003 + JSON envelope output                                                                        |

### VS Code Extension (wraps the linter)

| PR  | Date           | What landed                                                                      |
| --- | -------------- | -------------------------------------------------------------------------------- |
| #19 | Apr 29 → May 3 | Wrap the config linter as a VS Code extension (inline diagnostics in the editor) |
| #23 | May 5          | Bump extension to v0.2.0 for the JSON-envelope parser                            |

### edit-config — surgical `after.json` editor (`tools/edit-config/`)

Text-surgery editor that changes `after.json` in place without reformatting the
whole file (keeps diffs minimal, preserves the inline-array style).

| PR  | Date      | What landed                                                                                                                         |
| --- | --------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| #24 | May 5     | Initial surgical editor — add/remove publishers, set minPublishers, set state                                                       |
| #29 | May 18–19 | `--set-ric-mapping --from-csv` — fill `datascope_ric` identifiers from an LSEG-style CSV; reports unmatched rows; YAML-spec support |
| #30 | May 19    | Fix: match both HK feed-prefix forms in `--set-ric-mapping`                                                                         |

### session-editor — market-session editor (`tools/session-editor/`)

| PR  | Date   | What landed                                                                                                        |
| --- | ------ | ------------------------------------------------------------------------------------------------------------------ |
| #28 | May 18 | New tool: add/remove US-equity market sessions (REGULAR / PRE_MARKET / POST_MARKET / OVER_NIGHT) on selected feeds |

### RIC mapping / Datascope onboarding (`generate_ric_mapping.py`)

| PR  | Date      | What landed                                                                                                                      |
| --- | --------- | -------------------------------------------------------------------------------------------------------------------------------- |
| #26 | May 17    | `tools/backfill-apids/` — one-off migrations to backfill missing `allowedPublisherIds` + `benchmarkMapping` on COMING_SOON feeds |
| #27 | May 17    | Apply the LSEG "consolidated `.K`" RIC rule for US equities                                                                      |
| #29 | May 18–19 | `generate_ric_mapping.py` now resolves by `--feed-id` and reads `after.json` by default (not just tickers)                       |

### lazer_dq — DQ evaluation pipeline (`lazer_dq/`)

The largest theme: a subprocess-based bulk data-quality runner that evaluates
publisher feeds against Datascope benchmarks, summarizes results into a
spreadsheet, and applies the vetted publisher lists back into `after.json`.

| PR  | Date      | What landed                                                                                       |
| --- | --------- | ------------------------------------------------------------------------------------------------- |
| #25 | May 11    | Import the lazer DQ bulk runner + feeds-summary tooling (replaces the papermill-notebook flow)    |
| #31 | May 21    | `hk-equities` support + port PR #272 benchmark filters (irregular-trade qualifier filtering)      |
| #32 | May 22    | `--asset-class` flag with hk-equities support (asset-class registry in `summarize_feeds`)         |
| #33 | May 25    | Fix: handle no-alignment crash in the engine; split "skip" vs "fail" in the bulk runner           |
| #34 | May 25–26 | `summarize_feeds` redundancy floor (ceiling-bounded top-ups) + new `apply_allowed_to_config` tool |
| #35 | May 26    | Fix: insert session `minPublishers` in canonical order (before `"session"`)                       |
| #36 | May 27    | Docs: `--asset-class`/hk-equities, top-up disable, stats-path fix                                 |

---

## Part B — Script Reference

Grouped by the workflow each tool serves. For full usage, see the linked doc.

### Config governance — validating and editing `after.json`

**`tools/config-linter/config_linter.py`** — [docs/config_linter.md](config_linter.md)
Static linter for `after.json`. Catches duplicate feeds, bad publisher lists,
schedule mismatches, and exchange-specific errors (rules E001–E025 / W001–W011).
Use it before committing a config change or as a CI gate.

- Key flags: `--baseline before.json` / `--baseline-ref develop` / `--no-baseline`
  (diff mode — lint only what changed), `--format json`, `--warnings-as-errors`.
- Also shipped as a VS Code extension for inline editor diagnostics.

**`tools/edit-config/edit_config.py`** — [docs/edit_config.md](edit_config.md)
Surgical text editor for `after.json` — makes targeted edits without
reformatting the whole file (minimal diffs). Use it to add/remove publishers,
set `minPublishers`, set feed state, or fill RIC mappings across a feed range.

- Key ops: `--add-publisher` / `--remove-publisher`, `--set-min-publishers`,
  `--set-state`, `--set-ric-mapping --from-csv <lseg.csv>`, `--feed-id 1000-1050`.

**`tools/session-editor/session_editor.py`** — [docs/session_editor.md](session_editor.md)
Adds or removes market sessions (REGULAR / PRE_MARKET / POST_MARKET /
OVER_NIGHT) on US-equity feeds. Dry-run by default; pass `--apply` to write.
Use it when extended-hours sessions need to be rolled out or pulled back across
a set of feeds.

- Key flags: `--add-session` / `--remove-session`, `--feed-id`, `--state STABLE`,
  `--min-publishers`, `--apply`.

**`tools/backfill-apids/backfill.py`** and **`backfill_benchmark.py`**
One-off migrations (run once, May 2026). `backfill.py` adds top-level
`allowedPublisherIds` + `benchmarkMapping` to COMING_SOON feeds that lack them,
expanding standard US equities from 1 to 4 sessions. `backfill_benchmark.py` is
the phase-2 follow-up that adds `benchmarkMapping` skeletons to feeds that
already had `allowedPublisherIds`. Not part of the routine workflow.

### RIC mapping / Datascope onboarding

**`generate_ric_mapping.py`** — [docs/generate_ric_mapping.md](generate_ric_mapping.md)
Given tickers or feed IDs, derives the Reuters Instrument Code (RIC) using
asset-class-specific rules and outputs a Datascope-onboarding CSV. Supports US
equities/ETFs, FX, metals, commodity & equity-index futures, and US Treasury
rates. Reads `after.json` by default.

- Key flags: `--ticker AAPL EURUSD`, `--feed-id 922 327 346`, `--ticker-file`,
  `--symbols lazer_symbols.json`, `--output`.

### Lazer DQ evaluation pipeline (`lazer_dq/`)

This is a four-stage pipeline: **evaluate → bulk-run → summarize → apply**.

**`lazer_dq/evaluate_feed_standalone.py`** — the engine
Evaluates a single (feed, date, mode) against its Datascope benchmark. Standalone
port of the `publisher_benchmark_eval.ipynb` notebook, with ClickHouse queries
filtered to a `[start_time, end_time]` UTC window. Usually invoked by the bulk
runner, not directly.

- Exit codes: `0` = analysis ran, `2` = no benchmark data (holiday / non-trading
  day / not yet ingested), other = unexpected error.
- Key flags: `--feed-id`, `--date`, `--mode`, `--cluster`, `--start-time`/`--end-time`.

**`lazer_dq/evaluate_feeds_bulk.py`** — [docs/evaluate_feeds_bulk.md](evaluate_feeds_bulk.md)
Bulk DQ runner — calls the standalone engine once per CSV row (`feed_id,date,mode`),
resolving the per-mode market window (NY time, or HKEX morning session for
`hk-equities`) to UTC. Treats every non-zero engine exit as a soft skip and
continues. Writes per-feed reports into `dq_reports/`.

- Key flags: `--csv feeds.csv`, `--cluster lazer-prod`.

**`lazer_dq/summarize_feeds.py`** — [docs/summarize_feeds.md](summarize_feeds.md)
Reads `dq_reports/` and emits one `.xlsx` workbook with two sheets: `rankings`
(top-N publishers per feed/mode by `rmse_over_spread`) and `allowed`
(paste-ready `allowedPublisherIds` arrays). Applies a redundancy floor with
ceiling-bounded top-ups. Asset-class-aware via an `ASSET_CLASS_CONFIG` registry.

- Key flags: `--csv`, `--cluster`, `--date`, `--asset-class us-equities|hk-equities`,
  `--min-publishers`.

**`lazer_dq/apply_allowed_to_config.py`** — [docs/apply_allowed_to_config.md](apply_allowed_to_config.md)
Reads the `allowed` sheet from a `summarize_feeds` workbook and edits
`after.json` in place: promotes COMING_SOON feeds to STABLE on their DQ-vetted
publisher lists, and additively adds missing sessions to already-live STABLE
feeds without disturbing their live sessions. Shares `lib/json_surgery.py` with
the other config tools.

- Key flags: `--xlsx dq_summary_*.xlsx`, `--config after_1.json`, `--dry-run`.

> **Pipeline-vs-CSV note:** `apply_allowed_to_config` consumes the
> `summarize_feeds` `.xlsx` (DQ pipeline). The older `update_config_from_summary.py`
> consumes a `feed_readiness.py` CSV. They are not interchangeable.
