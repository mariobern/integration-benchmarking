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

## 7. Appendix A — config drift since the audit

`lazer_new.json` (2026-07-15) differs from `lazer_to_modify.json` (the
config the pipeline ran against) on 75 feeds: 16 state changes (11
COMING_SOON→STABLE among them) and 59 publisher/minPublishers edits. Audit
rows for these feeds — especially the 16 that are also flagged — may be
stale and should be re-audited after the remediation spec is applied.

| Feed  | Symbol                       | Change (lazer_to_modify → lazer_new) | Flagged? |
| ----- | ---------------------------- | ------------------------------------ | -------- |
| 579   | Crypto.STSUI/USD             | state INACTIVE → STABLE              |          |
| 730   | Crypto.STETH/ETH.RR          | state COMING_SOON → STABLE           |          |
| 759   | Crypto.WEETH/EETH.RR         | state COMING_SOON → STABLE           |          |
| 760   | Crypto.WM/M.RR               | state COMING_SOON → STABLE           |          |
| 922   | Equity.US.AAPL/USD           | publishers/minPublishers             |          |
| 949   | Equity.US.AMD/USD            | publishers/minPublishers             |          |
| 954   | Equity.US.AMZN/USD           | publishers/minPublishers             |          |
| 969   | Equity.US.ASML/USD           | publishers/minPublishers             |          |
| 972   | Equity.US.AVGO/USD           | publishers/minPublishers             |          |
| 979   | Equity.US.BA/USD             | publishers/minPublishers             | yes      |
| 999   | Equity.US.BRK-B/USD          | publishers/minPublishers             |          |
| 1012  | Equity.US.CANG/USD           | publishers/minPublishers             | yes      |
| 1014  | Equity.US.CAT/USD            | publishers/minPublishers             |          |
| 1042  | Equity.US.COIN/USD           | publishers/minPublishers             |          |
| 1046  | Equity.US.COST/USD           | publishers/minPublishers             |          |
| 1138  | Equity.US.FITB/USD           | publishers/minPublishers             | yes      |
| 1163  | Equity.US.GOOGL/USD          | publishers/minPublishers             |          |
| 1182  | Equity.US.HOOD/USD           | publishers/minPublishers             |          |
| 1201  | Equity.US.INTC/USD           | publishers/minPublishers             |          |
| 1223  | Equity.US.JPM/USD            | publishers/minPublishers             |          |
| 1246  | Equity.US.LLY/USD            | publishers/minPublishers             | yes      |
| 1247  | Equity.US.LMT/USD            | publishers/minPublishers             | yes      |
| 1264  | Equity.US.MCHP/USD           | publishers/minPublishers             | yes      |
| 1272  | Equity.US.META/USD           | publishers/minPublishers             |          |
| 1281  | Equity.US.MNST/USD           | publishers/minPublishers             | yes      |
| 1292  | Equity.US.MSFT/USD           | publishers/minPublishers             |          |
| 1294  | Equity.US.MSTR/USD           | publishers/minPublishers             |          |
| 1298  | Equity.US.MU/USD             | publishers/minPublishers             |          |
| 1304  | Equity.US.NFLX/USD           | publishers/minPublishers             |          |
| 1314  | Equity.US.NVDA/USD           | publishers/minPublishers             |          |
| 1324  | Equity.US.ORCL/USD           | publishers/minPublishers             |          |
| 1346  | Equity.US.PLTR/USD           | publishers/minPublishers             |          |
| 1363  | Equity.US.QQQ/USD            | publishers/minPublishers             |          |
| 1398  | Equity.US.SPY/USD            | publishers/minPublishers             |          |
| 1420  | Equity.US.TER/USD            | publishers/minPublishers             |          |
| 1435  | Equity.US.TSLA/USD           | publishers/minPublishers             |          |
| 1440  | Equity.US.TTWO/USD           | publishers/minPublishers             |          |
| 1474  | Equity.US.VRSN/USD           | publishers/minPublishers             | yes      |
| 1499  | Equity.US.XOM/USD            | publishers/minPublishers             | yes      |
| 1668  | Equity.JP.1321/JPY           | state COMING_SOON → STABLE           |          |
| 1683  | Equity.US.CRCL/USD           | publishers/minPublishers             |          |
| 1713  | Equity.US.MAGS/USD           | publishers/minPublishers             |          |
| 2269  | Equity.US.AAL/USD            | publishers/minPublishers             | yes      |
| 2271  | Equity.US.BABA/USD           | publishers/minPublishers             |          |
| 2274  | Equity.US.BOTZ/USD           | publishers/minPublishers             | yes      |
| 2353  | Equity.US.BMNR/USD           | publishers/minPublishers             |          |
| 2363  | Equity.US.IREN/USD           | publishers/minPublishers             |          |
| 2370  | Equity.US.RGTI/USD           | publishers/minPublishers             |          |
| 2371  | Equity.US.RIVN/USD           | publishers/minPublishers             |          |
| 2372  | Equity.US.SMH/USD            | publishers/minPublishers             |          |
| 2689  | Equity.US.OPEN/USD           | publishers/minPublishers             |          |
| 2690  | Equity.US.QBTS/USD           | publishers/minPublishers             |          |
| 2737  | Equity.US.CRWV/USD           | publishers/minPublishers             |          |
| 2773  | Equity.US.GDX/USD            | publishers/minPublishers             |          |
| 2858  | Equity.US.SNDK/USD           | publishers/minPublishers             |          |
| 2911  | Equity.US.PURR/USD           | publishers/minPublishers             | yes      |
| 2928  | Equity.US.NLR/USD            | publishers/minPublishers             |          |
| 2929  | Equity.US.AIQ/USD            | publishers/minPublishers             | yes      |
| 2930  | Equity.US.SHLD/USD           | publishers/minPublishers             | yes      |
| 2942  | Equity.US.BTGO/USD           | publishers/minPublishers             |          |
| 2977  | Commodities.PDM6/USD         | publishers/minPublishers             |          |
| 3035  | Equity.US.NMM6/USD           | publishers/minPublishers             |          |
| 3057  | Commodities.GON6/USD         | state COMING_SOON → INACTIVE         |          |
| 3072  | Commodities.WTIX6/USD        | state COMING_SOON → STABLE           |          |
| 3079  | Commodities.WHN6/USD         | state STABLE → INACTIVE              | yes      |
| 3215  | Commodities.LCZ6/USc         | state COMING_SOON → STABLE           |          |
| 3250  | InterestRate.3MSH6           | state COMING_SOON → INACTIVE         |          |
| 3254  | InterestRate.10YM6           | state COMING_SOON → INACTIVE         |          |
| 3265  | Commodities.Index.NATGAS/USD | state COMING_SOON → STABLE           |          |
| 3290  | Equity.Index.US500/USD       | state COMING_SOON → STABLE           |          |
| 3291  | Equity.Index.US100/USD       | state COMING_SOON → STABLE           |          |
| 3307  | Equity.US.USAR/USD           | publishers/minPublishers             |          |
| 3320  | Equity.US.TZA/USD            | publishers/minPublishers             | yes      |
| 3337  | Equity.JP.285A/JPY           | state COMING_SOON → STABLE           |          |
| 99941 | Pyth.HL.NATGAS/USDC          | state COMING_SOON → STABLE           |          |

## 8. Appendix B — all flagged feed-sessions with qualification outcome

CRITICAL first, then WARN; `Cand/G1/G2/Sel` = candidates discovered / passed
activity gate / passed quality gate / selected. `Worst min` is
`qualify_candidates`'s own re-derivation of the worst per-minute
active-publisher count (`worst_minute_before`), which counts both ACCEPTED
and UNAUTHORIZED-rejected updates from currently-allowed publishers — it is
not directly comparable to §3's audit-derived `worst_minute_active` and can
diverge from it for the same feed/session (e.g. feed 1572: 0 in §3 vs 4
here).

| Feed  | Symbol                          | Session     | Class    | Reason                   | Cand | G1  | G2  | Sel | Worst min | Target | Detail                                               |
| ----- | ------------------------------- | ----------- | -------- | ------------------------ | ---- | --- | --- | --- | --------- | ------ | ---------------------------------------------------- |
| 209   | FundingRate.Deribit.1h.BTC/USD  | REGULAR     | CRITICAL | candidates_fail_quality  | 1    | 1   | 0   | 0   | 1         | 3      | 1 active candidates, 0 passed quality                |
| 211   | FundingRate.Deribit.1h.ETH/USD  | REGULAR     | CRITICAL | candidates_fail_quality  | 1    | 1   | 0   | 0   | 1         | 3      | 1 active candidates, 0 passed quality                |
| 309   | Crypto.DATA/USD                 | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 2   | 0   | 0   | 7         | 5      | 2 active candidates, 0 passed quality                |
| 387   | Crypto.BOLD/USD                 | REGULAR     | CRITICAL | candidates_fail_quality  | 2    | 1   | 0   | 0   | 5         | 5      | 1 active candidates, 0 passed quality                |
| 463   | Crypto.KHYPE/USD                | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 4         | 4      | 1 candidates all below 0.9                           |
| 470   | Crypto.LION/USD                 | REGULAR     | CRITICAL | candidates_fail_quality  | 7    | 6   | 0   | 0   | 4         | 5      | 6 active candidates, 0 passed quality                |
| 490   | Crypto.MEZO.MUSD/USD            | REGULAR     | CRITICAL | candidates_fail_quality  | 1    | 1   | 0   | 0   | 3         | 4      | 1 active candidates, 0 passed quality                |
| 502   | Crypto.MSETH/USD                | REGULAR     | CRITICAL | candidates_fail_quality  | 3    | 2   | 0   | 0   | 3         | 4      | 2 active candidates, 0 passed quality                |
| 504   | Crypto.MSUSD/USD                | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 4         | 4      | 1 candidates all below 0.9                           |
| 613   | Crypto.USDTB/USD                | REGULAR     | CRITICAL | candidates_fail_quality  | 8    | 7   | 0   | 0   | 6         | 5      | 7 active candidates, 0 passed quality                |
| 650   | Crypto.UBTC/USD                 | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 8         | 5      | 1 candidates all below 0.9                           |
| 651   | Crypto.UETH/USD                 | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 7         | 5      | 1 candidates all below 0.9                           |
| 697   | Crypto.KHYPE/HYPE.RR            | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 1   | 0   | 0   | 7         | 5      | no aggregate (price_feeds) data                      |
| 762   | Crypto.WSTHYPE/STHYPE.RR        | REGULAR     | CRITICAL | no_benchmark_data        | 3    | 2   | 0   | 0   | 7         | 5      | no aggregate (price_feeds) data                      |
| 1060  | Equity.US.CTSH/USD              | PRE_MARKET  | CRITICAL | candidates_fail_quality  | 19   | 9   | 0   | 0   | 3         | 5      | 9 active candidates, 0 passed quality                |
| 1088  | Equity.US.DRI/USD               | REGULAR     | CRITICAL | candidates_fail_quality  | 21   | 17  | 0   | 0   | 3         | 5      | 17 active candidates, 0 passed quality               |
| 1095  | Equity.US.EBAY/USD              | OVER_NIGHT  | CRITICAL | no_benchmark_data        | 25   | 8   | 0   | 0   | 2         | 4      | mode=us-equities-overnight, no engine data in window |
| 1120  | Equity.US.EWH/USD               | OVER_NIGHT  | CRITICAL | no_benchmark_data        | 18   | 4   | 0   | 0   | 1         | 4      | mode=us-equities-overnight, no engine data in window |
| 1138  | Equity.US.FITB/USD              | PRE_MARKET  | CRITICAL | no_benchmark_data        | 21   | 11  | 0   | 0   | 1         | 3      | mode=us-equities-pre, no engine data in window       |
| 1138  | Equity.US.FITB/USD              | POST_MARKET | CRITICAL | no_benchmark_data        | 22   | 12  | 0   | 0   | 1         | 3      | mode=us-equities-post, no engine data in window      |
| 1179  | Equity.US.HODL/USD              | POST_MARKET | CRITICAL | no_benchmark_data        | 18   | 10  | 0   | 0   | 2         | 4      | mode=us-equities-post, no engine data in window      |
| 1180  | Equity.US.HOLX/USD              | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 2   | 0   | 0   | 3         | 5      | mode=us-equities, no engine data in window           |
| 1264  | Equity.US.MCHP/USD              | PRE_MARKET  | CRITICAL | candidates_fail_quality  | 21   | 9   | 0   | 0   | 3         | 5      | 9 active candidates, 0 passed quality                |
| 1264  | Equity.US.MCHP/USD              | POST_MARKET | CRITICAL | still_below_target       | 21   | 8   | 1   | 1   | 3         | 5      | projected worst 4 < target 5 after adding [55]       |
| 1315  | Equity.US.NVR/USD               | REGULAR     | CRITICAL | candidates_fail_quality  | 20   | 15  | 0   | 0   | 2         | 4      | 15 active candidates, 0 passed quality               |
| 1332  | Equity.US.PAYX/USD              | POST_MARKET | CRITICAL | candidates_fail_quality  | 21   | 10  | 0   | 0   | 3         | 5      | 10 active candidates, 0 passed quality               |
| 1381  | Equity.US.RTX/USD               | POST_MARKET | CRITICAL | still_below_target       | 24   | 13  | 1   | 1   | 2         | 4      | projected worst 3 < target 4 after adding [44]       |
| 1428  | Equity.US.TPL/USD               | REGULAR     | CRITICAL | candidates_fail_quality  | 16   | 13  | 0   | 0   | 2         | 4      | 13 active candidates, 0 passed quality               |
| 1444  | Equity.US.UAL/USD               | PRE_MARKET  | CRITICAL | candidates_fail_quality  | 17   | 8   | 0   | 0   | 3         | 5      | 8 active candidates, 0 passed quality                |
| 1474  | Equity.US.VRSN/USD              | PRE_MARKET  | CRITICAL | candidates_fail_quality  | 18   | 8   | 0   | 0   | 2         | 4      | 8 active candidates, 0 passed quality                |
| 1474  | Equity.US.VRSN/USD              | POST_MARKET | CRITICAL | no_benchmark_data        | 18   | 9   | 0   | 0   | 2         | 4      | mode=us-equities-post, no engine data in window      |
| 1555  | FundingRate.Hyperliquid.ETH/USD | REGULAR     | CRITICAL | still_below_target       | 3    | 3   | 1   | 1   | 1         | 3      | projected worst 2 < target 3 after adding [82]       |
| 1572  | Crypto.LHYPE/HYPE.RR            | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 4         | 5      | no aggregate (price_feeds) data                      |
| 1575  | Crypto.NAV.ACRED/USD            | REGULAR     | CRITICAL | candidates_fail_quality  | 1    | 1   | 0   | 0   | 7         | 5      | 1 active candidates, 0 passed quality                |
| 1596  | Crypto.USOL/USD                 | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 5         | 5      | 1 candidates all below 0.9                           |
| 1791  | Crypto.AAPLX/AAPL.RR            | REGULAR     | CRITICAL | candidates_fail_quality  | 7    | 6   | 0   | 0   | 2         | 4      | 6 active candidates, 0 passed quality                |
| 1807  | Crypto.GOOGLX/GOOGL.RR          | REGULAR     | CRITICAL | candidates_fail_quality  | 7    | 6   | 0   | 0   | 2         | 4      | 6 active candidates, 0 passed quality                |
| 1821  | Crypto.MCDX/MCD.RR              | REGULAR     | CRITICAL | candidates_fail_quality  | 7    | 7   | 0   | 0   | 2         | 4      | 7 active candidates, 0 passed quality                |
| 1823  | Crypto.METAX/META.RR            | REGULAR     | CRITICAL | candidates_fail_quality  | 8    | 7   | 0   | 0   | 2         | 4      | 7 active candidates, 0 passed quality                |
| 1826  | Crypto.MSTRX/MSTR.RR            | REGULAR     | CRITICAL | candidates_fail_quality  | 8    | 7   | 0   | 0   | 2         | 4      | 7 active candidates, 0 passed quality                |
| 1830  | Crypto.NAV.USCC/USD             | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 5   | 0   | 0   | 1         | 3      | 5 active candidates, 0 passed quality                |
| 1832  | Crypto.NVDAX/NVDA.RR            | REGULAR     | CRITICAL | candidates_fail_quality  | 8    | 7   | 0   | 0   | 2         | 4      | 7 active candidates, 0 passed quality                |
| 1836  | Crypto.QQQX/QQQ.RR              | REGULAR     | CRITICAL | candidates_fail_quality  | 8    | 7   | 0   | 0   | 2         | 4      | 7 active candidates, 0 passed quality                |
| 1842  | Crypto.SPYX/SPY.RR              | REGULAR     | CRITICAL | candidates_fail_quality  | 8    | 7   | 0   | 0   | 2         | 4      | 7 active candidates, 0 passed quality                |
| 1846  | Crypto.TSLAX/TSLA.RR            | REGULAR     | CRITICAL | candidates_fail_quality  | 8    | 7   | 0   | 0   | 2         | 4      | 7 active candidates, 0 passed quality                |
| 1851  | Crypto.USX/USD                  | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 2         | 4      | 5 submitting, all allowed/excluded                   |
| 2300  | Equity.US.SSK/USD               | REGULAR     | CRITICAL | candidates_fail_quality  | 11   | 7   | 0   | 0   | 2         | 4      | 7 active candidates, 0 passed quality                |
| 2303  | Equity.US.UPXI/USD              | REGULAR     | CRITICAL | candidates_fail_quality  | 14   | 9   | 0   | 0   | 2         | 4      | 9 active candidates, 0 passed quality                |
| 2326  | Crypto.FF/USD                   | REGULAR     | CRITICAL | no_benchmark_data        | 5    | 3   | 0   | 0   | 7         | 5      | no aggregate (price_feeds) data                      |
| 2334  | Crypto.HYUSD/JITOSOL.RR         | REGULAR     | CRITICAL | still_below_target       | 2    | 2   | 1   | 1   | 2         | 4      | projected worst 2 < target 4 after adding [24]       |
| 2339  | Crypto.SHYUSD/JITOSOL.RR        | REGULAR     | CRITICAL | candidates_fail_quality  | 2    | 2   | 0   | 0   | 2         | 4      | 2 active candidates, 0 passed quality                |
| 2351  | Crypto.XSOL/JITOSOL.RR          | REGULAR     | CRITICAL | candidates_fail_quality  | 2    | 2   | 0   | 0   | 2         | 4      | 2 active candidates, 0 passed quality                |
| 2366  | Equity.US.NIO/USD               | PRE_MARKET  | CRITICAL | candidates_fail_quality  | 13   | 6   | 0   | 0   | 2         | 4      | 6 active candidates, 0 passed quality                |
| 2394  | Crypto.LMTS/USD                 | REGULAR     | CRITICAL | candidates_fail_quality  | 3    | 1   | 0   | 0   | 6         | 5      | 1 active candidates, 0 passed quality                |
| 2395  | Crypto.META/USD                 | REGULAR     | CRITICAL | no_benchmark_data        | 6    | 4   | 0   | 0   | 4         | 4      | no aggregate (price_feeds) data                      |
| 2419  | Equity.US.STRC/USD              | PRE_MARKET  | CRITICAL | candidates_fail_quality  | 14   | 4   | 0   | 0   | 4         | 4      | 4 active candidates, 0 passed quality                |
| 2687  | Crypto.USDF/USD                 | REGULAR     | CRITICAL | candidates_fail_quality  | 4    | 3   | 0   | 0   | 2         | 4      | 3 active candidates, 0 passed quality                |
| 2700  | Crypto.MMT/USD                  | REGULAR     | CRITICAL | candidates_fail_activity | 2    | 0   | 0   | 0   | 8         | 5      | 2 candidates all below 0.9                           |
| 2701  | Crypto.SEDA/USD                 | REGULAR     | CRITICAL | candidates_fail_activity | 2    | 0   | 0   | 0   | 4         | 5      | 2 candidates all below 0.9                           |
| 2769  | Equity.US.FLUT/USD              | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 19   | 6   | 0   | 0   | 1         | 4      | 6 active candidates, 0 passed quality                |
| 2864  | Equity.US.SPOT/USD              | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 18   | 6   | 0   | 0   | 2         | 4      | 6 active candidates, 0 passed quality                |
| 2922  | Custom.PRF1/USD                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 2924  | Custom.PRF2/USD                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 2925  | Custom.PRF3/USD                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 2926  | Custom.PRF4/USD                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 2927  | Custom.PRF5/USD                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 2929  | Equity.US.AIQ/USD               | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 21   | 7   | 0   | 0   | 1         | 4      | 7 active candidates, 0 passed quality                |
| 2930  | Equity.US.SHLD/USD              | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 19   | 6   | 0   | 0   | 2         | 4      | 6 active candidates, 0 passed quality                |
| 2978  | Commodities.PDU6/USD            | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 2   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 2980  | Commodities.PTN6/USD            | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 2   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3019  | Commodities.CON6/USD            | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3030  | Crypto.DBUSDC/USDC.RR           | REGULAR     | CRITICAL | candidates_fail_quality  | 2    | 2   | 0   | 0   | 2         | 4      | 2 active candidates, 0 passed quality                |
| 3043  | Commodities.BRENTU6/USD         | REGULAR     | CRITICAL | no_benchmark_data        | 3    | 3   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3044  | Commodities.BRENTV6/USD         | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 2   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3045  | Commodities.BRENTX6/USD         | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 2   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3046  | Commodities.BRENTZ6/USD         | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 2   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3050  | Crypto.DIME/USD                 | REGULAR     | CRITICAL | still_below_target       | 1    | 1   | 1   | 1   | 2         | 4      | projected worst 2 < target 4 after adding [2]        |
| 3054  | Equity.US.KORU/USD              | OVER_NIGHT  | CRITICAL | no_benchmark_data        | 16   | 5   | 0   | 0   | 2         | 4      | mode=us-equities-overnight, no engine data in window |
| 3058  | Commodities.GOQ6/USD            | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3059  | Commodities.GOU6/USD            | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 1         | 3      | 4 submitting, all allowed/excluded                   |
| 3060  | Commodities.GOV6/USD            | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3079  | Commodities.WHN6/USD            | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 0         | 3      | mode=commodity, no engine data in window             |
| 3083  | Commodities.SON6/USD            | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3090  | Commodities.TGEQ6/EUR           | REGULAR     | CRITICAL | no_benchmark_data        | 3    | 3   | 0   | 0   | 1         | 3      | mode=commodity, no engine data in window             |
| 3120  | Equity.US.VXN6                  | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 1         | 3      | mode=us-equities, no engine data in window           |
| 3121  | Equity.US.VXQ6                  | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 1         | 3      | mode=us-equities, no engine data in window           |
| 3148  | Crypto.SETHFI/ETHFI.RR          | REGULAR     | CRITICAL | still_below_target       | 1    | 1   | 1   | 1   | 3         | 5      | projected worst 4 < target 5 after adding [24]       |
| 3153  | Metal.Index.GOLD/USD            | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 2   | 0   | 0   | 1         | 3      | mode=metals, no engine data in window                |
| 3154  | Metal.Index.SILVER/USD          | REGULAR     | CRITICAL | no_benchmark_data        | 2    | 2   | 0   | 0   | 1         | 3      | mode=metals, no engine data in window                |
| 3170  | Equity.US.BIRD/USD              | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 15   | 4   | 0   | 0   | 1         | 4      | 4 active candidates, 0 passed quality                |
| 3172  | Commodities.CAN6/USD            | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 2 submitting, all allowed/excluded                   |
| 3176  | Crypto.WM/USD                   | REGULAR     | CRITICAL | candidates_fail_quality  | 2    | 2   | 0   | 0   | 2         | 4      | 2 active candidates, 0 passed quality                |
| 3182  | Crypto.Index.EBTC/USD           | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 2         | 4      | 1 candidates all below 0.9                           |
| 3183  | FX.Index.EUR/USD                | REGULAR     | CRITICAL | no_benchmark_data        | 3    | 1   | 0   | 0   | 0         | 3      | mode=fx, no engine data in window                    |
| 3184  | FX.Index.USD/JPY                | REGULAR     | CRITICAL | no_benchmark_data        | 3    | 1   | 0   | 0   | 0         | 3      | mode=fx, no engine data in window                    |
| 3185  | Equity.Index.TSLA/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 1         | 3      | 4 active candidates, 0 passed quality                |
| 3186  | Equity.Index.CRCL/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 4    | 4   | 0   | 0   | 1         | 3      | 4 active candidates, 0 passed quality                |
| 3187  | Equity.Index.MSTR/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 1         | 3      | 4 active candidates, 0 passed quality                |
| 3188  | Equity.Index.NVDA/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 1         | 3      | 4 active candidates, 0 passed quality                |
| 3189  | Equity.Index.HOOD/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 0         | 3      | 4 active candidates, 0 passed quality                |
| 3191  | Equity.Index.AAPL/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 0         | 3      | 4 active candidates, 0 passed quality                |
| 3194  | Equity.Index.GOOGL/USD          | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 0         | 3      | 4 active candidates, 0 passed quality                |
| 3196  | Equity.Index.MSFT/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 0         | 3      | 4 active candidates, 0 passed quality                |
| 3217  | Metal.OGQ6/USD                  | REGULAR     | CRITICAL | no_benchmark_data        | 1    | 1   | 0   | 0   | 1         | 3      | mode=metals, no engine data in window                |
| 3251  | InterestRate.3MSM6              | REGULAR     | CRITICAL | candidates_fail_quality  | 2    | 2   | 0   | 0   | 1         | 3      | 2 active candidates, 0 passed quality                |
| 3252  | InterestRate.3MSU6              | REGULAR     | CRITICAL | candidates_fail_quality  | 2    | 2   | 0   | 0   | 1         | 3      | 2 active candidates, 0 passed quality                |
| 3253  | InterestRate.3MSZ6              | REGULAR     | CRITICAL | candidates_fail_quality  | 2    | 2   | 0   | 0   | 1         | 3      | 2 active candidates, 0 passed quality                |
| 3255  | InterestRate.10YU6              | REGULAR     | CRITICAL | still_below_target       | 2    | 2   | 1   | 1   | 1         | 3      | projected worst 2 < target 3 after adding [48]       |
| 3261  | Equity.Index.INTC/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 0         | 3      | 4 active candidates, 0 passed quality                |
| 3263  | Equity.Index.MU/USD             | REGULAR     | CRITICAL | candidates_fail_quality  | 5    | 4   | 0   | 0   | 0         | 3      | 4 active candidates, 0 passed quality                |
| 3270  | Crypto.NFALCON/USD.RR           | REGULAR     | CRITICAL | still_below_target       | 3    | 2   | 1   | 1   | 2         | 4      | projected worst 3 < target 4 after adding [48]       |
| 3271  | Crypto.NALPHA/USD.RR            | REGULAR     | CRITICAL | still_below_target       | 1    | 1   | 1   | 1   | 2         | 4      | projected worst 3 < target 4 after adding [71]       |
| 3272  | Crypto.NBASIS/USD.RR            | REGULAR     | CRITICAL | still_below_target       | 2    | 1   | 1   | 1   | 2         | 4      | projected worst 3 < target 4 after adding [24]       |
| 3273  | Crypto.NOPAL/USD.RR             | REGULAR     | CRITICAL | still_below_target       | 1    | 1   | 1   | 1   | 2         | 4      | projected worst 3 < target 4 after adding [71]       |
| 3274  | Crypto.NTBILL/USD.RR            | REGULAR     | CRITICAL | still_below_target       | 2    | 1   | 1   | 1   | 2         | 4      | projected worst 3 < target 4 after adding [24]       |
| 3280  | Equity.US.BILI/USD              | OVER_NIGHT  | CRITICAL | no_benchmark_data        | 16   | 5   | 0   | 0   | 2         | 4      | mode=us-equities-overnight, no engine data in window |
| 3282  | Equity.US.IBKR/USD              | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 17   | 5   | 0   | 0   | 2         | 4      | 5 active candidates, 0 passed quality                |
| 3285  | Equity.US.AEHR/USD              | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 16   | 5   | 0   | 0   | 2         | 4      | 5 active candidates, 0 passed quality                |
| 3304  | Crypto.Index.SILV/USD           | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 1         | 3      | 3 submitting, all allowed/excluded                   |
| 3316  | Equity.Index.SPCX/USD           | REGULAR     | CRITICAL | candidates_fail_quality  | 3    | 3   | 0   | 0   | 1         | 3      | 3 active candidates, 0 passed quality                |
| 3320  | Equity.US.TZA/USD               | PRE_MARKET  | CRITICAL | still_below_target       | 9    | 4   | 1   | 1   | 3         | 5      | projected worst 4 < target 5 after adding [48]       |
| 3321  | Crypto.AMZNX/USD                | REGULAR     | CRITICAL | candidates_fail_activity | 2    | 0   | 0   | 0   | 4         | 5      | 2 candidates all below 0.9                           |
| 3345  | Equity.US.MXL/USD               | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 15   | 5   | 0   | 0   | 2         | 4      | 5 active candidates, 0 passed quality                |
| 3348  | Equity.US.TSEM/USD              | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 15   | 5   | 0   | 0   | 2         | 5      | 5 active candidates, 0 passed quality                |
| 3353  | Equity.US.NVTS/USD              | OVER_NIGHT  | CRITICAL | still_below_target       | 15   | 6   | 1   | 1   | 2         | 4      | projected worst 3 < target 4 after adding [29]       |
| 3396  | Crypto.MUX/USD                  | REGULAR     | CRITICAL | candidates_fail_quality  | 1    | 1   | 0   | 0   | 0         | 3      | 1 active candidates, 0 passed quality                |
| 3407  | Crypto.BEAT/USD                 | REGULAR     | CRITICAL | candidates_fail_activity | 2    | 0   | 0   | 0   | 4         | 5      | 2 candidates all below 0.9                           |
| 3409  | Equity.US.ECHO/USD              | OVER_NIGHT  | CRITICAL | candidates_fail_quality  | 10   | 2   | 0   | 0   | 2         | 4      | 2 active candidates, 0 passed quality                |
| 3410  | Crypto.U/USD                    | REGULAR     | CRITICAL | candidates_fail_quality  | 6    | 2   | 0   | 0   | 2         | 5      | 2 active candidates, 0 passed quality                |
| 3411  | Crypto.STABLE/USD               | REGULAR     | CRITICAL | candidates_fail_activity | 2    | 0   | 0   | 0   | 4         | 5      | 2 candidates all below 0.9                           |
| 3412  | Crypto.BFUSD/USD                | REGULAR     | CRITICAL | candidates_fail_activity | 2    | 0   | 0   | 0   | 3         | 5      | 2 candidates all below 0.9                           |
| 3413  | Crypto.HTX/USD                  | REGULAR     | CRITICAL | candidates_fail_activity | 3    | 0   | 0   | 0   | 3         | 5      | 3 candidates all below 0.9                           |
| 3414  | Crypto.M/USD                    | REGULAR     | CRITICAL | candidates_fail_activity | 2    | 0   | 0   | 0   | 3         | 5      | 2 candidates all below 0.9                           |
| 3415  | Crypto.LAB/USD                  | REGULAR     | CRITICAL | candidates_fail_activity | 3    | 0   | 0   | 0   | 3         | 5      | 3 candidates all below 0.9                           |
| 3416  | Crypto.WBT/USD                  | REGULAR     | CRITICAL | candidates_fail_quality  | 6    | 2   | 0   | 0   | 0         | 4      | 2 active candidates, 0 passed quality                |
| 3417  | Crypto.RAIN/USD                 | REGULAR     | CRITICAL | candidates_fail_activity | 3    | 0   | 0   | 0   | 3         | 5      | 3 candidates all below 0.9                           |
| 3418  | Crypto.ANSEM/USD                | REGULAR     | CRITICAL | candidates_fail_activity | 3    | 0   | 0   | 0   | 0         | 4      | 3 candidates all below 0.9                           |
| 3419  | Crypto.ADI/USD                  | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 3         | 4      | 1 candidates all below 0.9                           |
| 3438  | Equity.US.SKHYV/USD             | REGULAR     | CRITICAL | candidates_fail_activity | 3    | 0   | 0   | 0   | 0         | 4      | 3 candidates all below 0.9                           |
| 3441  | Crypto.CASHCAT/USD              | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 0         | 4      | 1 candidates all below 0.9                           |
| 3444  | Crypto.NAV.XHYPE/USDC           | REGULAR     | CRITICAL | candidates_fail_activity | 1    | 0   | 0   | 0   | 0         | 4      | 1 candidates all below 0.9                           |
| 3445  | Crypto.NAV.XBTC/USDC            | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 4      | 3 submitting, all allowed/excluded                   |
| 99000 | Internal.FeedComponent          | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99001 | FeedComponent.DIA/USD.Dividend  | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99002 | FeedComponent.DIA/USD.K         | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99003 | FeedComponent.SPY/USD.K         | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99004 | FeedComponent.SPY/USD.Dividend  | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99005 | FeedComponent.IVV/USD.K         | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99006 | FeedComponent.IVV/USD.Dividend  | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99007 | FeedComponent.VOO/USD.K         | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99008 | FeedComponent.VOO/USD.Dividend  | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99009 | FeedComponent.QQQ/USD.K         | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99010 | FeedComponent.QQQ/USD.Dividend  | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99011 | FeedComponent.QQQM/USD.K        | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99012 | FeedComponent.QQQM/USD.Dividend | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99914 | Pyth.BN.AAPL/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99915 | Pyth.BN.AMZN/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99916 | Pyth.BN.BRENT/USDT              | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99917 | Pyth.BN.CRCL/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99918 | Pyth.BN.EUR/USDT                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99919 | Pyth.BN.GBP/USDT                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99920 | Pyth.BN.GOOGL/USDT              | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99921 | Pyth.BN.HOOD/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99922 | Pyth.BN.INTC/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99923 | Pyth.BN.META/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99924 | Pyth.BN.XAU/USDT                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99925 | Pyth.BN.MSFT/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99926 | Pyth.BN.MSTR/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99927 | Pyth.BN.MU/USDT                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99928 | Pyth.BN.NVDA/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99929 | Pyth.BN.SPCX/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99930 | Pyth.BN.TSLA/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99931 | Pyth.BN.USD/JPY                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99932 | Pyth.BN.WTI/USDT                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99933 | Pyth.BN.XAG/USDT                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 1 submitting, all allowed/excluded                   |
| 99934 | Pyth.HL.SPCX/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99943 | Pyth.HL.MU/USDC                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99944 | Pyth.HL.INTC/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99951 | Pyth.DC.INTC/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99958 | Pyth.DC.HOOD/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99959 | Pyth.HL.HOOD/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99961 | Pyth.HL.MSTR/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99962 | Pyth.DC.CRCL/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99963 | Pyth.HL.CRCL/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99964 | Pyth.DC.GOOGL/USDT              | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99965 | Pyth.DC.TSLA/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99966 | Pyth.DC.NVDA/USDT               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99971 | Pyth.HL.USD/JPY                 | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99972 | Pyth.HL.EUR/USDC                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99973 | Pyth.HL.GBP/USDC                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99974 | Pyth.HL.BRENT/USDC              | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99975 | Pyth.HL.WTI/USDC                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99976 | Pyth.HL.XAG/USDC                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99977 | Pyth.HL.XAU/USDC                | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99985 | Pyth.HL.GOOGL/USDC              | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99986 | Pyth.HL.TSLA/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99987 | Pyth.HL.NVDA/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99988 | Pyth.HL.MSFT/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99989 | Pyth.HL.META/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99990 | Pyth.HL.AMZN/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 0 submitting, all allowed/excluded                   |
| 99991 | Pyth.HL.AAPL/USDC               | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 0         | 3      | 3 submitting, all allowed/excluded                   |
| 99999 | Internal.E2EProbe/Latency       | REGULAR     | CRITICAL | no_candidates            | 0    | 0   | 0   | 0   | 1         | 3      | 1 submitting, all allowed/excluded                   |
| 12    | Crypto.TON/USD                  | REGULAR     | WARN     | candidates_fail_quality  | 8    | 7   | 0   | 0   | 4         | 5      | 7 active candidates, 0 passed quality                |
| 113   | FundingRate.Deribit.8h.BTC/USD  | REGULAR     | WARN     | candidates_fail_quality  | 1    | 1   | 0   | 0   | 2         | 3      | 1 active candidates, 0 passed quality                |
| 210   | FundingRate.Deribit.8h.ETH/USD  | REGULAR     | WARN     | candidates_fail_quality  | 1    | 1   | 0   | 0   | 2         | 3      | 1 active candidates, 0 passed quality                |
| 212   | FundingRate.Deribit.8h.SOL/USDC | REGULAR     | WARN     | no_candidates            | 0    | 0   | 0   | 0   | 2         | 3      | 4 submitting, all allowed/excluded                   |
| 213   | FundingRate.Deribit.1h.SOL/USDC | REGULAR     | WARN     | no_candidates            | 0    | 0   | 0   | 0   | 2         | 3      | 4 submitting, all allowed/excluded                   |
| 967   | Equity.US.ARKK/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 27   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 976   | Equity.US.AXP/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 26   | 8   | 0   | 0   | 3         | 4      | 8 active candidates, 0 passed quality                |
| 977   | Equity.US.AZN/USD               | OVER_NIGHT  | WARN     | no_benchmark_data        | 25   | 7   | 0   | 0   | 3         | 4      | mode=us-equities-overnight, no engine data in window |
| 979   | Equity.US.BA/USD                | OVER_NIGHT  | WARN     | candidates_fail_quality  | 25   | 8   | 0   | 0   | 3         | 4      | 8 active candidates, 0 passed quality                |
| 991   | Equity.US.BK/USD                | REGULAR     | WARN     | no_benchmark_data        | 4    | 1   | 0   | 0   | 4         | 5      | mode=us-equities, no engine data in window           |
| 995   | Equity.US.BLK/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 25   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1007  | Equity.US.BX/USD                | OVER_NIGHT  | WARN     | still_below_target       | 24   | 8   | 1   | 1   | 3         | 4      | projected worst 3 < target 4 after adding [29]       |
| 1012  | Equity.US.CANG/USD              | REGULAR     | WARN     | candidates_fail_quality  | 10   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1021  | Equity.US.CDNS/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 22   | 11  | 0   | 0   | 3         | 4      | 11 active candidates, 0 passed quality               |
| 1035  | Equity.US.CME/USD               | POST_MARKET | WARN     | no_benchmark_data        | 22   | 13  | 0   | 0   | 2         | 3      | mode=us-equities-post, no engine data in window      |
| 1041  | Equity.US.COF/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1044  | Equity.US.COP/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1054  | Equity.US.CRWD/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1055  | Equity.US.CSCO/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 25   | 9   | 0   | 0   | 3         | 4      | 9 active candidates, 0 passed quality                |
| 1070  | Equity.US.DDOG/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1077  | Equity.US.DGX/USD               | REGULAR     | WARN     | candidates_fail_quality  | 20   | 16  | 0   | 0   | 4         | 5      | 16 active candidates, 0 passed quality               |
| 1093  | Equity.US.DXCM/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 20   | 9   | 0   | 0   | 3         | 4      | 9 active candidates, 0 passed quality                |
| 1120  | Equity.US.EWH/USD               | POST_MARKET | WARN     | no_benchmark_data        | 18   | 6   | 0   | 0   | 3         | 4      | mode=us-equities-post, no engine data in window      |
| 1123  | Equity.US.EXPE/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 20   | 9   | 0   | 0   | 4         | 5      | 9 active candidates, 0 passed quality                |
| 1128  | Equity.US.FAST/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 20   | 8   | 0   | 0   | 3         | 4      | 8 active candidates, 0 passed quality                |
| 1130  | Equity.US.FCX/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1140  | Equity.US.FOX/USD               | PRE_MARKET  | WARN     | candidates_fail_quality  | 19   | 8   | 0   | 0   | 3         | 4      | 8 active candidates, 0 passed quality                |
| 1152  | Equity.US.GEV/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 22   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1156  | Equity.US.GL/USD                | PRE_MARKET  | WARN     | still_below_target       | 19   | 6   | 1   | 1   | 3         | 4      | projected worst 3 < target 4 after adding [19]       |
| 1179  | Equity.US.HODL/USD              | PRE_MARKET  | WARN     | no_benchmark_data        | 15   | 7   | 0   | 0   | 4         | 5      | mode=us-equities-pre, no engine data in window       |
| 1195  | Equity.US.IBM/USD               | OVER_NIGHT  | WARN     | no_benchmark_data        | 25   | 9   | 0   | 0   | 3         | 4      | mode=us-equities-overnight, no engine data in window |
| 1197  | Equity.US.IDXX/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 18   | 8   | 0   | 0   | 2         | 4      | 8 active candidates, 0 passed quality                |
| 1202  | Equity.US.INTU/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 22   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 1211  | Equity.US.ITA/USD               | POST_MARKET | WARN     | no_benchmark_data        | 21   | 11  | 0   | 0   | 3         | 4      | mode=us-equities-post, no engine data in window      |
| 1246  | Equity.US.LLY/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 23   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1247  | Equity.US.LMT/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 25   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1257  | Equity.US.MA/USD                | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1281  | Equity.US.MNST/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 20   | 8   | 0   | 0   | 3         | 4      | 8 active candidates, 0 passed quality                |
| 1283  | Equity.US.MOH/USD               | REGULAR     | WARN     | candidates_fail_quality  | 19   | 16  | 0   | 0   | 3         | 4      | 16 active candidates, 0 passed quality               |
| 1329  | Equity.US.PANW/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1333  | Equity.US.PCAR/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 20   | 9   | 0   | 0   | 2         | 4      | 9 active candidates, 0 passed quality                |
| 1378  | Equity.US.ROP/USD               | POST_MARKET | WARN     | candidates_fail_quality  | 18   | 8   | 0   | 0   | 3         | 4      | 8 active candidates, 0 passed quality                |
| 1381  | Equity.US.RTX/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 25   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1390  | Equity.US.SLB/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 23   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1401  | Equity.US.STLD/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 20   | 9   | 0   | 0   | 3         | 4      | 9 active candidates, 0 passed quality                |
| 1410  | Equity.US.SYF/USD               | PRE_MARKET  | WARN     | candidates_fail_quality  | 20   | 8   | 0   | 0   | 3         | 4      | 8 active candidates, 0 passed quality                |
| 1410  | Equity.US.SYF/USD               | OVER_NIGHT  | WARN     | no_benchmark_data        | 24   | 6   | 0   | 0   | 3         | 4      | mode=us-equities-overnight, no engine data in window |
| 1415  | Equity.US.TDG/USD               | PRE_MARKET  | WARN     | candidates_fail_quality  | 21   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1415  | Equity.US.TDG/USD               | POST_MARKET | WARN     | no_benchmark_data        | 19   | 8   | 0   | 0   | 3         | 4      | mode=us-equities-post, no engine data in window      |
| 1416  | Equity.US.TDY/USD               | REGULAR     | WARN     | candidates_fail_quality  | 18   | 14  | 0   | 0   | 3         | 4      | 14 active candidates, 0 passed quality               |
| 1430  | Equity.US.TRGP/USD              | REGULAR     | WARN     | candidates_fail_quality  | 18   | 15  | 0   | 0   | 3         | 4      | 15 active candidates, 0 passed quality               |
| 1441  | Equity.US.TXN/USD               | POST_MARKET | WARN     | candidates_fail_quality  | 23   | 10  | 0   | 0   | 3         | 4      | 10 active candidates, 0 passed quality               |
| 1441  | Equity.US.TXN/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 23   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1445  | Equity.US.UBER/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1467  | Equity.US.V/USD                 | OVER_NIGHT  | WARN     | candidates_fail_quality  | 24   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1473  | Equity.US.VRSK/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 19   | 6   | 0   | 0   | 4         | 5      | 6 active candidates, 0 passed quality                |
| 1481  | Equity.US.WAT/USD               | REGULAR     | WARN     | candidates_fail_quality  | 18   | 14  | 0   | 0   | 3         | 4      | 14 active candidates, 0 passed quality               |
| 1484  | Equity.US.WDAY/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 20   | 9   | 0   | 0   | 3         | 4      | 9 active candidates, 0 passed quality                |
| 1493  | Equity.US.WST/USD               | REGULAR     | WARN     | candidates_fail_quality  | 18   | 14  | 0   | 0   | 3         | 4      | 14 active candidates, 0 passed quality               |
| 1499  | Equity.US.XOM/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 21   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 1510  | FX.USD/HKD                      | REGULAR     | WARN     | candidates_fail_quality  | 15   | 14  | 0   | 0   | 4         | 5      | 14 active candidates, 0 passed quality               |
| 1511  | FX.USD/IDR                      | REGULAR     | WARN     | no_benchmark_data        | 10   | 8   | 0   | 0   | 3         | 4      | mode=fx, no engine data in window                    |
| 1516  | FX.USD/PHP                      | REGULAR     | WARN     | candidates_fail_quality  | 7    | 5   | 0   | 0   | 4         | 5      | 5 active candidates, 0 passed quality                |
| 1523  | InterestRate.EFFR               | REGULAR     | WARN     | candidates_fail_quality  | 2    | 2   | 0   | 0   | 3         | 4      | 2 active candidates, 0 passed quality                |
| 1524  | InterestRate.OBFR               | REGULAR     | WARN     | candidates_fail_quality  | 2    | 2   | 0   | 0   | 3         | 4      | 2 active candidates, 0 passed quality                |
| 1558  | Crypto.CBXRP/USD                | REGULAR     | WARN     | candidates_fail_quality  | 2    | 2   | 0   | 0   | 3         | 4      | 2 active candidates, 0 passed quality                |
| 1577  | Crypto.PST/USDC.RR              | REGULAR     | WARN     | candidates_fail_quality  | 2    | 2   | 0   | 0   | 3         | 4      | 2 active candidates, 0 passed quality                |
| 1721  | Equity.US.NVO/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 21   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 1727  | Equity.US.SCCO/USD              | REGULAR     | WARN     | candidates_fail_quality  | 16   | 14  | 0   | 0   | 3         | 4      | 14 active candidates, 0 passed quality               |
| 1733  | Equity.US.SGML/USD              | REGULAR     | WARN     | candidates_fail_quality  | 15   | 13  | 0   | 0   | 3         | 4      | 13 active candidates, 0 passed quality               |
| 1764  | Equity.US.VT/USD                | OVER_NIGHT  | WARN     | candidates_fail_quality  | 19   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 1795  | Crypto.COINX/COIN.RR            | REGULAR     | WARN     | candidates_fail_quality  | 7    | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1797  | Crypto.CRCLX/CRCL.RR            | REGULAR     | WARN     | candidates_fail_quality  | 7    | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 1814  | Crypto.HOODX/HOOD.RR            | REGULAR     | WARN     | candidates_fail_quality  | 6    | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 2166  | Equity.KR.000660/KRW            | REGULAR     | WARN     | candidates_fail_quality  | 4    | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 2269  | Equity.US.AAL/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 20   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 2274  | Equity.US.BOTZ/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 20   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 2285  | Equity.US.ESLT/USD              | REGULAR     | WARN     | candidates_fail_quality  | 13   | 9   | 0   | 0   | 3         | 4      | 9 active candidates, 0 passed quality                |
| 2293  | Equity.US.NA/USD                | REGULAR     | WARN     | candidates_fail_quality  | 12   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 2302  | Equity.US.UFO/USD               | REGULAR     | WARN     | candidates_fail_quality  | 12   | 9   | 0   | 0   | 3         | 4      | 9 active candidates, 0 passed quality                |
| 2307  | FX.USDXY                        | REGULAR     | WARN     | candidates_fail_quality  | 2    | 2   | 0   | 0   | 3         | 4      | 2 active candidates, 0 passed quality                |
| 2349  | Crypto.VSUI/SUI.RR              | REGULAR     | WARN     | candidates_fail_quality  | 2    | 1   | 0   | 0   | 2         | 3      | 1 active candidates, 0 passed quality                |
| 2355  | Equity.US.CCJ/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 22   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 2362  | Equity.US.GENI/USD              | REGULAR     | WARN     | candidates_fail_quality  | 12   | 7   | 0   | 0   | 4         | 5      | 7 active candidates, 0 passed quality                |
| 2367  | Equity.US.NVD/USD               | REGULAR     | WARN     | candidates_fail_quality  | 9    | 5   | 0   | 0   | 4         | 5      | 5 active candidates, 0 passed quality                |
| 2374  | Equity.US.STKE/USD              | REGULAR     | WARN     | candidates_fail_quality  | 10   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 2379  | FX.EUR/DKK                      | REGULAR     | WARN     | candidates_fail_quality  | 10   | 8   | 0   | 0   | 4         | 5      | 8 active candidates, 0 passed quality                |
| 2421  | Equity.US.STRF/USD              | REGULAR     | WARN     | candidates_fail_quality  | 9    | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 2629  | FX.USD/MYR                      | REGULAR     | WARN     | no_benchmark_data        | 4    | 3   | 0   | 0   | 3         | 4      | mode=fx, no engine data in window                    |
| 2686  | Crypto.NFLXX/NFLX.RR            | REGULAR     | WARN     | candidates_fail_quality  | 5    | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 2702  | Equity.US.AAAU/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 21   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 2704  | Equity.US.AFRM/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 19   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 2705  | Equity.US.ALAB/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 16   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 2706  | Equity.US.APLD/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 18   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 2722  | Equity.US.BIDU/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 16   | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 2735  | Equity.US.CRDO/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 14   | 4   | 0   | 0   | 4         | 5      | 4 active candidates, 0 passed quality                |
| 2779  | Equity.US.GRAB/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 19   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 2798  | Equity.US.INDA/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 13   | 3   | 0   | 0   | 3         | 4      | 3 active candidates, 0 passed quality                |
| 2798  | Equity.US.INDA/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 16   | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 2835  | Equity.US.NVDX/USD              | REGULAR     | WARN     | candidates_fail_quality  | 10   | 5   | 0   | 0   | 5         | 5      | 5 active candidates, 0 passed quality                |
| 2860  | Equity.US.SNOW/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 10   | 5   | 0   | 0   | 4         | 5      | 5 active candidates, 0 passed quality                |
| 2869  | Equity.US.TCOM/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 16   | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 2911  | Equity.US.PURR/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 17   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 2914  | Equity.US.NIDU6/USD             | REGULAR     | WARN     | no_benchmark_data        | 3    | 2   | 0   | 0   | 2         | 3      | mode=us-equities, no engine data in window           |
| 2935  | Commodities.CCN6/USD            | REGULAR     | WARN     | no_benchmark_data        | 2    | 2   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 2943  | Equity.US.CPER/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 19   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 2981  | Commodities.PTV6/USD            | REGULAR     | WARN     | no_benchmark_data        | 2    | 2   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 2987  | Crypto.EXOD.SS/EXOD.RR          | REGULAR     | WARN     | candidates_fail_quality  | 5    | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 3048  | Equity.US.ONDS/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 17   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3052  | Commodities.COU6/USD            | REGULAR     | WARN     | no_benchmark_data        | 1    | 1   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3053  | Commodities.COZ6/USD            | REGULAR     | WARN     | no_benchmark_data        | 1    | 1   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3054  | Equity.US.KORU/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 16   | 7   | 0   | 0   | 5         | 4      | 7 active candidates, 0 passed quality                |
| 3055  | Equity.US.EWT/USD               | POST_MARKET | WARN     | candidates_fail_quality  | 15   | 6   | 0   | 0   | 4         | 5      | 6 active candidates, 0 passed quality                |
| 3063  | Commodities.Index.PYTHOIL/USD   | REGULAR     | WARN     | no_candidates            | 0    | 0   | 0   | 0   | 2         | 3      | 3 submitting, all allowed/excluded                   |
| 3081  | Commodities.WHZ6/USD            | REGULAR     | WARN     | no_benchmark_data        | 1    | 1   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3084  | Commodities.SOQ6/USD            | REGULAR     | WARN     | no_benchmark_data        | 2    | 2   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3085  | Commodities.SOU6/USD            | REGULAR     | WARN     | no_benchmark_data        | 2    | 2   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3091  | Commodities.TGEU6/EUR           | REGULAR     | WARN     | no_benchmark_data        | 2    | 2   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3092  | Commodities.TGEV6/EUR           | REGULAR     | WARN     | no_benchmark_data        | 2    | 2   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3142  | Equity.US.LUNR/USD              | OVER_NIGHT  | WARN     | no_benchmark_data        | 16   | 5   | 0   | 0   | 3         | 4      | mode=us-equities-overnight, no engine data in window |
| 3152  | Commodities.RSV6/USc            | REGULAR     | WARN     | no_benchmark_data        | 1    | 1   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3158  | Commodities.BLDV6/USD           | REGULAR     | WARN     | no_benchmark_data        | 2    | 2   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3162  | Crypto.Index.EACRED/USD         | REGULAR     | WARN     | candidates_fail_quality  | 1    | 1   | 0   | 0   | 3         | 4      | 1 active candidates, 0 passed quality                |
| 3163  | Equity.US.URNM/USD              | POST_MARKET | WARN     | no_benchmark_data        | 11   | 3   | 0   | 0   | 4         | 5      | mode=us-equities-post, no engine data in window      |
| 3167  | Equity.US.NTRA/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 9    | 4   | 0   | 0   | 4         | 5      | 4 active candidates, 0 passed quality                |
| 3167  | Equity.US.NTRA/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 9    | 4   | 0   | 0   | 4         | 5      | 4 active candidates, 0 passed quality                |
| 3168  | Equity.US.CASY/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 15   | 6   | 0   | 0   | 4         | 5      | 6 active candidates, 0 passed quality                |
| 3169  | Equity.US.CW/USD                | PRE_MARKET  | WARN     | candidates_fail_quality  | 16   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3169  | Equity.US.CW/USD                | POST_MARKET | WARN     | candidates_fail_quality  | 16   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3173  | Commodities.CAU6/USD            | REGULAR     | WARN     | no_candidates            | 0    | 0   | 0   | 0   | 2         | 3      | 4 submitting, all allowed/excluded                   |
| 3174  | Commodities.CAZ6/USD            | REGULAR     | WARN     | no_candidates            | 0    | 0   | 0   | 0   | 2         | 3      | 4 submitting, all allowed/excluded                   |
| 3178  | Crypto.Index.EXBTC/USD          | REGULAR     | WARN     | candidates_fail_activity | 1    | 0   | 0   | 0   | 3         | 4      | 1 candidates all below 0.9                           |
| 3179  | Crypto.Index.ETHIRD/USD         | REGULAR     | WARN     | candidates_fail_activity | 1    | 0   | 0   | 0   | 3         | 4      | 1 candidates all below 0.9                           |
| 3180  | Crypto.Index.ESUI/USD           | REGULAR     | WARN     | candidates_fail_activity | 1    | 0   | 0   | 0   | 3         | 4      | 1 candidates all below 0.9                           |
| 3181  | Crypto.Index.EGUSDC/USD         | REGULAR     | WARN     | candidates_fail_activity | 1    | 0   | 0   | 0   | 3         | 4      | 1 candidates all below 0.9                           |
| 3209  | Commodities.CFN6/USc            | REGULAR     | WARN     | no_benchmark_data        | 1    | 1   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3210  | Commodities.CFU6/USc            | REGULAR     | WARN     | no_benchmark_data        | 1    | 1   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3223  | Equity.US.URA/USD               | PRE_MARKET  | WARN     | candidates_fail_quality  | 13   | 3   | 0   | 0   | 3         | 4      | 3 active candidates, 0 passed quality                |
| 3226  | Equity.US.ERIC/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 11   | 3   | 0   | 0   | 3         | 4      | 3 active candidates, 0 passed quality                |
| 3228  | Equity.US.INSM/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 11   | 3   | 0   | 0   | 3         | 4      | 3 active candidates, 0 passed quality                |
| 3228  | Equity.US.INSM/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 11   | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 3229  | Equity.US.VOD/USD               | POST_MARKET | WARN     | candidates_fail_quality  | 12   | 3   | 0   | 0   | 3         | 4      | 3 active candidates, 0 passed quality                |
| 3230  | Equity.US.ZM/USD                | OVER_NIGHT  | WARN     | no_benchmark_data        | 16   | 4   | 0   | 0   | 3         | 4      | mode=us-equities-overnight, no engine data in window |
| 3231  | Equity.US.TRI/USD               | PRE_MARKET  | WARN     | candidates_fail_quality  | 11   | 3   | 0   | 0   | 3         | 4      | 3 active candidates, 0 passed quality                |
| 3236  | Equity.US.P/USD                 | REGULAR     | WARN     | candidates_fail_quality  | 11   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 3239  | Equity.US.MDLN/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 11   | 2   | 0   | 0   | 3         | 4      | 2 active candidates, 0 passed quality                |
| 3241  | Crypto.HEMIBTC/BTC.RR           | REGULAR     | WARN     | candidates_fail_activity | 1    | 0   | 0   | 0   | 4         | 5      | 1 candidates all below 0.9                           |
| 3247  | Commodities.NGDV6/USD           | REGULAR     | WARN     | no_benchmark_data        | 1    | 1   | 0   | 0   | 2         | 3      | mode=commodity, no engine data in window             |
| 3276  | Equity.US.RVMD/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 16   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 3277  | Equity.US.FLEX/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 15   | 5   | 0   | 0   | 4         | 5      | 5 active candidates, 0 passed quality                |
| 3278  | Equity.US.RGC/USD               | REGULAR     | WARN     | candidates_fail_quality  | 16   | 9   | 0   | 0   | 4         | 5      | 9 active candidates, 0 passed quality                |
| 3278  | Equity.US.RGC/USD               | PRE_MARKET  | WARN     | candidates_fail_quality  | 17   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3278  | Equity.US.RGC/USD               | POST_MARKET | WARN     | candidates_fail_quality  | 17   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 3279  | Equity.US.EDU/USD               | POST_MARKET | WARN     | no_benchmark_data        | 17   | 7   | 0   | 0   | 3         | 4      | mode=us-equities-post, no engine data in window      |
| 3280  | Equity.US.BILI/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 14   | 7   | 0   | 0   | 3         | 4      | 7 active candidates, 0 passed quality                |
| 3281  | Equity.US.RIV/USD               | REGULAR     | WARN     | candidates_fail_quality  | 12   | 6   | 0   | 0   | 4         | 5      | 6 active candidates, 0 passed quality                |
| 3284  | Equity.US.AVEX/USD              | REGULAR     | WARN     | candidates_fail_quality  | 14   | 9   | 0   | 0   | 4         | 5      | 9 active candidates, 0 passed quality                |
| 3289  | Equity.US.LOGI/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 16   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3293  | Equity.US.WOLF/USD              | REGULAR     | WARN     | candidates_fail_quality  | 12   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3296  | Equity.US.XPRO/USD              | REGULAR     | WARN     | candidates_fail_quality  | 12   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 3300  | Equity.US.LPTH/USD              | REGULAR     | WARN     | candidates_fail_quality  | 12   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3301  | Crypto.STRCX/STRC.RR            | REGULAR     | WARN     | candidates_fail_quality  | 3    | 3   | 0   | 0   | 3         | 4      | 3 active candidates, 0 passed quality                |
| 3303  | Equity.US.FLNC/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 15   | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 3311  | Equity.US.QNT/USD               | PRE_MARKET  | WARN     | candidates_fail_quality  | 10   | 2   | 0   | 0   | 4         | 5      | 2 active candidates, 0 passed quality                |
| 3311  | Equity.US.QNT/USD               | POST_MARKET | WARN     | candidates_fail_quality  | 10   | 2   | 0   | 0   | 4         | 5      | 2 active candidates, 0 passed quality                |
| 3312  | Equity.US.FDXF/USD              | REGULAR     | WARN     | candidates_fail_quality  | 9    | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 3313  | Equity.US.RVI/USD               | REGULAR     | WARN     | candidates_fail_quality  | 10   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3319  | Equity.US.MVLL/USD              | REGULAR     | WARN     | candidates_fail_quality  | 10   | 5   | 0   | 0   | 4         | 5      | 5 active candidates, 0 passed quality                |
| 3319  | Equity.US.MVLL/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 15   | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 3320  | Equity.US.TZA/USD               | REGULAR     | WARN     | candidates_fail_quality  | 12   | 5   | 0   | 0   | 4         | 5      | 5 active candidates, 0 passed quality                |
| 3320  | Equity.US.TZA/USD               | POST_MARKET | WARN     | candidates_fail_quality  | 12   | 3   | 0   | 0   | 4         | 5      | 3 active candidates, 0 passed quality                |
| 3322  | Crypto.AMZNX/AMZN.RR            | REGULAR     | WARN     | candidates_fail_quality  | 1    | 1   | 0   | 0   | 3         | 4      | 1 active candidates, 0 passed quality                |
| 3323  | Crypto.MSFTX/MSFT.RR            | REGULAR     | WARN     | candidates_fail_quality  | 1    | 1   | 0   | 0   | 3         | 4      | 1 active candidates, 0 passed quality                |
| 3324  | Crypto.NAV.USDM1/USD            | REGULAR     | WARN     | no_candidates            | 0    | 0   | 0   | 0   | 3         | 4      | 5 submitting, all allowed/excluded                   |
| 3342  | Equity.US.PENG/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 14   | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 3343  | Equity.US.NNE/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 15   | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 3351  | Equity.US.NU/USD                | OVER_NIGHT  | WARN     | candidates_fail_quality  | 15   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 3352  | Equity.US.CLSK/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 15   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 3354  | Equity.US.UMC/USD               | OVER_NIGHT  | WARN     | candidates_fail_quality  | 15   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 3355  | Equity.US.POET/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 14   | 6   | 0   | 0   | 3         | 4      | 6 active candidates, 0 passed quality                |
| 3357  | Equity.US.CIEN/USD              | OVER_NIGHT  | WARN     | candidates_fail_quality  | 14   | 5   | 0   | 0   | 3         | 4      | 5 active candidates, 0 passed quality                |
| 3365  | Equity.US.SATA/USD              | REGULAR     | WARN     | candidates_fail_quality  | 7    | 1   | 0   | 0   | 4         | 5      | 1 active candidates, 0 passed quality                |
| 3366  | Equity.US.WEN/USD               | REGULAR     | WARN     | candidates_fail_quality  | 6    | 1   | 0   | 0   | 4         | 5      | 1 active candidates, 0 passed quality                |
| 3374  | Equity.HK.0668/HKD              | REGULAR     | WARN     | no_candidates            | 0    | 0   | 0   | 0   | 3         | 4      | 6 submitting, all allowed/excluded                   |
| 3409  | Equity.US.ECHO/USD              | PRE_MARKET  | WARN     | candidates_fail_quality  | 9    | 1   | 0   | 0   | 3         | 4      | 1 active candidates, 0 passed quality                |
| 3409  | Equity.US.ECHO/USD              | POST_MARKET | WARN     | candidates_fail_quality  | 8    | 1   | 0   | 0   | 4         | 4      | 1 active candidates, 0 passed quality                |
| 3420  | Equity.US.BSP/USD               | REGULAR     | WARN     | candidates_fail_quality  | 7    | 3   | 0   | 0   | 4         | 5      | 3 active candidates, 0 passed quality                |
| 3421  | Equity.US.MBGL/USD              | REGULAR     | WARN     | candidates_fail_quality  | 8    | 4   | 0   | 0   | 3         | 4      | 4 active candidates, 0 passed quality                |
| 3422  | Equity.US.SECZ/USD              | REGULAR     | WARN     | candidates_fail_quality  | 6    | 2   | 0   | 0   | 5         | 5      | 2 active candidates, 0 passed quality                |
| 3427  | Crypto.VERONA/USD               | REGULAR     | WARN     | candidates_fail_activity | 2    | 0   | 0   | 0   | 3         | 4      | 2 candidates all below 0.9                           |
| 3436  | Equity.US.SHAZ/USD              | REGULAR     | WARN     | candidates_fail_quality  | 7    | 1   | 0   | 0   | 5         | 5      | 1 active candidates, 0 passed quality                |
