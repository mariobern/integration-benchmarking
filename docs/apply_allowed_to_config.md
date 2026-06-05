# Apply Allowed Publishers to Config (apply_allowed_to_config.py)

Applies the **"allowed" sheet** of a `dq_summary_<cluster>_<date>.xlsx`
(produced by `lazer_dq/summarize_feeds.py`) directly into a session-only
config (`lazer_update.json` era). It promotes `COMING_SOON` feeds to `STABLE`
on their DQ-vetted publisher lists and additively adds missing sessions to live
feeds.

## Config format (new format only)

This tool targets the session-level config format (`lazer_update.json` era):
publisher lists live ONLY inside `marketSchedules` session entries — there is
no feed-level `allowedPublisherIds`. The tool refuses to run against
old-format files (clear error at startup).

- Promotion writes per-session `allowedPublisherIds` and sets the feed-level
  `minPublishers` to 2.
- Session-level `minPublishers` is written only for `Equity.US.*` feeds
  (us-equities is the only asset class that carries it). hk-equities and all
  other classes get the session publisher list plus the feed-level
  `minPublishers` — their session entries never gain a `minPublishers` key.
- There is no `--asset-class` flag anymore: the workbook's session rows drive
  which sessions are written (hk workbooks emit only REGULAR rows), and
  US-equity detection is automatic by symbol prefix.

## Usage

```bash
# Preview (no writes) — always dry-run first
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json --min-publishers 2 --dry-run

# Write per-session fields, drop publisher-less sessions.
# Backs up to after_1.json.bak first.
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json --min-publishers 2
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

| Argument           | Description                                                           | Required |
| ------------------ | --------------------------------------------------------------------- | -------- |
| `--xlsx`           | dq_summary workbook (reads the `allowed` tab)                         | Yes      |
| `--config`         | session-only config (e.g. `after_1.json` / `lazer_update.json`)       | Yes      |
| `--dry-run`        | Preview changes without writing                                       | No       |
| `--min-publishers` | Min surviving publishers to promote a COMING_SOON feed (default: `3`) | No       |

## Per-(feed, session) rules

| Feed state  | Session in feed?       | Summary has list? | Action                                                            |
| ----------- | ---------------------- | ----------------- | ----------------------------------------------------------------- |
| COMING_SOON | yes                    | yes               | overwrite session `allowedPublisherIds` (+ `minPublishers` on US) |
| COMING_SOON | no                     | yes               | add the session entry                                             |
| COMING_SOON | yes                    | no                | **drop the session** — see "no publisher-less sessions"           |
| COMING_SOON | (any session has data) | —                 | flip → STABLE; feed-level `minPublishers: 2`                      |
| STABLE      | yes                    | yes               | leave untouched (live)                                            |
| STABLE      | no                     | yes               | add the session entry                                             |
| STABLE      | —                      | `(no data)`       | leave untouched                                                   |

- Only `COMING_SOON` and `STABLE` feeds are modified.
- **No publisher-less sessions on promotion.** When a COMING_SOON feed is
  promoted, any `marketSchedules` session that has no publishers in the summary
  (e.g. PRE/POST/OVERNIGHT showing `(no data)`) is **removed** from the feed —
  a STABLE feed never carries a session that nobody prices. Only sessions with
  publishers remain. (If those sessions later get publishers, a subsequent run
  re-adds them.) STABLE feeds are not touched, so any pre-existing empty session
  on a live feed is left as-is.
- **Session-level `minPublishers` only for `Equity.US.*` feeds.** For US-equity
  feeds, each `marketSchedules` entry gets its own `allowedPublisherIds` +
  `minPublishers` (missing sessions are added). For all other asset classes
  (hk-equities, fx, metals, …) only the session's `allowedPublisherIds` is
  written — session entries never gain a `minPublishers` key. US-equity detection
  is automatic by symbol prefix (`Equity.US.`).
- Added sessions (US-equity feeds only) copy `benchmarkMapping` from the feed's
  REGULAR session and use the standard US-equity `marketSchedule` template.
- `minPublishers`: per-session REGULAR 3 (→2 when ≤5 publishers), PRE/POST 2,
  OVERNIGHT 1 (US-equity feeds only); feed-level set to 2 on COMING_SOON
  promotion (all asset classes).
- Publishers `{0, 1, 9, 13, 15}` (aggregate sentinel + Lazer) are stripped from
  every list defensively, with a warning.
- A COMING_SOON feed is promoted **only if at least `--min-publishers` survive
  filtering** (across all sessions; default 3). Feeds below the threshold have
  insufficient redundancy and are left `COMING_SOON`, reported as
  "Skipped (<N publishers after filter)" — never promoted to STABLE. (At the
  default of 3 this also guarantees the feed-level `minPublishers: 2` is
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
