# min_pub Situation Report — 2026-07-15

Status report on minimum-publisher health for the STABLE feeds in
`lazer_new.json`, based on the min_pub audit & remediation pipeline run of
2026-07-13/14 (`lazer_dq/audit_min_pub.py` → `lazer_dq/qualify_candidates.py`).

## 1. Executive summary

- **1,645 STABLE feeds (2,505 feed-sessions) audited** over 2026-07-06 → 2026-07-13:
  **1,888 OK, 369 WARN, 248 CRITICAL** feed-sessions.
- **95 CRITICAL feed-sessions hit a minute with zero active publishers**; 121
  feed-sessions spent time below their effective minPublishers.
- Qualification examined all 617 non-OK feed-sessions: **245 can meet their
  publisher target** — 203 via new publisher additions, 42 already at target
  on their worst minute (flagged for margin/persistence, not shortfall).
- A remediation spec with **256 publisher additions (31 publishers, 191
  feeds)** was generated on Jul 14 but has **NOT been applied** — the
  additions are absent from `lazer_new.json`.
- **393 feed-sessions (370 feeds) remain flagged with no automatic fix**,
  mostly because every discovered candidate fails the activity or quality
  gates. These need publisher outreach, minPublishers review, or
  deactivation decisions.
- Caveat: the pipeline ran against `lazer_to_modify.json`; `lazer_new.json`
  (pulled 2026-07-15) has since drifted on 75 feeds, 16 of them flagged —
  see §7.

## 2. Methodology & data provenance

| Stage              | Tool                                              | Ran    | Config                 | Output                                                                                        |
| ------------------ | ------------------------------------------------- | ------ | ---------------------- | --------------------------------------------------------------------------------------------- |
| 1. Audit           | `lazer_dq/audit_min_pub.py`                       | Jul 13 | `lazer_to_modify.json` | `min_pub_audit_2026-07-06_2026-07-13.csv` (2,505 rows)                                        |
| 2. Qualification   | `lazer_dq/qualify_candidates.py`                  | Jul 14 | `lazer_to_modify.json` | `qualification_summary.csv` (617), `candidates_report.csv` (6,607), `flagged_feeds.csv` (393) |
| 3. Spec generation | `lazer_dq/apply_min_pub_remediation.py` (dry-run) | Jul 14 | `lazer_to_modify.json` | `min_pub_remediation_spec.yaml` (55 ops) — pending                                            |

The audit counts only `status='ACCEPTED'` updates from currently-allowed
publishers, per minute, session-aware. Qualification discovers candidates
from `REJECTED`/`UNAUTHORIZED` submissions (production keys only); gate 1 is
activity (≥ 90% of open minutes), gate 2 is quality — Datascope benchmark
where available, otherwise peer comparison against the feed's own
`price_feeds` aggregate.

Known caveats:

- **Peer-gate circularity**: non-Datascope feeds are qualified against their
  own aggregate — accepted by design, but it cannot detect a candidate that
  is wrong in the same way the aggregate is.
- **Flat-reference feeds** (zero price variance, e.g. NAV) can never pass
  the peer quality gate (`zero_range`) and are always flag-listed.
- **Window matching**: Stage 2 and Stage 3 must use identical
  `--start`/`--end` dates; a partial-overlap window produces spurious
  projected-margin failures.
- The audit classifies on time spent at/near minPublishers, not only on
  outright shortfall — a feed can be WARN/CRITICAL while its worst minute
  still meets the target (42 such feed-sessions; 21 of them remain flagged
  because their candidates also fail the gates).

## 3. Audit results (Stage 1)

Classification by asset type (feed-sessions, sorted by non-OK count):

| Asset type             | OK   | WARN | CRITICAL | Total |
| ---------------------- | ---- | ---- | -------- | ----- |
| equity                 | 1496 | 284  | 96       | 1876  |
| crypto                 | 327  | 22   | 62       | 411   |
| crypto-redemption-rate | 17   | 19   | 26       | 62    |
| commodity              | 11   | 17   | 18       | 46    |
| custom                 | 0    | 0    | 18       | 18    |
| fx                     | 29   | 6    | 8        | 43    |
| crypto-index           | 0    | 9    | 1        | 10    |
| interest-rate          | 0    | 5    | 4        | 9     |
| funding-rate           | 3    | 4    | 4        | 11    |
| metal                  | 4    | 0    | 7        | 11    |
| nav                    | 1    | 3    | 4        | 8     |
| **total**              | 1888 | 369  | 248      | 2505  |

Equities dominate the non-OK population (380 of 617 feed-sessions), driven
by extended sessions with thin publisher coverage. By session:

| Session     | OK   | WARN | CRITICAL | Total |
| ----------- | ---- | ---- | -------- | ----- |
| REGULAR     | 1307 | 141  | 197      | 1645  |
| OVER_NIGHT  | 64   | 117  | 29       | 210   |
| POST_MARKET | 249  | 63   | 12       | 324   |
| PRE_MARKET  | 268  | 48   | 10       | 326   |
| **total**   | 1888 | 369  | 248      | 2505  |

Severity highlights:

- 95 CRITICAL feed-sessions recorded at least one minute with **zero active
  publishers**.
- 121 feed-sessions spent minutes **below** effective minPublishers.
- 390 of the 617 non-OK feed-sessions are **prolonged** (long consecutive
  runs at or below minPublishers + 1), i.e. structural coverage gaps rather
  than transient dips.

Worst offenders by minutes below minimum:

| Feed  | Symbol                   | Session | Class    | minPub | Allowed | Min below min | Longest run ≤ min | Worst minute |
| ----- | ------------------------ | ------- | -------- | ------ | ------- | ------------- | ----------------- | ------------ |
| 377   | Crypto.BIO/USD           | REGULAR | CRITICAL | 3      | 12      | 10080         | 10080             | 2            |
| 470   | Crypto.LION/USD          | REGULAR | CRITICAL | 3      | 7       | 10080         | 10080             | 2            |
| 697   | Crypto.KHYPE/HYPE.RR     | REGULAR | CRITICAL | 3      | 8       | 10080         | 10080             | 2            |
| 762   | Crypto.WSTHYPE/STHYPE.RR | REGULAR | CRITICAL | 3      | 8       | 10080         | 10080             | 2            |
| 1572  | Crypto.LHYPE/HYPE.RR     | REGULAR | CRITICAL | 3      | 6       | 10080         | 10080             | 0            |
| 2326  | Crypto.FF/USD            | REGULAR | CRITICAL | 3      | 8       | 10080         | 10080             | 0            |
| 2395  | Crypto.META/USD          | REGULAR | CRITICAL | 2      | 5       | 10080         | 10080             | 0            |
| 2922  | Custom.PRF1/USD          | REGULAR | CRITICAL | 1      | 2       | 10080         | 10080             | 0            |
| 2927  | Custom.PRF5/USD          | REGULAR | CRITICAL | 1      | 2       | 10080         | 10080             | 0            |
| 99000 | Internal.FeedComponent   | REGULAR | CRITICAL | 1      | 1       | 10080         | 10080             | 0            |
| 3445  | Crypto.NAV.XBTC/USDC     | REGULAR | CRITICAL | 2      | 3       | 10080         | 10080             | 0            |
| 99914 | Pyth.BN.AAPL/USDT        | REGULAR | CRITICAL | 1      | 4       | 10080         | 10080             | 0            |
| 99918 | Pyth.BN.EUR/USDT         | REGULAR | CRITICAL | 1      | 4       | 10080         | 10080             | 0            |
| 99915 | Pyth.BN.AMZN/USDT        | REGULAR | CRITICAL | 1      | 4       | 10080         | 10080             | 0            |
| 99920 | Pyth.BN.GOOGL/USDT       | REGULAR | CRITICAL | 1      | 4       | 10080         | 10080             | 0            |

## 4. Qualification outcomes (Stage 2)

Candidate funnel across all 617 flagged feed-sessions:

| Stage                                                | Count |
| ---------------------------------------------------- | ----- |
| Flagged feed-sessions entering qualification         | 617   |
| Candidate (publisher, feed-session) pairs discovered | 6607  |
| Passed gate 1 (activity ≥ 90% of open minutes)       | 2838  |
| Passed gate 2 (quality: Datascope or peer)           | 761   |
| Selected for remediation                             | 256   |

Outcome per feed-session: 245 met target (203 via additions, 42 already at
target), 372 unmet (16 of which received partial additions that narrow but
do not close the gap).

Selected additions by session:

| Session           | Publisher additions |
| ----------------- | ------------------- |
| OVER_NIGHT        | 103                 |
| REGULAR (default) | 77                  |
| POST_MARKET       | 49                  |
| PRE_MARKET        | 27                  |

## 5. Remediation plan status — PENDING

`output_csv/min_pub_remediation_spec.yaml` (generated Jul 14) contains 55
operations adding 256 (publisher, feed, session) entries across 191 feeds
and 31 publishers. **It has not been applied**: spot-checks confirm the
additions are absent from both `lazer_to_modify.json` and `lazer_new.json`.

Additions per publisher:

| Publisher | Additions |
| --------- | --------- |
| 41        | 31        |
| 48        | 31        |
| 73        | 23        |
| 29        | 19        |
| 19        | 16        |
| 86        | 16        |
| 80        | 12        |
| 22        | 9         |
| 72        | 9         |
| 84        | 9         |
| 24        | 8         |
| 32        | 8         |
| 12        | 7         |
| 20        | 6         |
| 42        | 6         |
| 44        | 6         |
| 37        | 5         |
| 45        | 5         |
| 57        | 4         |
| 21        | 3         |
| 50        | 3         |
| 55        | 3         |
| 82        | 3         |
| 2         | 2         |
| 14        | 2         |
| 54        | 2         |
| 65        | 2         |
| 69        | 2         |
| 71        | 2         |
| 7         | 1         |
| 11        | 1         |

To apply (dry-run first, then with `--apply`):

    python3 -m lazer_dq.apply_min_pub_remediation \
      --config lazer_new.json \
      --start-date 2026-07-06 --end-date 2026-07-13

Note: Stage 3 must reuse the Stage 2 window (2026-07-06 → 2026-07-13)
exactly, and the spec was computed against `lazer_to_modify.json` — re-verify
against `lazer_new.json` given the drift in §7 (16 flagged feeds changed).

## 6. Unresolvable feeds — 393 feed-sessions (370 feeds)

| Reason                   | Feed-sessions | Unique feeds |
| ------------------------ | ------------- | ------------ |
| candidates_fail_quality  | 210           | 198          |
| no_candidates            | 77            | 77           |
| no_benchmark_data        | 63            | 60           |
| candidates_fail_activity | 27            | 27           |
| still_below_target       | 16            | 16           |

Recommended disposition per bucket:

- **candidates_fail_quality (210)** — candidates are active but publish
  prices failing the benchmark/peer gate. Publisher outreach with per-feed
  quality evidence (`candidates_report.csv` has per-candidate metrics).
- **no_candidates (77)** — nobody else is even attempting to publish.
  Requires recruiting publishers, lowering minPublishers, or accepting the
  risk; feeds here with a zero-publisher worst minute are the deactivation
  discussion list.
- **no_benchmark_data (63)** — quality gate could not run (no Datascope RIC
  and no usable aggregate; includes the flat-NAV `zero_range` class).
  Needs an alternative quality metric (max-abs-pct-diff was floated) before
  these can ever auto-qualify.
- **candidates_fail_activity (27)** — candidates exist but publish < 90% of
  open minutes. Outreach: ask for sustained coverage, then re-run.
- **still_below_target (16)** — additions were found but not enough.
  Combine with outreach from the first two buckets.
