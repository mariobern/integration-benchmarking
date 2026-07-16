# active_pub_distribution — active-publisher histogram + concentration

Diagnostic sweep of all STABLE (feed, session) pairs in a new-format Lazer
config. Answers two questions the min_pub audit's CRITICAL/WARN/OK collapses
away:

1. **How often does the feed run close to minPublishers?** Histogram of
   per-minute active publisher counts over session open minutes (a publisher
   is active in a minute iff it has ≥ 1 ACCEPTED update there). Mass near
   `min_pub` = fragile; mass near `allowed_count` = healthy margin.
2. **Is update volume concentrated?** Per-publisher ACCEPTED-update shares:
   `effective_publishers` (inverse HHI — "effectively 3.2 publishers even
   though 10 are allowed"), `top1_share_pct`, `top3_share_pct`.

Methodology matches `lazer_dq.audit_min_pub` (same session masks, same
active-in-minute definition), so results line up with audit classifications.
Design spec: `docs/superpowers/specs/2026-07-16-active-pub-distribution-design.md`.

## Usage

```bash

# Sweep (default window: last 7 full UTC days)

python3 -m lazer_dq.active_pub_distribution --config lazer_new.json \
 --start-date 2026-07-09 --end-date 2026-07-16 --workers 8

# Interrupted? Re-run with --resume (summary row = completion marker;

# orphan detail rows from a mid-feed crash are pruned automatically)

python3 -m lazer_dq.active_pub_distribution --config lazer_new.json \
 --start-date 2026-07-09 --end-date 2026-07-16 --resume

# HTML report (no ClickHouse needed)

python3 -m lazer_dq.render_active_pub_html \
 --summary output_csv/active_pub_distribution_2026-07-09_2026-07-16.csv \
 --publishers output_csv/active_pub_publishers_2026-07-09_2026-07-16.csv \
 --top 50
```

## Outputs

### `active_pub_distribution_<start>_<end>.csv` — one row per (feed, session)

| Column                                                         | Meaning                                                                                                                                                                                                                                                |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `note`                                                         | blank = metrics present; `NO_SCHEDULE` / `ZERO_OPEN_MINUTES` rows carry identity + `effective_min_pub` + `allowed_count` only; `SKIPPED_DEPRECATED` rows carry `feed_id` + `symbol` only                                                               |
| `allowed_count` / `active_pub_count` / `never_published_count` | allowed-list size vs publishers that actually produced ≥ 1 ACCEPTED update vs dead weight                                                                                                                                                              |
| `unlisted_active_count`                                        | Sanity flag: distinct publishers NOT in the config's allowed list with ACCEPTED updates in the window. Non-zero ⇒ the analyzed config file differs from what production enforced (snapshot drift); such publishers are excluded from all other metrics |
| `pct_minutes_le_min` / `pct_minutes_le_min_plus_1`             | % of open minutes at or below min_pub / min_pub+1 (the left-skew signal; `le_min` matches the audit's CRITICAL condition)                                                                                                                              |
| `p10_active, median_active, p90_active, worst_minute_active`   | Distribution of the per-minute active count: p10/median/p90 percentiles plus the worst-minute minimum                                                                                                                                                  |
| `active_hist`                                                  | Full histogram: `"3:0.52;4:12.10;5:87.38"` = % of open minutes at each active count                                                                                                                                                                    |
| `effective_publishers`                                         | Inverse HHI of update shares; compare to `effective_min_pub`                                                                                                                                                                                           |
| `top1_share_pct` / `top3_share_pct`                            | % of all ACCEPTED updates from the 1 / 3 most active publishers                                                                                                                                                                                        |

### `active_pub_publishers_<start>_<end>.csv` — one row per (feed, session, allowed publisher)

Includes zero-update publishers (the "allowed but never publishes" list):
`accepted_updates, update_share_pct, minutes_active, pct_open_minutes_active,
rank` (1 = most updates; ties by publisher_id; zero-update publishers last).

### HTML report

Self-contained file (works offline, publishable as a claude.ai Artifact):
worst-N gallery of histograms (red bars = counts ≤ min_pub) annotated with
effective publishers, top-3 share, and dominant publisher IDs, plus a
sortable table of every summary row. Light + dark mode.

## Interpretation notes

- A feed can be audit-OK yet fragile here: e.g. always 2 above min_pub but
  with 90% of updates from one publisher (`effective_publishers` ≈ 1) — one
  publisher outage away from CRITICAL.
- `pct_minutes_le_min > 0` ⇔ the audit classified that session CRITICAL over
  the same window (same definition, same masks).
- This tool only describes; it sets no thresholds and edits no configs.
