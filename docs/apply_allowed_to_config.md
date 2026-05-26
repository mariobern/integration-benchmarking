# Apply Allowed Publishers to Config (apply_allowed_to_config.py)

Applies the **"allowed" sheet** of a `dq_summary_<cluster>_<date>.xlsx`
(produced by `lazer_dq/summarize_feeds.py`) directly into `after.json` /
`after_1.json`. It promotes `COMING_SOON` feeds to `STABLE` on their
DQ-vetted publisher lists and additively adds missing sessions to live feeds.

## Usage

```bash
# Preview (no writes) — always dry-run first
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json --min-publishers 2 --dry-run

# us-equities (default asset class): writes per-session fields, drops
# publisher-less sessions. Backs up to after_1.json.bak first.
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json --min-publishers 2

# hk-equities: top-level allowedPublisherIds + minPublishers only.
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-22.xlsx \
    --config after_1.json --asset-class hk-equities --min-publishers 2
```

Run once per workbook (each file is one asset class / one date).

### Config file vs backups

`--config` is read **and** written in place; before each real run the tool
snapshots the previous contents to `<config>.bak`. The three files play distinct
roles:

| File                   | Role                                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------------------- |
| `after_1.json`         | The **live config** — always what you pass to `--config`. Read, edited, and written in place.  |
| `after_1.json.bak`     | **Auto-snapshot** of `after_1.json` taken just before the most recent run. Single-level undo.  |
| a manual pristine copy | Your **full-reset point** (e.g. `cp after_1.json after_1.json.pristine` before the first run). |

- **Always apply against `after_1.json`.** Running several workbooks in sequence,
  each with `--config after_1.json`, accumulates correctly — `after_1.json`
  always carries all applied changes. Never feed `.bak` back in as `--config`
  (that edits the stale snapshot and writes `<config>.bak.bak`).
- **Each run overwrites `.bak`**, so after two sequential runs `.bak` only undoes
  the _last_ run. Roll back the last run with `cp after_1.json.bak after_1.json`;
  to reset all the way to the original you need the separate pristine copy (or to
  re-fetch the source config).

## Arguments

| Argument           | Description                                                             | Required |
| ------------------ | ----------------------------------------------------------------------- | -------- |
| `--xlsx`           | dq_summary workbook (reads the `allowed` tab)                           | Yes      |
| `--config`         | after.json / after_1.json                                               | Yes      |
| `--dry-run`        | Preview changes without writing                                         | No       |
| `--min-publishers` | Min surviving publishers to promote a COMING_SOON feed (default: `3`)   | No       |
| `--asset-class`    | `us-equities` (default) or `hk-equities` — see session-level note below | No       |

## Per-(feed, session) rules

| Feed state  | Session in feed?       | Summary has list? | Action                                                  |
| ----------- | ---------------------- | ----------------- | ------------------------------------------------------- |
| COMING_SOON | yes                    | yes               | overwrite `allowedPublisherIds` + `minPublishers`       |
| COMING_SOON | no                     | yes               | add the session entry                                   |
| COMING_SOON | yes                    | no                | **drop the session** — see "no publisher-less sessions" |
| COMING_SOON | (any session has data) | —                 | flip → STABLE; top-level = union, `minPublishers` 2     |
| STABLE      | yes                    | yes               | leave untouched (live)                                  |
| STABLE      | no                     | yes               | add the session entry; fold publishers into top-level   |
| STABLE      | —                      | `(no data)`       | leave untouched                                         |

- Only `COMING_SOON` and `STABLE` feeds are modified.
- **No publisher-less sessions on promotion (us-equities).** When a COMING_SOON
  feed is promoted, any `marketSchedules` session that has no publishers in the
  summary (e.g. PRE/POST/OVERNIGHT showing `(no data)`) is **removed** from the
  feed — a STABLE feed never carries a session that nobody prices. Only sessions
  with publishers remain. (If those sessions later get publishers, a subsequent
  run re-adds them.) STABLE feeds are not touched, so any pre-existing empty
  session on a live feed is left as-is.
- **Session-level fields are written only for `--asset-class us-equities`.** For
  us-equities, each `marketSchedules` entry gets its own `allowedPublisherIds` +
  `minPublishers` (and missing sessions are added). For every other asset class
  (`hk-equities`, …) only the **top-level** `allowedPublisherIds` + `minPublishers`
  are set; the single REGULAR `marketSchedules` entry is left exactly as-is (no
  session-level `allowedPublisherIds`/`minPublishers` added).
- Added sessions (us-equities only) copy `benchmarkMapping` from the feed's
  REGULAR session and use the standard US-equity `marketSchedule` template.
- `minPublishers`: per-session REGULAR 3 (→2 when ≤5 publishers), PRE/POST 2,
  OVERNIGHT 1 (us-equities only); top-level set to 2 on COMING_SOON promotion
  (all asset classes).
- Publishers `{0, 1, 9, 13, 15}` (aggregate sentinel + Lazer) are stripped from
  every list defensively, with a warning.
- A COMING_SOON feed is promoted **only if at least `--min-publishers` survive
  filtering** (across all sessions; default 3). Feeds below the threshold have
  insufficient redundancy and are left `COMING_SOON`, reported as
  "Skipped (<N publishers after filter)" — never promoted to STABLE. (At the
  default of 3 this also guarantees the top-level `minPublishers: 2` is
  satisfiable. Lower it, e.g. `--min-publishers 2`, for asset classes with
  fewer publishers such as hk-equities.)

## Safety

- `--dry-run` previews everything and writes nothing.
- A real run copies the config to `<config>.bak` before writing.
- Existing live (STABLE) sessions are never overwritten.

## Compared to update_config_from_summary.py

| Feature        | `update_config_from_summary.py` | `apply_allowed_to_config.py`               |
| -------------- | ------------------------------- | ------------------------------------------ |
| Input          | `feed_readiness.py` CSV         | dq_summary `.xlsx` "allowed" sheet         |
| Multi-date     | Intersects across dates         | One vetted date per workbook               |
| STABLE feeds   | Refreshes existing sessions     | Never touches live sessions; adds new only |
| Added sessions | Omits `benchmarkMapping`        | Copies `benchmarkMapping` from REGULAR     |

## Tests

```bash
python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v
```
