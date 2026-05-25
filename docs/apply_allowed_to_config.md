# Apply Allowed Publishers to Config (apply_allowed_to_config.py)

Applies the **"allowed" sheet** of a `dq_summary_<cluster>_<date>.xlsx`
(produced by `lazer_dq/summarize_feeds.py`) directly into `after.json` /
`after_1.json`. It promotes `COMING_SOON` feeds to `STABLE` on their
DQ-vetted publisher lists and additively adds missing sessions to live feeds.

## Usage

```bash
# Preview (no writes)
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json --dry-run

# Apply (writes after_1.json, backup at after_1.json.bak)
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json
```

Run once per workbook (each file is one asset class / one date).

## Arguments

| Argument    | Description                                   | Required |
| ----------- | --------------------------------------------- | -------- |
| `--xlsx`    | dq_summary workbook (reads the `allowed` tab) | Yes      |
| `--config`  | after.json / after_1.json                     | Yes      |
| `--dry-run` | Preview changes without writing               | No       |

## Per-(feed, session) rules

| Feed state  | Session in feed?       | Summary has list? | Action                                                |
| ----------- | ---------------------- | ----------------- | ----------------------------------------------------- |
| COMING_SOON | yes                    | yes               | overwrite `allowedPublisherIds` + `minPublishers`     |
| COMING_SOON | no                     | yes               | add the session entry                                 |
| COMING_SOON | (any session has data) | —                 | flip → STABLE; top-level = union, `minPublishers` 1   |
| STABLE      | yes                    | yes               | leave untouched (live)                                |
| STABLE      | no                     | yes               | add the session entry; fold publishers into top-level |
| any         | —                      | `(no data)`       | leave untouched                                       |

- Only `COMING_SOON` and `STABLE` feeds are modified.
- Added sessions copy `benchmarkMapping` from the feed's REGULAR session and
  use the standard US-equity `marketSchedule` template for the session.
- `minPublishers`: REGULAR 3 (→2 when ≤5 publishers), PRE/POST 2, OVERNIGHT 1;
  top-level set to 1 only on COMING_SOON promotion.
- Publishers `{0, 1, 9, 13, 15}` (aggregate sentinel + Lazer) are stripped from
  every list defensively, with a warning.
- A COMING_SOON feed is promoted **only if at least one publisher survives
  filtering**. If the summary listed only excluded publishers and nothing
  remains, the feed is left `COMING_SOON` and reported as
  "Skipped (no publishers after filter)" — never promoted to STABLE with an
  empty allow-list.

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
