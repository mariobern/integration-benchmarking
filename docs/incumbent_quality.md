# Incumbent Publisher Quality Sweep

`lazer_dq/incumbent_quality.py` scores the price quality of every
**incumbent** (currently-allowed) publisher on every session of every STABLE
feed in a new-format Lazer config — the population the min_pub pipeline
never benchmarks. With `--include-candidates` it also scores non-allowed
production-key publishers submitting in the window, using identical
thresholds, so both roles are directly comparable.

Measure-only: no activity gate, no selection, no config mutation. Candidate
selection remains `lazer_dq/qualify_candidates.py`'s job.

## Usage

    python3 -m lazer_dq.incumbent_quality \
        --config lazer_new.json \
        --start-date 2026-07-08 --end-date 2026-07-15 \
        --include-candidates \
        --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv \
        --workers 8 --resume

Dates are UTC, end exclusive. `--resume` appends and skips feeds already in
the summary CSV. `--feed-id 12 3050` restricts the sweep. Full sweeps are
multi-hour; run with `--resume` so restarts are cheap.

## Quality paths

| Path     | Feeds                                                       | Method                                                                                                |
| -------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `engine` | fx, metals, commodity, rates, US/HK/JP/KR/IN equities       | DQ engine (`evaluate_feed_standalone`) per-publisher stats, gated by `qualify_candidates.engine_gate` |
| `peer`   | everything else (crypto, RR, NAV, funding rates, custom, …) | `peer_benchmark.evaluate_peer` vs the feed's own `price_feeds` aggregate                              |

## Verdicts

| Verdict        | Meaning                                                                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `PASS`         | Met the quality gate for the feed's path                                                                                                 |
| `FAIL`         | Enough data, failed the gate                                                                                                             |
| `NO_DATA`      | No (or too few) observations for this publisher in the window (`reason`: no_submissions, insufficient_obs, no_engine_row, bad_stats_row) |
| `NO_BENCHMARK` | The reference itself was unavailable (`reason`: no_engine_data, no_aggregate_data, zero_range, no_open_minutes)                          |

## Outputs (in `--output-dir`, default `output_csv/`)

- `incumbent_report.csv` — one row per publisher × feed-session (metrics + verdict).
- `incumbent_quality_summary.csv` — one row per feed-session (role-split verdict counts, `all_pass`, and `audit_classification` when `--audit-csv` is given).
- `flagged_incumbents.csv` — incumbents with verdict != PASS, plus failing candidates when `--include-candidates`.

## Caveats

- **Peer-path circularity**: incumbents are compared against an aggregate
  they themselves produce. Accepted by design (same trade-off as candidate
  qualification); a dominant bad incumbent partially self-validates.
- **Flat-reference feeds** (zero price variance, e.g. NAV) can never pass
  the peer gate — they come back `NO_BENCHMARK`/`zero_range`.
- **Incumbents vs candidates, price query**: incumbents are scored from
  their `ACCEPTED` submissions with no key-type filter (an incumbent may
  publish with a non-production key and still score normally); candidates
  are production-key-only by discovery (`fetch_production_publisher_ids`,
  same as `qualify_candidates`) and are scored from `ACCEPTED` +
  `UNAUTHORIZED`-rejected submissions, mirroring qualification.
- **Engine benchmark date** is the most recent weekday with engine data in
  the window (up to 3 tried), not the whole window.
