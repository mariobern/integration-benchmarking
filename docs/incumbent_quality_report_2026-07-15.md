# Incumbent Quality Report — 2026-07-15

Window 2026-07-08..2026-07-15 (UTC, end exclusive), config `lazer_new.json`, sweep with candidates
(`lazer_dq/incumbent_quality.py --include-candidates --audit-csv
output_csv/min_pub_audit_2026-07-06_2026-07-13.csv --workers 8`).

## 1. Headline

The sweep scored **53,851 publisher rows** across **2,537 feed-sessions**
(**1,661 unique feeds**, 0 feed-level failures): **20,072 incumbent** rows and
**33,779 candidate** rows.

| Verdict      |    ALL | incumbent | candidate |
| ------------ | -----: | --------: | --------: |
| PASS         | 19,996 |    11,001 |     8,995 |
| FAIL         | 19,352 |     6,266 |    13,086 |
| NO_DATA      | 13,205 |     2,222 |    10,983 |
| NO_BENCHMARK |  1,298 |       583 |       715 |

`flagged_incumbents.csv` has **22,157 rows** — every incumbent row that isn't
PASS (9,071 = 6,266 + 2,222 + 583) plus every failing candidate (13,086).

**1,348 feed-sessions** are audit-`OK` (i.e. currently meeting minPublishers
comfortably per the min_pub audit) yet have at least one failing incumbent —
these are the headline remediation candidates (Section 4) since they aren't
flagged by the min_pub pipeline at all.

Raw incumbent-FAIL totals are concentrated, not evenly spread: **the top 15
publishers (of ~70 with any incumbent rows) account for 5,244 of the 6,266
incumbent FAILs — 83.7%**. A handful of chronically-failing publishers, not a
broad quality problem across the incumbent population, drive most of the FAIL
count (Section 4).

## 2. Method

For every STABLE feed-session in `lazer_new.json`, `incumbent_quality.py`
scores each currently-allowed ("incumbent") publisher's window submissions
against a quality gate, using the DQ engine (`evaluate_feed_standalone`, path
`engine`: fx, metals, commodity, rates, US/HK/JP/KR/IN equities) or a peer
comparison against the feed's own aggregate (path `peer`: crypto, redemption
rate, funding rate, NAV, custom, and some non-US-market equity feeds). With
`--include-candidates`, non-allowed production-key publishers submitting in
the window are scored identically for direct comparison. This is
measure-only: no activity gate, no selection, no config mutation — it is a
census of quality, not a remediation action.

Caveats:

- **Peer-path circularity**: incumbents on the peer path are compared
  against an aggregate they themselves help produce; a dominant bad incumbent
  can partially self-validate. Accepted by design (same trade-off as
  candidate qualification in `qualify_candidates.py`).
- **Zero-range / flat-reference feeds**: feeds with no price variance in the
  window (e.g. some NAV feeds) can never pass the peer gate and instead
  return `NO_BENCHMARK`/`zero_range` — this is a benchmark-availability
  artifact, not evidence of bad quality (164 rows in this sweep, Section 6).
- **Engine benchmark date**: the DQ engine path resolves the benchmark date
  as the most recent weekday with engine data in the window (up to 3 tried),
  not the full window — a single-day snapshot, not a window average.
- **NO_DATA ≠ bad quality**: NO_DATA (13,205 rows, 24.5% of all rows) means
  silence or too few observations to score (`no_submissions`,
  `insufficient_obs`, `no_engine_row`), not a failed quality check. It is by
  far the dominant reason candidates don't come back with a verdict
  (10,983 of 13,205 NO_DATA rows are candidates).
- **Incumbents vs. candidates, price query**: incumbents are scored from
  `ACCEPTED` submissions with no key-type filter; candidates are
  production-key-only by discovery and scored from `ACCEPTED` +
  `UNAUTHORIZED`-rejected submissions, mirroring `qualify_candidates.py`.

## 3. Pass rates by asset type and path

Incumbents only (`publisher_role == incumbent`); `pass_rate_of_scored` =
`n_pass / (n_pass + n_fail)`, excluding NO_DATA/NO_BENCHMARK rows from the
denominator.

| asset_type             | quality_path |      n | n_pass | n_fail | n_no_data | n_no_benchmark | pass_rate_of_scored |
| ---------------------- | ------------ | -----: | -----: | -----: | --------: | -------------: | ------------------: |
| commodity              | engine       |    177 |      0 |      0 |         0 |            177 |                   — |
| equity                 | engine       | 14,608 |  6,809 |  5,777 |     1,809 |            213 |              0.5410 |
| fx                     | engine       |    357 |    181 |    101 |        34 |             41 |              0.6418 |
| metal                  | engine       |     59 |     10 |     24 |         2 |             23 |              0.2941 |
| crypto                 | peer         |  4,193 |  3,575 |    317 |       295 |              6 |              0.9186 |
| crypto-index           | peer         |     38 |     38 |      0 |         0 |              0 |              1.0000 |
| crypto-redemption-rate | peer         |    369 |    239 |     22 |        40 |             68 |              0.9157 |
| custom                 | peer         |     23 |      3 |      0 |         4 |             16 |              1.0000 |
| equity                 | peer         |    145 |     80 |      0 |        30 |             35 |              1.0000 |
| funding-rate           | peer         |     31 |     18 |     13 |         0 |              0 |              0.5806 |
| interest-rate          | peer         |     37 |     26 |      5 |         6 |              0 |              0.8387 |
| nav                    | peer         |     35 |     22 |      7 |         2 |              4 |              0.7586 |

Notes:

- **commodity/engine** is entirely `NO_BENCHMARK` (177/177) — no engine data
  resolved for these feed-sessions in the window (see Section 6).
- **equity/peer** (145 rows) is not US-equities-via-engine; it's the
  non-US-market equity feeds scored on the peer path.
- **metal/engine** has the lowest pass rate of any scored bucket (0.2941, on
  only 59 rows) — small sample, worth a closer look before drawing
  conclusions.

## 4. Incumbent FAIL concentration by publisher

Top 15 publishers by incumbent-FAIL row count, out of 6,266 total incumbent
FAILs. `share_of_all_incumbent_fails` = publisher's `n_fail` / 6,266.

| publisher_id | n_pass | n_fail | n_no_data | n_no_benchmark | share_of_all_incumbent_fails |
| -----------: | -----: | -----: | --------: | -------------: | ---------------------------: |
|           71 |    267 |    674 |         6 |              9 |                       0.1076 |
|           41 |    766 |    525 |         6 |             51 |                       0.0838 |
|           65 |    946 |    457 |        55 |             13 |                       0.0729 |
|           22 |    951 |    457 |        46 |             30 |                       0.0729 |
|           20 |    646 |    456 |        63 |             65 |                       0.0728 |
|           45 |    335 |    454 |        72 |             14 |                       0.0725 |
|           19 |    723 |    398 |        17 |             14 |                       0.0635 |
|           48 |    289 |    344 |        26 |             19 |                       0.0549 |
|           29 |    280 |    240 |       124 |             13 |                       0.0383 |
|           42 |    603 |    239 |       168 |             13 |                       0.0381 |
|           12 |    548 |    223 |         5 |             31 |                       0.0356 |
|           54 |    157 |    201 |        23 |              5 |                       0.0321 |
|           21 |    343 |    196 |        17 |             11 |                       0.0313 |
|           64 |      9 |    193 |         2 |              2 |                       0.0308 |
|           55 |     81 |    187 |        64 |              2 |                       0.0298 |

These 15 publishers hold **5,244 of 6,266 incumbent FAILs (83.7%)**.
Publisher 71 alone accounts for 10.8% of all incumbent FAILs across the
whole config (674 rows, against only 267 PASS on the feeds it's an incumbent
on — a materially worse pass rate than the incumbent population as a whole).
This is directly relevant to reading Section 5: a small number of "OK feeds
with failing incumbents" are driven by a repeat-offender publisher appearing
across many feeds, not by many different publishers each failing once.

## 5. OK feeds with failing incumbents

Summary rows where `audit_classification == "OK"` and `n_fail > 0`: **1,348
feed-sessions**. Full table in [Appendix A](#appendix-a-full-ok-feeds-with-failing-incumbents-table)
(sorted by `n_fail` desc); top 25 shown here.

| feed_id | symbol             | session | asset_type | quality_path | n_incumbents | n_pass | n_fail | n_no_data | n_no_benchmark | n_candidates | n_candidates_pass |
| ------: | ------------------ | ------- | ---------- | ------------ | -----------: | -----: | -----: | --------: | -------------: | -----------: | ----------------: |
|    1398 | Equity.US.SPY/USD  | REGULAR | equity     | engine       |           20 |      1 |     17 |         2 |              0 |           11 |                 0 |
|    1363 | Equity.US.QQQ/USD  | REGULAR | equity     | engine       |           22 |      3 |     17 |         2 |              0 |           10 |                 1 |
|    1314 | Equity.US.NVDA/USD | REGULAR | equity     | engine       |           23 |      4 |     16 |         3 |              0 |            9 |                 1 |
|    1745 | Equity.US.TQQQ/USD | REGULAR | equity     | engine       |           14 |      0 |     14 |         0 |              0 |           11 |                 0 |
|    1215 | Equity.US.IWM/USD  | REGULAR | equity     | engine       |           14 |      0 |     14 |         0 |              0 |           14 |                 1 |
|     922 | Equity.US.AAPL/USD | REGULAR | equity     | engine       |           22 |      5 |     14 |         3 |              0 |           11 |                 2 |
|     941 | Equity.US.AKAM/USD | REGULAR | equity     | engine       |           13 |      0 |     13 |         0 |              0 |           14 |                 0 |
|    1404 | Equity.US.STX/USD  | REGULAR | equity     | engine       |           13 |      0 |     13 |         0 |              0 |           15 |                 0 |
|    1738 | Equity.US.SOXS/USD | REGULAR | equity     | engine       |           13 |      0 |     13 |         0 |              0 |            7 |                 0 |
|    1143 | Equity.US.FSLR/USD | REGULAR | equity     | engine       |           12 |      0 |     12 |         0 |              0 |           13 |                 0 |
|     322 | FX.EUR/GBP         | REGULAR | fx         | engine       |           12 |      0 |     12 |         0 |              0 |            8 |                 1 |
|     345 | Metal.XAG/USD      | REGULAR | metal      | engine       |           13 |      0 |     12 |         1 |              0 |            7 |                 0 |
|    1304 | Equity.US.NFLX/USD | REGULAR | equity     | engine       |           20 |      7 |     12 |         1 |              0 |           11 |                 0 |
|    1359 | Equity.US.PTC/USD  | REGULAR | equity     | engine       |           12 |      0 |     12 |         0 |              0 |           13 |                 0 |
|    1504 | Equity.US.ZS/USD   | REGULAR | equity     | engine       |           13 |      0 |     12 |         1 |              0 |           11 |                 0 |
|    1448 | Equity.US.ULTA/USD | REGULAR | equity     | engine       |           12 |      0 |     12 |         0 |              0 |           14 |                 0 |
|    1098 | Equity.US.EEM/USD  | REGULAR | equity     | engine       |           16 |      5 |     11 |         0 |              0 |            8 |                 1 |
|    1311 | Equity.US.NTAP/USD | REGULAR | equity     | engine       |           12 |      1 |     11 |         0 |              0 |           13 |                 0 |
|     236 | Crypto.RLUSD/USD   | REGULAR | crypto     | peer         |           12 |      1 |     11 |         0 |              0 |            6 |                 0 |
|    3246 | Equity.US.CBRS/USD | REGULAR | equity     | engine       |           12 |      0 |     11 |         1 |              0 |           12 |                 0 |
|    1744 | Equity.US.SQQQ/USD | REGULAR | equity     | engine       |           13 |      2 |     11 |         0 |              0 |           12 |                 1 |
|    1099 | Equity.US.EFA/USD  | REGULAR | equity     | engine       |           16 |      5 |     11 |         0 |              0 |           10 |                 1 |
|    1070 | Equity.US.DDOG/USD | REGULAR | equity     | engine       |           12 |      0 |     11 |         1 |              0 |           17 |                 0 |
|    1704 | Equity.US.IWF/USD  | REGULAR | equity     | engine       |           12 |      0 |     11 |         1 |              0 |            8 |                 0 |
|    1292 | Equity.US.MSFT/USD | REGULAR | equity     | engine       |           22 |      9 |     11 |         2 |              0 |           11 |                 3 |

Note the pattern: high-`n_incumbents` liquid US equity feeds (SPY, QQQ, NVDA,
AAPL, MSFT) surface here because their large incumbent rosters give more
opportunities to fail the tight regular-session engine gate, even while
`min_pub_audit` sees them as comfortably `OK` on publisher count. This is
exactly the incumbent-quality blind spot the sweep exists to close.

## 6. Candidate bench

Feeds with at least one passing candidate (`n_candidates_pass > 0`):
**1,628 feed-sessions**, totaling **8,995 passing candidates** (this equals
the candidate PASS verdict count in Table 1 exactly — every passing
candidate row belongs to one of these feeds) out of 23,090 candidates
evaluated on those same feeds.

Top 20 by `n_candidates_pass`:

| feed_id | symbol           | session | asset_type | n_candidates | n_candidates_pass |
| ------: | ---------------- | ------- | ---------- | -----------: | ----------------: |
|     106 | Crypto.SNX/USD   | REGULAR | crypto     |           21 |                20 |
|      24 | Crypto.BCH/USD   | REGULAR | crypto     |           21 |                20 |
|      26 | Crypto.LTC/USD   | REGULAR | crypto     |           21 |                20 |
|     125 | Crypto.BAT/USD   | REGULAR | crypto     |           20 |                19 |
|      33 | Crypto.VET/USD   | REGULAR | crypto     |           20 |                19 |
|      65 | Crypto.AXS/USD   | REGULAR | crypto     |           20 |                19 |
|      32 | Crypto.POL/USD   | REGULAR | crypto     |           20 |                19 |
|      25 | Crypto.UNI/USD   | REGULAR | crypto     |           20 |                19 |
|      23 | Crypto.XLM/USD   | REGULAR | crypto     |           20 |                19 |
|      69 | Crypto.MANA/USD  | REGULAR | crypto     |           20 |                19 |
|      27 | Crypto.NEAR/USD  | REGULAR | crypto     |           20 |                19 |
|      46 | Crypto.INJ/USD   | REGULAR | crypto     |           20 |                19 |
|      22 | Crypto.DOT/USD   | REGULAR | crypto     |           21 |                19 |
|      20 | Crypto.SHIB/USD  | REGULAR | crypto     |           20 |                19 |
|      44 | Crypto.ATOM/USD  | REGULAR | crypto     |           20 |                19 |
|     165 | Crypto.COMP/USD  | REGULAR | crypto     |           20 |                19 |
|      82 | Crypto.CRV/USD   | REGULAR | crypto     |           20 |                19 |
|      86 | Crypto.ENS/USD   | REGULAR | crypto     |           20 |                19 |
|     150 | Crypto.1INCH/USD | REGULAR | crypto     |           19 |                18 |
|      47 | Crypto.GRT/USD   | REGULAR | crypto     |           19 |                18 |

The candidate bench is overwhelmingly a crypto phenomenon — the peer-path
gate on liquid crypto feeds with dozens of production-key submitters passes
most of them. This is a discovery signal for `qualify_candidates.py`, not an
automatic promotion list.

## 7. Unmeasurable inventory

`NO_DATA` / `NO_BENCHMARK` rows in `incumbent_report.csv`, by reason (all
roles combined):

| verdict      | reason            | count |
| ------------ | ----------------- | ----: |
| NO_BENCHMARK | no_engine_data    | 1,077 |
| NO_BENCHMARK | zero_range        |   164 |
| NO_BENCHMARK | no_aggregate_data |    57 |
| NO_DATA      | no_engine_row     | 9,510 |
| NO_DATA      | insufficient_obs  | 2,951 |
| NO_DATA      | no_submissions    |   744 |

`no_engine_row` (9,510) dominates NO_DATA and is almost entirely candidates
on the engine path with no engine per-publisher row for the resolved
benchmark date — expected given candidates are non-allowed, often
low-volume, publishers. `no_engine_data` (1,077, all NO_BENCHMARK) means the
DQ engine itself produced nothing for that feed-session's benchmark date
(e.g. the entire `commodity/engine` bucket in Section 3). `zero_range` (164)
is the flat-reference-feed caveat from Section 2 — a benchmark-availability
artifact, not a quality signal.

---

## Appendix A: full OK-feeds-with-failing-incumbents table

Same rows as Section 5, all 1,348, sorted by `n_fail` desc.

| feed_id | symbol                       | session     | asset_type             | quality_path | n_incumbents | n_pass | n_fail | n_no_data | n_no_benchmark | n_candidates | n_candidates_pass |
| ------: | ---------------------------- | ----------- | ---------------------- | ------------ | -----------: | -----: | -----: | --------: | -------------: | -----------: | ----------------: |
|    1398 | Equity.US.SPY/USD            | REGULAR     | equity                 | engine       |           20 |      1 |     17 |         2 |              0 |           11 |                 0 |
|    1363 | Equity.US.QQQ/USD            | REGULAR     | equity                 | engine       |           22 |      3 |     17 |         2 |              0 |           10 |                 1 |
|    1314 | Equity.US.NVDA/USD           | REGULAR     | equity                 | engine       |           23 |      4 |     16 |         3 |              0 |            9 |                 1 |
|    1745 | Equity.US.TQQQ/USD           | REGULAR     | equity                 | engine       |           14 |      0 |     14 |         0 |              0 |           11 |                 0 |
|    1215 | Equity.US.IWM/USD            | REGULAR     | equity                 | engine       |           14 |      0 |     14 |         0 |              0 |           14 |                 1 |
|     922 | Equity.US.AAPL/USD           | REGULAR     | equity                 | engine       |           22 |      5 |     14 |         3 |              0 |           11 |                 2 |
|     941 | Equity.US.AKAM/USD           | REGULAR     | equity                 | engine       |           13 |      0 |     13 |         0 |              0 |           14 |                 0 |
|    1404 | Equity.US.STX/USD            | REGULAR     | equity                 | engine       |           13 |      0 |     13 |         0 |              0 |           15 |                 0 |
|    1738 | Equity.US.SOXS/USD           | REGULAR     | equity                 | engine       |           13 |      0 |     13 |         0 |              0 |            7 |                 0 |
|    1143 | Equity.US.FSLR/USD           | REGULAR     | equity                 | engine       |           12 |      0 |     12 |         0 |              0 |           13 |                 0 |
|     322 | FX.EUR/GBP                   | REGULAR     | fx                     | engine       |           12 |      0 |     12 |         0 |              0 |            8 |                 1 |
|     345 | Metal.XAG/USD                | REGULAR     | metal                  | engine       |           13 |      0 |     12 |         1 |              0 |            7 |                 0 |
|    1304 | Equity.US.NFLX/USD           | REGULAR     | equity                 | engine       |           20 |      7 |     12 |         1 |              0 |           11 |                 0 |
|    1359 | Equity.US.PTC/USD            | REGULAR     | equity                 | engine       |           12 |      0 |     12 |         0 |              0 |           13 |                 0 |
|    1504 | Equity.US.ZS/USD             | REGULAR     | equity                 | engine       |           13 |      0 |     12 |         1 |              0 |           11 |                 0 |
|    1448 | Equity.US.ULTA/USD           | REGULAR     | equity                 | engine       |           12 |      0 |     12 |         0 |              0 |           14 |                 0 |
|    1098 | Equity.US.EEM/USD            | REGULAR     | equity                 | engine       |           16 |      5 |     11 |         0 |              0 |            8 |                 1 |
|    1311 | Equity.US.NTAP/USD           | REGULAR     | equity                 | engine       |           12 |      1 |     11 |         0 |              0 |           13 |                 0 |
|     236 | Crypto.RLUSD/USD             | REGULAR     | crypto                 | peer         |           12 |      1 |     11 |         0 |              0 |            6 |                 0 |
|    3246 | Equity.US.CBRS/USD           | REGULAR     | equity                 | engine       |           12 |      0 |     11 |         1 |              0 |           12 |                 0 |
|    1744 | Equity.US.SQQQ/USD           | REGULAR     | equity                 | engine       |           13 |      2 |     11 |         0 |              0 |           12 |                 1 |
|    1099 | Equity.US.EFA/USD            | REGULAR     | equity                 | engine       |           16 |      5 |     11 |         0 |              0 |           10 |                 1 |
|    1070 | Equity.US.DDOG/USD           | REGULAR     | equity                 | engine       |           12 |      0 |     11 |         1 |              0 |           17 |                 0 |
|    1704 | Equity.US.IWF/USD            | REGULAR     | equity                 | engine       |           12 |      0 |     11 |         1 |              0 |            8 |                 0 |
|    1292 | Equity.US.MSFT/USD           | REGULAR     | equity                 | engine       |           22 |      9 |     11 |         2 |              0 |           11 |                 3 |
|    1272 | Equity.US.META/USD           | POST_MARKET | equity                 | engine       |           11 |      0 |     10 |         1 |              0 |           20 |                 1 |
|    1267 | Equity.US.MDB/USD            | REGULAR     | equity                 | engine       |           11 |      0 |     10 |         1 |              0 |           14 |                 0 |
|    1383 | Equity.US.SBAC/USD           | REGULAR     | equity                 | engine       |           10 |      0 |     10 |         0 |              0 |           15 |                 0 |
|    1006 | Equity.US.BWA/USD            | REGULAR     | equity                 | engine       |           10 |      0 |     10 |         0 |              0 |           12 |                 0 |
|    1518 | FX.USD/TRY                   | REGULAR     | fx                     | engine       |           10 |      0 |     10 |         0 |              0 |            9 |                 0 |
|    1163 | Equity.US.GOOGL/USD          | POST_MARKET | equity                 | engine       |           11 |      0 |     10 |         1 |              0 |           21 |                 0 |
|    1452 | Equity.US.UPST/USD           | PRE_MARKET  | equity                 | engine       |           14 |      0 |     10 |         4 |              0 |           14 |                 0 |
|    1373 | Equity.US.RKLB/USD           | POST_MARKET | equity                 | engine       |           10 |      0 |     10 |         0 |              0 |           18 |                 0 |
|    1503 | Equity.US.ZBRA/USD           | REGULAR     | equity                 | engine       |           10 |      0 |     10 |         0 |              0 |           13 |                 0 |
|    1286 | Equity.US.MPWR/USD           | REGULAR     | equity                 | engine       |           10 |      0 |     10 |         0 |              0 |           15 |                 0 |
|    1474 | Equity.US.VRSN/USD           | REGULAR     | equity                 | engine       |           11 |      0 |     10 |         1 |              0 |           12 |                 0 |
|    1286 | Equity.US.MPWR/USD           | PRE_MARKET  | equity                 | engine       |           11 |      0 |     10 |         1 |              0 |           14 |                 0 |
|    1504 | Equity.US.ZS/USD             | PRE_MARKET  | equity                 | engine       |           12 |      0 |     10 |         2 |              0 |           12 |                 0 |
|    1067 | Equity.US.DASH/USD           | REGULAR     | equity                 | engine       |           12 |      0 |     10 |         2 |              0 |           16 |                 0 |
|    1395 | Equity.US.SOLV/USD           | REGULAR     | equity                 | engine       |           11 |      0 |     10 |         1 |              0 |           13 |                 0 |
|    1069 | Equity.US.DD/USD             | REGULAR     | equity                 | engine       |           11 |      0 |     10 |         1 |              0 |           13 |                 0 |
|    1420 | Equity.US.TER/USD            | REGULAR     | equity                 | engine       |           10 |      0 |     10 |         0 |              0 |           16 |                 0 |
|    1378 | Equity.US.ROP/USD            | REGULAR     | equity                 | engine       |           10 |      0 |     10 |         0 |              0 |           15 |                 0 |
|    1042 | Equity.US.COIN/USD           | REGULAR     | equity                 | engine       |           18 |      7 |     10 |         1 |              0 |           13 |                 3 |
|    1351 | Equity.US.PODD/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           19 |                 0 |
|    2762 | Equity.US.EZU/USD            | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |            8 |                 0 |
|    1260 | Equity.US.MARA/USD           | POST_MARKET | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           19 |                 0 |
|    1404 | Equity.US.STX/USD            | POST_MARKET | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           19 |                 0 |
|    1260 | Equity.US.MARA/USD           | PRE_MARKET  | equity                 | engine       |           12 |      0 |      9 |         3 |              0 |           16 |                 0 |
|    1215 | Equity.US.IWM/USD            | PRE_MARKET  | equity                 | engine       |           11 |      0 |      9 |         2 |              0 |           17 |                 0 |
|    1243 | Equity.US.LII/USD            | REGULAR     | equity                 | engine       |           10 |      0 |      9 |         1 |              0 |           14 |                 0 |
|    1346 | Equity.US.PLTR/USD           | REGULAR     | equity                 | engine       |           19 |      9 |      9 |         1 |              0 |           11 |                 2 |
|     988 | Equity.US.BIIB/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           17 |                 0 |
|    1361 | Equity.US.PYPL/USD           | PRE_MARKET  | equity                 | engine       |           13 |      1 |      9 |         3 |              0 |           15 |                 0 |
|    1110 | Equity.US.EQIX/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           17 |                 0 |
|     977 | Equity.US.AZN/USD            | REGULAR     | equity                 | engine       |           14 |      5 |      9 |         0 |              0 |           14 |                 2 |
|    1775 | Equity.US.XLK/USD            | REGULAR     | equity                 | engine       |           11 |      2 |      9 |         0 |              0 |           14 |                 0 |
|    1215 | Equity.US.IWM/USD            | POST_MARKET | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           19 |                 0 |
|    1156 | Equity.US.GL/USD             | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           16 |                 0 |
|    1484 | Equity.US.WDAY/USD           | REGULAR     | equity                 | engine       |           10 |      0 |      9 |         1 |              0 |           16 |                 0 |
|    1109 | Equity.US.EPAM/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           17 |                 0 |
|    1153 | Equity.US.GFS/USD            | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           15 |                 0 |
|    1251 | Equity.US.LULU/USD           | POST_MARKET | equity                 | engine       |           13 |      2 |      9 |         2 |              0 |           12 |                 0 |
|    1251 | Equity.US.LULU/USD           | PRE_MARKET  | equity                 | engine       |           12 |      0 |      9 |         3 |              0 |           14 |                 0 |
|       7 | Crypto.USDC/USD              | REGULAR     | crypto                 | peer         |           13 |      3 |      9 |         1 |              0 |           17 |                 0 |
|     232 | Crypto.USDG/USD              | REGULAR     | crypto                 | peer         |           14 |      3 |      9 |         2 |              0 |            7 |                 0 |
|    1227 | Equity.US.KEYS/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           15 |                 0 |
|    1466 | Equity.US.USO/USD            | PRE_MARKET  | equity                 | engine       |           11 |      0 |      9 |         2 |              0 |           17 |                 0 |
|    1472 | Equity.US.VOO/USD            | POST_MARKET | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           20 |                 0 |
|    1267 | Equity.US.MDB/USD            | PRE_MARKET  | equity                 | engine       |           10 |      0 |      9 |         1 |              0 |           14 |                 0 |
|     947 | Equity.US.AMC/USD            | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           16 |                 0 |
|    1074 | Equity.US.DELL/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      9 |         0 |              0 |           19 |                 0 |
|    1472 | Equity.US.VOO/USD            | PRE_MARKET  | equity                 | engine       |           10 |      0 |      9 |         1 |              0 |           19 |                 0 |
|    1472 | Equity.US.VOO/USD            | REGULAR     | equity                 | engine       |           15 |      6 |      9 |         0 |              0 |           14 |                 1 |
|    1723 | Equity.US.QQQM/USD           | REGULAR     | equity                 | engine       |           11 |      2 |      9 |         0 |              0 |           15 |                 3 |
|    1080 | Equity.US.DIA/USD            | REGULAR     | equity                 | engine       |           14 |      4 |      9 |         1 |              0 |           14 |                 1 |
|    1087 | Equity.US.DPZ/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           17 |                 0 |
|    1466 | Equity.US.USO/USD            | POST_MARKET | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           20 |                 0 |
|    2288 | Equity.US.GLXY/USD           | PRE_MARKET  | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           17 |                 0 |
|    3067 | Equity.US.UAE/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |            9 |                 0 |
|    1190 | Equity.US.HUM/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           17 |                 0 |
|    1776 | Equity.US.XLV/USD            | REGULAR     | equity                 | engine       |           11 |      3 |      8 |         0 |              0 |            9 |                 0 |
|    1193 | Equity.US.IAU/USD            | REGULAR     | equity                 | engine       |           14 |      6 |      8 |         0 |              0 |           14 |                 1 |
|    1390 | Equity.US.SLB/USD            | PRE_MARKET  | equity                 | engine       |           10 |      1 |      8 |         1 |              0 |           18 |                 1 |
|     945 | Equity.US.ALLE/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           17 |                 0 |
|    1338 | Equity.US.PFE/USD            | REGULAR     | equity                 | engine       |           16 |      8 |      8 |         0 |              0 |            9 |                 4 |
|    1771 | Equity.US.VXUS/USD           | REGULAR     | equity                 | engine       |           13 |      5 |      8 |         0 |              0 |            7 |                 1 |
|    1744 | Equity.US.SQQQ/USD           | PRE_MARKET  | equity                 | engine       |           10 |      0 |      8 |         2 |              0 |           15 |                 0 |
|     954 | Equity.US.AMZN/USD           | REGULAR     | equity                 | engine       |           22 |     10 |      8 |         4 |              0 |           12 |                 3 |
|    2864 | Equity.US.SPOT/USD           | POST_MARKET | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           14 |                 1 |
|    1183 | Equity.US.HPE/USD            | PRE_MARKET  | equity                 | engine       |           12 |      0 |      8 |         4 |              0 |           16 |                 1 |
|    3066 | Equity.US.PAYP/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           12 |                 0 |
|    1127 | Equity.US.FANG/USD           | PRE_MARKET  | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           16 |                 0 |
|    1036 | Equity.US.CMG/USD            | REGULAR     | equity                 | engine       |           14 |      5 |      8 |         1 |              0 |            9 |                 1 |
|    1136 | Equity.US.FICO/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           16 |                 0 |
|    1123 | Equity.US.EXPE/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           18 |                 0 |
|    2355 | Equity.US.CCJ/USD            | PRE_MARKET  | equity                 | engine       |           10 |      0 |      8 |         2 |              0 |           16 |                 1 |
|    2355 | Equity.US.CCJ/USD            | POST_MARKET | equity                 | engine       |           11 |      2 |      8 |         1 |              0 |           15 |                 2 |
|    3150 | Equity.US.BWET/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           10 |                 0 |
|    1022 | Equity.US.CDW/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           17 |                 0 |
|    1435 | Equity.US.TSLA/USD           | POST_MARKET | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           22 |                 0 |
|    1080 | Equity.US.DIA/USD            | PRE_MARKET  | equity                 | engine       |           12 |      0 |      8 |         4 |              0 |           16 |                 0 |
|    1149 | Equity.US.GE/USD             | PRE_MARKET  | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           18 |                 0 |
|    2288 | Equity.US.GLXY/USD           | POST_MARKET | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           17 |                 1 |
|    2364 | Equity.US.JD/USD             | PRE_MARKET  | equity                 | engine       |           12 |      1 |      8 |         3 |              0 |           13 |                 0 |
|    1371 | Equity.US.RIOT/USD           | REGULAR     | equity                 | engine       |           10 |      2 |      8 |         0 |              0 |           14 |                 1 |
|    1157 | Equity.US.GLD/USD            | PRE_MARKET  | equity                 | engine       |           10 |      0 |      8 |         2 |              0 |           20 |                 0 |
|    1163 | Equity.US.GOOGL/USD          | REGULAR     | equity                 | engine       |           21 |     11 |      8 |         2 |              0 |           12 |                 3 |
|    1150 | Equity.US.GEHC/USD           | PRE_MARKET  | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           16 |                 0 |
|     980 | Equity.US.BAC/USD            | REGULAR     | equity                 | engine       |           10 |      2 |      8 |         0 |              0 |           19 |                 0 |
|    1116 | Equity.US.ETN/USD            | PRE_MARKET  | equity                 | engine       |           11 |      0 |      8 |         3 |              0 |           18 |                 0 |
|    1162 | Equity.US.GOOG/USD           | REGULAR     | equity                 | engine       |           14 |      6 |      8 |         0 |              0 |           14 |                 7 |
|     975 | Equity.US.AXON/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           18 |                 0 |
|    1352 | Equity.US.POOL/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           17 |                 0 |
|    2375 | Equity.US.TEM/USD            | REGULAR     | equity                 | engine       |           10 |      0 |      8 |         2 |              0 |           13 |                 0 |
|    1100 | Equity.US.EFX/USD            | REGULAR     | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           16 |                 0 |
|    2375 | Equity.US.TEM/USD            | POST_MARKET | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           13 |                 0 |
|    1391 | Equity.US.SMCI/USD           | REGULAR     | equity                 | engine       |           15 |      7 |      8 |         0 |              0 |           13 |                 1 |
|     924 | Equity.US.ABNB/USD           | REGULAR     | equity                 | engine       |           16 |      8 |      8 |         0 |              0 |           13 |                 3 |
|    1737 | Equity.US.SNAP/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           12 |                 0 |
|    1241 | Equity.US.LH/USD             | REGULAR     | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           15 |                 0 |
|    1508 | FX.USD/CNH                   | REGULAR     | fx                     | engine       |           10 |      0 |      8 |         2 |              0 |           12 |                 0 |
|    1318 | Equity.US.NXPI/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           18 |                 0 |
|    1513 | FX.USD/KRW                   | REGULAR     | fx                     | engine       |            8 |      0 |      8 |         0 |              0 |            8 |                 0 |
|    1304 | Equity.US.NFLX/USD           | POST_MARKET | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           22 |                 0 |
|    1303 | Equity.US.NEM/USD            | PRE_MARKET  | equity                 | engine       |           14 |      3 |      8 |         3 |              0 |           14 |                 1 |
|     342 | FX.USD/SGD                   | REGULAR     | fx                     | engine       |            9 |      1 |      8 |         0 |              0 |           13 |                 1 |
|    1220 | Equity.US.JKHY/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           17 |                 0 |
|    2731 | Equity.US.CELH/USD           | POST_MARKET | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           15 |                 0 |
|    1708 | Equity.US.JEPQ/USD           | REGULAR     | equity                 | engine       |           14 |      6 |      8 |         0 |              0 |           10 |                 0 |
|    1208 | Equity.US.IRM/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           17 |                 0 |
|    1234 | Equity.US.KMX/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           16 |                 0 |
|    1327 | Equity.US.OXY/USD            | POST_MARKET | equity                 | engine       |           13 |      3 |      8 |         2 |              0 |           15 |                 1 |
|    1725 | Equity.US.RSP/USD            | REGULAR     | equity                 | engine       |            9 |      0 |      8 |         1 |              0 |           14 |                 0 |
|    1213 | Equity.US.IVV/USD            | REGULAR     | equity                 | engine       |           14 |      5 |      8 |         1 |              0 |           12 |                 0 |
|    2714 | Equity.US.AVAV/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      8 |         0 |              0 |           15 |                 0 |
|    2769 | Equity.US.FLUT/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           16 |                 0 |
|    3343 | Equity.US.NNE/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           12 |                 0 |
|    1007 | Equity.US.BX/USD             | PRE_MARKET  | equity                 | engine       |           10 |      0 |      7 |         3 |              0 |           18 |                 2 |
|    3362 | Equity.US.HONA/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |            7 |                 0 |
|     367 | Crypto.AUSD/USD              | REGULAR     | crypto                 | peer         |            8 |      1 |      7 |         0 |              0 |            4 |                 0 |
|     156 | Crypto.PYUSD/USD             | REGULAR     | crypto                 | peer         |           10 |      1 |      7 |         2 |              0 |           17 |                 0 |
|    1272 | Equity.US.META/USD           | REGULAR     | equity                 | engine       |           23 |     14 |      7 |         2 |              0 |           10 |                 4 |
|    1025 | Equity.US.CF/USD             | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    3342 | Equity.US.PENG/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           12 |                 0 |
|    1148 | Equity.US.GDDY/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 0 |
|    1029 | Equity.US.CHTR/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 0 |
|    2771 | Equity.US.FUTU/USD           | PRE_MARKET  | equity                 | engine       |            9 |      0 |      7 |         2 |              0 |           12 |                 0 |
|    1142 | Equity.US.FRT/USD            | REGULAR     | equity                 | engine       |            8 |      1 |      7 |         0 |              0 |           17 |                 0 |
|    1083 | Equity.US.DLTR/USD           | REGULAR     | equity                 | engine       |           14 |      7 |      7 |         0 |              0 |           11 |                 1 |
|    3346 | Equity.US.INOD/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           12 |                 0 |
|    3163 | Equity.US.URNM/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      7 |         2 |              0 |           10 |                 0 |
|    2928 | Equity.US.NLR/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 0 |
|    3344 | Equity.US.ELF/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           12 |                 0 |
|    1161 | Equity.US.GNRC/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 0 |
|    1484 | Equity.US.WDAY/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 2 |
|    3357 | Equity.US.CIEN/USD           | REGULAR     | equity                 | engine       |           10 |      0 |      7 |         3 |              0 |           11 |                 0 |
|    1002 | Equity.US.BSX/USD            | REGULAR     | equity                 | engine       |           16 |      9 |      7 |         0 |              0 |           10 |                 1 |
|    1239 | Equity.US.LDOS/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           16 |                 0 |
|    2942 | Equity.US.BTGO/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    1085 | Equity.US.DOV/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           16 |                 0 |
|     995 | Equity.US.BLK/USD            | REGULAR     | equity                 | engine       |           12 |      5 |      7 |         0 |              0 |           18 |                 3 |
|    1004 | Equity.US.BTCW/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           13 |                 0 |
|    3168 | Equity.US.CASY/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           14 |                 1 |
|     996 | Equity.US.BMY/USD            | REGULAR     | equity                 | engine       |           17 |     10 |      7 |         0 |              0 |            9 |                 2 |
|    3142 | Equity.US.LUNR/USD           | PRE_MARKET  | equity                 | engine       |           10 |      0 |      7 |         3 |              0 |           10 |                 2 |
|    2928 | Equity.US.NLR/USD            | PRE_MARKET  | equity                 | engine       |           10 |      0 |      7 |         3 |              0 |           14 |                 0 |
|    1401 | Equity.US.STLD/USD           | REGULAR     | equity                 | engine       |            8 |      1 |      7 |         0 |              0 |           17 |                 0 |
|    3345 | Equity.US.MXL/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           12 |                 0 |
|    1292 | Equity.US.MSFT/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           24 |                 0 |
|    1270 | Equity.US.MELI/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 3 |
|    1388 | Equity.US.SIVR/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           20 |                 0 |
|    1409 | Equity.US.SWKS/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 0 |
|    1398 | Equity.US.SPY/USD            | PRE_MARKET  | equity                 | engine       |           11 |      0 |      7 |         4 |              0 |           20 |                 0 |
|    1078 | Equity.US.DHI/USD            | REGULAR     | equity                 | engine       |           13 |      6 |      7 |         0 |              0 |           12 |                 1 |
|    2313 | Crypto.USDH/USD              | REGULAR     | crypto                 | peer         |            7 |      0 |      7 |         0 |              0 |            3 |                 0 |
|    1404 | Equity.US.STX/USD            | PRE_MARKET  | equity                 | engine       |           12 |      2 |      7 |         3 |              0 |           16 |                 0 |
|    1107 | Equity.US.ENPH/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    2944 | Equity.US.EWY/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    1417 | Equity.US.TEAM/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           16 |                 0 |
|    1417 | Equity.US.TEAM/USD           | PRE_MARKET  | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           16 |                 0 |
|    1113 | Equity.US.ERIE/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    1057 | Equity.US.CSX/USD            | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 2 |
|    1379 | Equity.US.ROST/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|     204 | Crypto.USDE/USD              | REGULAR     | crypto                 | peer         |            9 |      2 |      7 |         0 |              0 |           16 |                 0 |
|    1070 | Equity.US.DDOG/USD           | PRE_MARKET  | equity                 | engine       |           11 |      0 |      7 |         4 |              0 |           18 |                 0 |
|    1420 | Equity.US.TER/USD            | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 1 |
|    1050 | Equity.US.CPRT/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 3 |
|    2998 | Crypto.SUIUSDE/USD           | REGULAR     | crypto                 | peer         |            7 |      0 |      7 |         0 |              0 |            1 |                 0 |
|    1298 | Equity.US.MU/USD             | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           22 |                 1 |
|    3348 | Equity.US.TSEM/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           12 |                 0 |
|    2357 | Equity.US.FIGR/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           10 |                 0 |
|     582 | Crypto.SUSDE/USD             | REGULAR     | crypto                 | peer         |            7 |      0 |      7 |         0 |              0 |            2 |                 0 |
|    1312 | Equity.US.NTRS/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 0 |
|    1131 | Equity.US.FDS/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 0 |
|    1425 | Equity.US.TLT/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           21 |                 0 |
|    1037 | Equity.US.CMI/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 0 |
|    1134 | Equity.US.FFIV/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           18 |                 0 |
|    1169 | Equity.US.GWW/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 0 |
|    1001 | Equity.US.BRRR/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           17 |                 0 |
|     994 | Equity.US.BLDR/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           17 |                 0 |
|    2864 | Equity.US.SPOT/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           15 |                 0 |
|    1189 | Equity.US.HUBB/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           15 |                 0 |
|    1194 | Equity.US.IBIT/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 0 |
|    3277 | Equity.US.FLEX/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           15 |                 0 |
|     611 | Crypto.USDS/USD              | REGULAR     | crypto                 | peer         |            8 |      1 |      7 |         0 |              0 |            9 |                 1 |
|    2779 | Equity.US.GRAB/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           16 |                 0 |
|    2773 | Equity.US.GDX/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           13 |                 0 |
|    1314 | Equity.US.NVDA/USD           | POST_MARKET | equity                 | engine       |            9 |      0 |      7 |         2 |              0 |           22 |                 0 |
|    1237 | Equity.US.KVUE/USD           | REGULAR     | equity                 | engine       |           16 |      8 |      7 |         1 |              0 |            7 |                 1 |
|    3285 | Equity.US.AEHR/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           13 |                 0 |
|    2408 | Equity.US.BNKK/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      7 |         2 |              0 |            9 |                 0 |
|    2853 | Equity.US.SLV/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 0 |
|    3285 | Equity.US.AEHR/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           14 |                 0 |
|     968 | Equity.US.ARM/USD            | REGULAR     | equity                 | engine       |           10 |      3 |      7 |         0 |              0 |           20 |                 0 |
|     967 | Equity.US.ARKK/USD           | REGULAR     | equity                 | engine       |           12 |      5 |      7 |         0 |              0 |           18 |                 1 |
|     898 | Equity.HK.1044/HKD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |            3 |                 1 |
|    2410 | Equity.US.BYND/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    2650 | FX.USD/THB                   | REGULAR     | fx                     | engine       |            8 |      0 |      7 |         1 |              0 |            9 |                 0 |
|     951 | Equity.US.AMGN/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           20 |                 1 |
|     942 | Equity.US.ALB/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           20 |                 0 |
|     932 | Equity.US.ADSK/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|     931 | Equity.US.ADP/USD            | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    1202 | Equity.US.INTU/USD           | POST_MARKET | equity                 | engine       |            9 |      1 |      7 |         1 |              0 |           19 |                 3 |
|    1766 | Equity.US.VTI/USD            | REGULAR     | equity                 | engine       |           12 |      5 |      7 |         0 |              0 |            8 |                 0 |
|    1329 | Equity.US.PANW/USD           | REGULAR     | equity                 | engine       |           13 |      6 |      7 |         0 |              0 |           16 |                 4 |
|     924 | Equity.US.ABNB/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           22 |                 0 |
|    2640 | FX.USD/RON                   | REGULAR     | fx                     | engine       |            7 |      0 |      7 |         0 |              0 |            5 |                 0 |
|    1198 | Equity.US.IEX/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 0 |
|    1327 | Equity.US.OXY/USD            | REGULAR     | equity                 | engine       |           19 |     11 |      7 |         1 |              0 |            9 |                 1 |
|    1197 | Equity.US.IDXX/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           16 |                 0 |
|    1216 | Equity.US.J/USD              | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           17 |                 0 |
|    1476 | Equity.US.VST/USD            | POST_MARKET | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           18 |                 0 |
|    1335 | Equity.US.PDD/USD            | POST_MARKET | equity                 | engine       |            8 |      1 |      7 |         0 |              0 |           21 |                 0 |
|     958 | Equity.US.AOS/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           20 |                 0 |
|     973 | Equity.US.AVY/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           20 |                 0 |
|    1320 | Equity.US.ODFL/USD           | PRE_MARKET  | equity                 | engine       |            9 |      0 |      7 |         2 |              0 |           17 |                 0 |
|    1366 | Equity.US.RDDT/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           21 |                 0 |
|    2704 | Equity.US.AFRM/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           16 |                 0 |
|    3224 | Equity.US.AGRO/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           14 |                 0 |
|    3170 | Equity.US.BIRD/USD           | REGULAR     | equity                 | engine       |            9 |      0 |      7 |         2 |              0 |           10 |                 0 |
|    2774 | Equity.US.GDXJ/USD           | POST_MARKET | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           15 |                 0 |
|    3288 | Equity.US.COHR/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           13 |                 0 |
|    3287 | Equity.US.AAOI/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           13 |                 0 |
|    1452 | Equity.US.UPST/USD           | REGULAR     | equity                 | engine       |           16 |      6 |      7 |         3 |              0 |           12 |                 1 |
|    1318 | Equity.US.NXPI/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    3167 | Equity.US.NTRA/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |            9 |                 0 |
|    1452 | Equity.US.UPST/USD           | POST_MARKET | equity                 | engine       |           11 |      1 |      7 |         3 |              0 |           17 |                 2 |
|    1361 | Equity.US.PYPL/USD           | REGULAR     | equity                 | engine       |           14 |      7 |      7 |         0 |              0 |           14 |                 1 |
|    1162 | Equity.US.GOOG/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           21 |                 0 |
|     978 | Equity.US.AZO/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 0 |
|    1177 | Equity.US.HII/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      7 |         1 |              0 |           16 |                 1 |
|     975 | Equity.US.AXON/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           19 |                 1 |
|    2773 | Equity.US.GDX/USD            | PRE_MARKET  | equity                 | engine       |            7 |      0 |      7 |         0 |              0 |           13 |                 0 |
|    1335 | Equity.US.PDD/USD            | PRE_MARKET  | equity                 | engine       |           11 |      2 |      6 |         3 |              0 |           18 |                 1 |
|    2735 | Equity.US.CRDO/USD           | REGULAR     | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           14 |                 0 |
|    1101 | Equity.US.EG/USD             | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|    1098 | Equity.US.EEM/USD            | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           18 |                 0 |
|    1270 | Equity.US.MELI/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           18 |                 0 |
|    3025 | Equity.US.SILJ/USD           | PRE_MARKET  | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           14 |                 0 |
|    2731 | Equity.US.CELH/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           17 |                 0 |
|    2705 | Equity.US.ALAB/USD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           15 |                 0 |
|    1346 | Equity.US.PLTR/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           23 |                 0 |
|    1195 | Equity.US.IBM/USD            | REGULAR     | equity                 | engine       |           11 |      5 |      6 |         0 |              0 |           18 |                 5 |
|    2689 | Equity.US.OPEN/USD           | PRE_MARKET  | equity                 | engine       |           10 |      1 |      6 |         3 |              0 |           13 |                 0 |
|    3036 | Equity.US.SPYM/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           15 |                 0 |
|    2714 | Equity.US.AVAV/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           17 |                 0 |
|    1361 | Equity.US.PYPL/USD           | POST_MARKET | equity                 | engine       |           10 |      4 |      6 |         0 |              0 |           18 |                 4 |
|    1167 | Equity.US.GRMN/USD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|    1157 | Equity.US.GLD/USD            | POST_MARKET | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           22 |                 0 |
|    1207 | Equity.US.IR/USD             | REGULAR     | equity                 | engine       |           12 |      5 |      6 |         1 |              0 |           13 |                 1 |
|    1080 | Equity.US.DIA/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           21 |                 0 |
|    1268 | Equity.US.MDLZ/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|    1201 | Equity.US.INTC/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           23 |                 0 |
|    2373 | Equity.US.SONY/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           16 |                 1 |
|    1206 | Equity.US.IQV/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|    1393 | Equity.US.SNPS/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           20 |                 0 |
|    1307 | Equity.US.NOC/USD            | PRE_MARKET  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           18 |                 0 |
|    2704 | Equity.US.AFRM/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           16 |                 1 |
|    1157 | Equity.US.GLD/USD            | REGULAR     | equity                 | engine       |           15 |      9 |      6 |         0 |              0 |           15 |                 3 |
|    1217 | Equity.US.JBHT/USD           | REGULAR     | equity                 | engine       |            7 |      1 |      6 |         0 |              0 |           18 |                 0 |
|    2860 | Equity.US.SNOW/USD           | PRE_MARKET  | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           10 |                 0 |
|    2375 | Equity.US.TEM/USD            | OVER_NIGHT  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           14 |                 0 |
|    1244 | Equity.US.LIN/USD            | PRE_MARKET  | equity                 | engine       |            8 |      2 |      6 |         0 |              0 |           15 |                 1 |
|    1174 | Equity.US.HD/USD             | POST_MARKET | equity                 | engine       |            7 |      1 |      6 |         0 |              0 |           22 |                 6 |
|    2771 | Equity.US.FUTU/USD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           15 |                 0 |
|    2760 | Equity.US.EWZ/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           15 |                 0 |
|    1191 | Equity.US.HWM/USD            | REGULAR     | equity                 | engine       |           11 |      4 |      6 |         1 |              0 |           13 |                 0 |
|    1128 | Equity.US.FAST/USD           | POST_MARKET | equity                 | engine       |            8 |      1 |      6 |         1 |              0 |           17 |                 1 |
|    2928 | Equity.US.NLR/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           17 |                 0 |
|    1143 | Equity.US.FSLR/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 2 |
|    2985 | Crypto.AUDD/USD              | REGULAR     | crypto                 | peer         |            6 |      0 |      6 |         0 |              0 |            5 |                 0 |
|    2948 | Equity.US.FWDI/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           16 |                 0 |
|    1144 | Equity.US.FTNT/USD           | PRE_MARKET  | equity                 | engine       |            7 |      1 |      6 |         0 |              0 |           17 |                 1 |
|    2864 | Equity.US.SPOT/USD           | PRE_MARKET  | equity                 | engine       |            7 |      1 |      6 |         0 |              0 |           15 |                 0 |
|    1250 | Equity.US.LRCX/USD           | PRE_MARKET  | equity                 | engine       |            9 |      0 |      6 |         3 |              0 |           19 |                 0 |
|    2946 | Equity.US.EXOD/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           17 |                 0 |
|    2323 | Crypto.CASH/USD              | REGULAR     | crypto                 | peer         |            8 |      2 |      6 |         0 |              0 |            2 |                 0 |
|    1250 | Equity.US.LRCX/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           22 |                 3 |
|    1154 | Equity.US.GILD/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           18 |                 1 |
|    1378 | Equity.US.ROP/USD            | PRE_MARKET  | equity                 | engine       |            8 |      1 |      6 |         1 |              0 |           17 |                 1 |
|    1307 | Equity.US.NOC/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           18 |                 0 |
|    1121 | Equity.US.EXC/USD            | REGULAR     | equity                 | engine       |           15 |      8 |      6 |         1 |              0 |           11 |                 2 |
|    1115 | Equity.US.ESS/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|    1218 | Equity.US.JBL/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|    2945 | Equity.US.HSDT/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           17 |                 0 |
|    1165 | Equity.US.GPC/USD            | REGULAR     | equity                 | engine       |            7 |      1 |      6 |         0 |              0 |           18 |                 0 |
|    1263 | Equity.US.MCHI/USD           | REGULAR     | equity                 | engine       |           13 |      7 |      6 |         0 |              0 |            9 |                 0 |
|    1181 | Equity.US.HON/USD            | PRE_MARKET  | equity                 | engine       |            8 |      1 |      6 |         1 |              0 |           18 |                 4 |
|    1265 | Equity.US.MCK/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|    3049 | Crypto.USDSUI/USD            | REGULAR     | crypto                 | peer         |            6 |      0 |      6 |         0 |              0 |            3 |                 0 |
|    1210 | Equity.US.IT/USD             | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|    1179 | Equity.US.HODL/USD           | REGULAR     | equity                 | engine       |           11 |      4 |      6 |         1 |              0 |           12 |                 1 |
|    1467 | Equity.US.V/USD              | POST_MARKET | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           20 |                 3 |
|     966 | Equity.US.ARKB/USD           | REGULAR     | equity                 | engine       |           12 |      6 |      6 |         0 |              0 |           13 |                 1 |
|    1505 | Equity.US.ZTS/USD            | REGULAR     | equity                 | engine       |           11 |      4 |      6 |         1 |              0 |           12 |                 1 |
|    3232 | Equity.US.LI/USD             | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           11 |                 1 |
|     929 | Equity.US.ADI/USD            | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           20 |                 0 |
|     939 | Equity.US.AIZ/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           20 |                 0 |
|     930 | Equity.US.ADM/USD            | PRE_MARKET  | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           22 |                 0 |
|    3230 | Equity.US.ZM/USD             | PRE_MARKET  | equity                 | engine       |            9 |      0 |      6 |         3 |              0 |           10 |                 0 |
|     943 | Equity.US.ALGN/USD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           21 |                 0 |
|     950 | Equity.US.AME/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           21 |                 4 |
|    1764 | Equity.US.VT/USD             | PRE_MARKET  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           17 |                 0 |
|    1764 | Equity.US.VT/USD             | POST_MARKET | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           17 |                 0 |
|     955 | Equity.US.ANET/USD           | PRE_MARKET  | equity                 | engine       |            9 |      0 |      6 |         3 |              0 |           21 |                 0 |
|    1475 | Equity.US.VRTX/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|     965 | Equity.US.ARE/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           21 |                 0 |
|    1471 | Equity.US.VMC/USD            | REGULAR     | equity                 | engine       |           10 |      3 |      6 |         1 |              0 |           13 |                 1 |
|    1021 | Equity.US.CDNS/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           19 |                 1 |
|     963 | Equity.US.APP/USD            | PRE_MARKET  | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           21 |                 1 |
|     967 | Equity.US.ARKK/USD           | PRE_MARKET  | equity                 | engine       |            9 |      0 |      6 |         3 |              0 |           21 |                 0 |
|     969 | Equity.US.ASML/USD           | REGULAR     | equity                 | engine       |           12 |      6 |      6 |         0 |              0 |           17 |                 4 |
|     974 | Equity.US.AWK/USD            | REGULAR     | equity                 | engine       |           16 |      9 |      6 |         1 |              0 |           11 |                 3 |
|     977 | Equity.US.AZN/USD            | POST_MARKET | equity                 | engine       |            8 |      2 |      6 |         0 |              0 |           20 |                 1 |
|    1775 | Equity.US.XLK/USD            | PRE_MARKET  | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           17 |                 0 |
|    3169 | Equity.US.CW/USD             | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           15 |                 0 |
|    3168 | Equity.US.CASY/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           16 |                 1 |
|    3164 | Equity.US.BOT/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           14 |                 0 |
|    1009 | Equity.US.C/USD              | REGULAR     | equity                 | engine       |           15 |      9 |      6 |         0 |              0 |           11 |                 2 |
|    1933 | Equity.HK.1606/HKD           | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |            2 |                 0 |
|    1441 | Equity.US.TXN/USD            | PRE_MARKET  | equity                 | engine       |            9 |      0 |      6 |         3 |              0 |           19 |                 0 |
|    1023 | Equity.US.CE/USD             | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           19 |                 0 |
|     925 | Equity.US.ABT/USD            | REGULAR     | equity                 | engine       |           15 |      9 |      6 |         0 |              0 |           12 |                 3 |
|    1506 | FX.USD/BRL                   | REGULAR     | fx                     | engine       |            8 |      0 |      6 |         2 |              0 |           10 |                 0 |
|    3259 | Equity.HK.9660/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            2 |                 0 |
|    3279 | Equity.US.EDU/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           16 |                 1 |
|    1694 | Equity.US.IEMG/USD           | REGULAR     | equity                 | engine       |           11 |      5 |      6 |         0 |              0 |            9 |                 0 |
|    1651 | Equity.HK.3692/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            4 |                 0 |
|    3357 | Equity.US.CIEN/USD           | POST_MARKET | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           11 |                 3 |
|    3354 | Equity.US.UMC/USD            | POST_MARKET | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           13 |                 1 |
|    3353 | Equity.US.NVTS/USD           | REGULAR     | equity                 | engine       |           10 |      2 |      6 |         2 |              0 |           10 |                 0 |
|    3359 | Equity.HK.2476/HKD           | REGULAR     | equity                 | engine       |            8 |      1 |      6 |         1 |              0 |            2 |                 0 |
|    3358 | Equity.HK.6809/HKD           | REGULAR     | equity                 | engine       |            8 |      1 |      6 |         1 |              0 |            1 |                 0 |
|    3351 | Equity.US.NU/USD             | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           13 |                 2 |
|    1713 | Equity.US.MAGS/USD           | REGULAR     | equity                 | engine       |            9 |      2 |      6 |         1 |              0 |           16 |                 2 |
|    1632 | Equity.HK.0968/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            4 |                 0 |
|    3348 | Equity.US.TSEM/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           13 |                 0 |
|     276 | Crypto.USDY/USD              | REGULAR     | crypto                 | peer         |            7 |      0 |      6 |         1 |              0 |           13 |                 0 |
|    1628 | Equity.HK.0868/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            4 |                 0 |
|    3345 | Equity.US.MXL/USD            | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           13 |                 1 |
|    1629 | Equity.HK.0881/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            4 |                 1 |
|    1621 | Equity.HK.0386/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            4 |                 1 |
|    3350 | Equity.US.XNDU/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           12 |                 0 |
|    1747 | Equity.US.TSLQ/USD           | REGULAR     | equity                 | engine       |            8 |      2 |      6 |         0 |              0 |           11 |                 0 |
|    1519 | FX.USD/TWD                   | REGULAR     | fx                     | engine       |            7 |      0 |      6 |         1 |              0 |            6 |                 0 |
|    3311 | Equity.US.QNT/USD            | REGULAR     | equity                 | engine       |            8 |      0 |      6 |         2 |              0 |           10 |                 0 |
|     889 | Equity.HK.0101/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            4 |                 0 |
|     890 | Equity.HK.0241/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            4 |                 0 |
|     899 | Equity.HK.1093/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            4 |                 0 |
|    3286 | Equity.US.AXTI/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           14 |                 0 |
|    3286 | Equity.US.AXTI/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           14 |                 0 |
|    3284 | Equity.US.AVEX/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           13 |                 0 |
|    3276 | Equity.US.RVMD/USD           | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           15 |                 0 |
|    1435 | Equity.US.TSLA/USD           | REGULAR     | equity                 | engine       |           22 |     13 |      6 |         3 |              0 |           11 |                 3 |
|    1286 | Equity.US.MPWR/USD           | POST_MARKET | equity                 | engine       |            9 |      2 |      6 |         1 |              0 |           16 |                 2 |
|    1060 | Equity.US.CTSH/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           18 |                 0 |
|    3108 | Equity.US.IEUR/USD           | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |            9 |                 0 |
|    1048 | Equity.US.CPB/USD            | REGULAR     | equity                 | engine       |           14 |      8 |      6 |         0 |              0 |           11 |                 3 |
|    3054 | Equity.US.KORU/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           16 |                 0 |
|    1052 | Equity.US.CRL/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           18 |                 0 |
|    1058 | Equity.US.CTAS/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           19 |                 0 |
|    1427 | Equity.US.TMUS/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           18 |                 0 |
|    3140 | Equity.US.FLY/USD            | REGULAR     | equity                 | engine       |            6 |      0 |      6 |         0 |              0 |           13 |                 0 |
|    1034 | Equity.US.CMCSA/USD          | PRE_MARKET  | equity                 | engine       |            7 |      1 |      6 |         0 |              0 |           18 |                 0 |
|    1425 | Equity.US.TLT/USD            | REGULAR     | equity                 | engine       |           19 |     11 |      6 |         2 |              0 |            9 |                 5 |
|    1091 | Equity.US.DVA/USD            | REGULAR     | equity                 | engine       |            7 |      0 |      6 |         1 |              0 |           19 |                 1 |
|    1231 | Equity.US.KLAC/USD           | PRE_MARKET  | equity                 | engine       |           12 |      3 |      5 |         4 |              0 |           16 |                 3 |
|    1308 | Equity.US.NOW/USD            | REGULAR     | equity                 | engine       |           15 |     10 |      5 |         0 |              0 |           13 |                 2 |
|    2419 | Equity.US.STRC/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    1498 | Equity.US.XLE/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           23 |                 0 |
|    1331 | Equity.US.PAYC/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|    1228 | Equity.US.KHC/USD            | PRE_MARKET  | equity                 | engine       |            9 |      1 |      5 |         3 |              0 |           18 |                 0 |
|    2299 | Equity.US.SLS/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    1055 | Equity.US.CSCO/USD           | REGULAR     | equity                 | engine       |           16 |     10 |      5 |         1 |              0 |           14 |                 3 |
|    1053 | Equity.US.CRM/USD            | REGULAR     | equity                 | engine       |           15 |     10 |      5 |         0 |              0 |           15 |                 3 |
|     887 | Equity.HK.0017/HKD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |            4 |                 0 |
|    1504 | Equity.US.ZS/USD             | POST_MARKET | equity                 | engine       |           10 |      3 |      5 |         2 |              0 |           14 |                 3 |
|    1498 | Equity.US.XLE/USD            | REGULAR     | equity                 | engine       |           12 |      6 |      5 |         1 |              0 |           17 |                 2 |
|    1235 | Equity.US.KO/USD             | REGULAR     | equity                 | engine       |           12 |      6 |      5 |         1 |              0 |           16 |                 5 |
|    2773 | Equity.US.GDX/USD            | REGULAR     | equity                 | engine       |            9 |      3 |      5 |         1 |              0 |           11 |                 1 |
|    3047 | Equity.US.MNDY/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           16 |                 0 |
|    1095 | Equity.US.EBAY/USD           | PRE_MARKET  | equity                 | engine       |           11 |      2 |      5 |         4 |              0 |           18 |                 0 |
|    2288 | Equity.US.GLXY/USD           | REGULAR     | equity                 | engine       |           12 |      5 |      5 |         2 |              0 |           14 |                 0 |
|    1382 | Equity.US.RVTY/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           19 |                 0 |
|    1320 | Equity.US.ODFL/USD           | REGULAR     | equity                 | engine       |            9 |      4 |      5 |         0 |              0 |           17 |                 2 |
|    2814 | Equity.US.KTOS/USD           | REGULAR     | equity                 | engine       |           10 |      4 |      5 |         1 |              0 |            7 |                 0 |
|    2779 | Equity.US.GRAB/USD           | PRE_MARKET  | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 1 |
|    2274 | Equity.US.BOTZ/USD           | REGULAR     | equity                 | engine       |           12 |      6 |      5 |         1 |              0 |           13 |                 2 |
|    1483 | Equity.US.WBD/USD            | REGULAR     | equity                 | engine       |           14 |      8 |      5 |         1 |              0 |           11 |                 1 |
|    1202 | Equity.US.INTU/USD           | REGULAR     | equity                 | engine       |           15 |      9 |      5 |         1 |              0 |           13 |                 2 |
|    1376 | Equity.US.ROK/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|    1201 | Equity.US.INTC/USD           | REGULAR     | equity                 | engine       |           12 |      6 |      5 |         1 |              0 |           18 |                 1 |
|    3236 | Equity.US.P/USD              | PRE_MARKET  | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |           11 |                 1 |
|    1324 | Equity.US.ORCL/USD           | REGULAR     | equity                 | engine       |           15 |      9 |      5 |         1 |              0 |           15 |                 7 |
|    3238 | Equity.US.IOT/USD            | REGULAR     | equity                 | engine       |            9 |      3 |      5 |         1 |              0 |            7 |                 0 |
|    2944 | Equity.US.EWY/USD            | REGULAR     | equity                 | engine       |           13 |      8 |      5 |         0 |              0 |           13 |                 1 |
|    1102 | Equity.US.EIX/USD            | REGULAR     | equity                 | engine       |           14 |      9 |      5 |         0 |              0 |           12 |                 6 |
|    3258 | Equity.HK.2513/HKD           | REGULAR     | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |            3 |                 0 |
|    1320 | Equity.US.ODFL/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      5 |         2 |              0 |           19 |                 1 |
|    1058 | Equity.US.CTAS/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|    3240 | Equity.US.DRAM/USD           | REGULAR     | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |           15 |                 0 |
|    1422 | Equity.US.TFX/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           17 |                 0 |
|    1419 | Equity.US.TEL/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    1499 | Equity.US.XOM/USD            | REGULAR     | equity                 | engine       |           16 |      9 |      5 |         2 |              0 |           12 |                 1 |
|    1223 | Equity.US.JPM/USD            | REGULAR     | equity                 | engine       |           16 |     10 |      5 |         1 |              0 |           14 |                 4 |
|    1103 | Equity.US.EL/USD             | REGULAR     | equity                 | engine       |            8 |      3 |      5 |         0 |              0 |           17 |                 1 |
|    1723 | Equity.US.QQQM/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           21 |                 0 |
|    1398 | Equity.US.SPY/USD            | POST_MARKET | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |           24 |                 0 |
|    2769 | Equity.US.FLUT/USD           | PRE_MARKET  | equity                 | engine       |            6 |      1 |      5 |         0 |              0 |           17 |                 0 |
|    3352 | Equity.US.CLSK/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    1092 | Equity.US.DVN/USD            | REGULAR     | equity                 | engine       |           14 |      9 |      5 |         0 |              0 |           11 |                 3 |
|    1070 | Equity.US.DDOG/USD           | POST_MARKET | equity                 | engine       |            8 |      2 |      5 |         1 |              0 |           21 |                 2 |
|    1274 | Equity.US.MHK/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           19 |                 0 |
|    3360 | Equity.HK.3986/HKD           | REGULAR     | equity                 | engine       |            7 |      2 |      5 |         0 |              0 |            1 |                 0 |
|     158 | Crypto.TUSD/USD              | REGULAR     | crypto                 | peer         |           10 |      4 |      5 |         1 |              0 |           18 |                 2 |
|    1079 | Equity.US.DHR/USD            | REGULAR     | equity                 | engine       |           13 |      8 |      5 |         0 |              0 |           12 |                 6 |
|    3354 | Equity.US.UMC/USD            | PRE_MARKET  | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 1 |
|    1267 | Equity.US.MDB/USD            | POST_MARKET | equity                 | engine       |            8 |      2 |      5 |         1 |              0 |           16 |                 0 |
|    1277 | Equity.US.MKTX/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    1706 | Equity.US.IXUS/USD           | REGULAR     | equity                 | engine       |           10 |      5 |      5 |         0 |              0 |            9 |                 1 |
|    1692 | Equity.US.IEF/USD            | REGULAR     | equity                 | engine       |           14 |      8 |      5 |         1 |              0 |           10 |                 3 |
|    1074 | Equity.US.DELL/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |           22 |                 4 |
|    1301 | Equity.US.NDSN/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|    2748 | Equity.US.EFV/USD            | REGULAR     | equity                 | engine       |            8 |      3 |      5 |         0 |              0 |            8 |                 1 |
|    1400 | Equity.US.STE/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    1697 | Equity.US.ITOT/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    2706 | Equity.US.APLD/USD           | REGULAR     | equity                 | engine       |            9 |      4 |      5 |         0 |              0 |           14 |                 0 |
|    3356 | Equity.US.QUBT/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           15 |                 0 |
|    3352 | Equity.US.CLSK/USD           | PRE_MARKET  | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    3352 | Equity.US.CLSK/USD           | REGULAR     | equity                 | engine       |            7 |      2 |      5 |         0 |              0 |           12 |                 0 |
|    1260 | Equity.US.MARA/USD           | REGULAR     | equity                 | engine       |           11 |      6 |      5 |         0 |              0 |           17 |                 3 |
|    2305 | Equity.US.WSM/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    1117 | Equity.US.ETR/USD            | REGULAR     | equity                 | engine       |           11 |      6 |      5 |         0 |              0 |           14 |                 5 |
|    2689 | Equity.US.OPEN/USD           | POST_MARKET | equity                 | engine       |            7 |      1 |      5 |         1 |              0 |           16 |                 0 |
|    3343 | Equity.US.NNE/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    2792 | Equity.US.IDV/USD            | REGULAR     | equity                 | engine       |            8 |      3 |      5 |         0 |              0 |            8 |                 2 |
|    3343 | Equity.US.NNE/USD            | PRE_MARKET  | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    1244 | Equity.US.LIN/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 4 |
|    1408 | Equity.US.SWK/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|    3342 | Equity.US.PENG/USD           | PRE_MARKET  | equity                 | engine       |            9 |      1 |      5 |         3 |              0 |           10 |                 1 |
|    1251 | Equity.US.LULU/USD           | REGULAR     | equity                 | engine       |           12 |      6 |      5 |         1 |              0 |           13 |                 4 |
|    1309 | Equity.US.NRG/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|    3345 | Equity.US.MXL/USD            | POST_MARKET | equity                 | engine       |            6 |      1 |      5 |         0 |              0 |           13 |                 0 |
|    1297 | Equity.US.MTD/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|    1067 | Equity.US.DASH/USD           | PRE_MARKET  | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           23 |                 0 |
|    3349 | Equity.US.SPMO/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    3048 | Equity.US.ONDS/USD           | PRE_MARKET  | equity                 | engine       |            8 |      0 |      5 |         3 |              0 |           13 |                 0 |
|    1257 | Equity.US.MA/USD             | PRE_MARKET  | equity                 | engine       |            7 |      0 |      5 |         2 |              0 |           21 |                 0 |
|    3351 | Equity.US.NU/USD             | POST_MARKET | equity                 | engine       |            7 |      2 |      5 |         0 |              0 |           12 |                 0 |
|     176 | Crypto.USDD/USD              | REGULAR     | crypto                 | peer         |           11 |      4 |      5 |         2 |              0 |            7 |                 1 |
|    1332 | Equity.US.PAYX/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      5 |         2 |              0 |           19 |                 0 |
|    2274 | Equity.US.BOTZ/USD           | PRE_MARKET  | equity                 | engine       |            8 |      0 |      5 |         3 |              0 |           17 |                 0 |
|    1089 | Equity.US.DTE/USD            | REGULAR     | equity                 | engine       |           11 |      6 |      5 |         0 |              0 |           13 |                 2 |
|    1044 | Equity.US.COP/USD            | PRE_MARKET  | equity                 | engine       |            9 |      2 |      5 |         2 |              0 |           19 |                 2 |
|    1150 | Equity.US.GEHC/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      5 |         2 |              0 |           17 |                 1 |
|    2298 | Equity.US.SHOP/USD           | PRE_MARKET  | equity                 | engine       |            7 |      2 |      5 |         0 |              0 |           12 |                 0 |
|    2370 | Equity.US.RGTI/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |           16 |                 0 |
|    1040 | Equity.US.CNP/USD            | REGULAR     | equity                 | engine       |           13 |      8 |      5 |         0 |              0 |           11 |                 3 |
|    3170 | Equity.US.BIRD/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|    1155 | Equity.US.GIS/USD            | REGULAR     | equity                 | engine       |           14 |      9 |      5 |         0 |              0 |           11 |                 3 |
|    3175 | Equity.US.DKNG/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |           14 |                 0 |
|     976 | Equity.US.AXP/USD            | PRE_MARKET  | equity                 | engine       |           10 |      2 |      5 |         3 |              0 |           20 |                 2 |
|     972 | Equity.US.AVGO/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           25 |                 1 |
|     972 | Equity.US.AVGO/USD           | REGULAR     | equity                 | engine       |           15 |      9 |      5 |         1 |              0 |           16 |                 5 |
|    3223 | Equity.US.URA/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           15 |                 0 |
|    1149 | Equity.US.GE/USD             | POST_MARKET | equity                 | engine       |            7 |      2 |      5 |         0 |              0 |           19 |                 3 |
|     975 | Equity.US.AXON/USD           | POST_MARKET | equity                 | engine       |            6 |      1 |      5 |         0 |              0 |           20 |                 1 |
|    3113 | Equity.US.EWG/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           10 |                 0 |
|    2929 | Equity.US.AIQ/USD            | PRE_MARKET  | equity                 | engine       |            7 |      0 |      5 |         2 |              0 |           17 |                 0 |
|    1448 | Equity.US.ULTA/USD           | PRE_MARKET  | equity                 | engine       |            7 |      1 |      5 |         1 |              0 |           19 |                 0 |
|     986 | Equity.US.BF-B/USD           | REGULAR     | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |            3 |                 0 |
|    1027 | Equity.US.CHD/USD            | REGULAR     | equity                 | engine       |            9 |      4 |      5 |         0 |              0 |           17 |                 2 |
|     995 | Equity.US.BLK/USD            | PRE_MARKET  | equity                 | engine       |            8 |      2 |      5 |         1 |              0 |           22 |                 1 |
|    1440 | Equity.US.TTWO/USD           | POST_MARKET | equity                 | engine       |            6 |      1 |      5 |         0 |              0 |           22 |                 1 |
|       1 | Crypto.BTC/USD               | REGULAR     | crypto                 | peer         |           19 |     14 |      5 |         0 |              0 |           13 |                 7 |
|    1445 | Equity.US.UBER/USD           | PRE_MARKET  | equity                 | engine       |           11 |      2 |      5 |         4 |              0 |           17 |                 2 |
|    1443 | Equity.US.TYL/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    1158 | Equity.US.GLW/USD            | REGULAR     | equity                 | engine       |           10 |      5 |      5 |         0 |              0 |           18 |                 0 |
|    2911 | Equity.US.PURR/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    1775 | Equity.US.XLK/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|     998 | Equity.US.BRK-A/USD          | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |            4 |                 0 |
|     992 | Equity.US.BKNG/USD           | REGULAR     | equity                 | engine       |            9 |      4 |      5 |         0 |              0 |           19 |                 1 |
|    1453 | Equity.US.URI/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    1010 | Equity.US.CAG/USD            | REGULAR     | equity                 | engine       |           12 |      7 |      5 |         0 |              0 |           13 |                 4 |
|    2277 | Equity.US.DAPP/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           12 |                 0 |
|    1128 | Equity.US.FAST/USD           | REGULAR     | equity                 | engine       |            8 |      3 |      5 |         0 |              0 |           16 |                 1 |
|    1447 | Equity.US.UHS/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    1778 | Equity.US.YANG/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           16 |                 0 |
|    2892 | Equity.US.XBI/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    1360 | Equity.US.PWR/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           19 |                 0 |
|    1041 | Equity.US.COF/USD            | PRE_MARKET  | equity                 | engine       |           10 |      0 |      5 |         5 |              0 |           19 |                 0 |
|    1193 | Equity.US.IAU/USD            | POST_MARKET | equity                 | engine       |            7 |      0 |      5 |         2 |              0 |           21 |                 0 |
|    1147 | Equity.US.GD/USD             | PRE_MARKET  | equity                 | engine       |            7 |      0 |      5 |         2 |              0 |           18 |                 2 |
|    2855 | Equity.US.SMR/USD            | REGULAR     | equity                 | engine       |            8 |      2 |      5 |         1 |              0 |           12 |                 1 |
|    2364 | Equity.US.JD/USD             | REGULAR     | equity                 | engine       |           11 |      6 |      5 |         0 |              0 |           14 |                 3 |
|    1017 | Equity.US.CBRE/USD           | REGULAR     | equity                 | engine       |            8 |      3 |      5 |         0 |              0 |           18 |                 3 |
|    1007 | Equity.US.BX/USD             | REGULAR     | equity                 | engine       |           11 |      6 |      5 |         0 |              0 |           17 |                 5 |
|    2930 | Equity.US.SHLD/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           18 |                 0 |
|    2273 | Equity.US.BNC/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           12 |                 0 |
|    1476 | Equity.US.VST/USD            | REGULAR     | equity                 | engine       |           13 |      7 |      5 |         1 |              0 |           13 |                 3 |
|    3143 | Equity.US.RDW/USD            | PRE_MARKET  | equity                 | engine       |            7 |      0 |      5 |         2 |              0 |           12 |                 0 |
|    1146 | Equity.US.GBTC/USD           | REGULAR     | equity                 | engine       |           11 |      5 |      5 |         1 |              0 |           12 |                 2 |
|     944 | Equity.US.ALL/USD            | REGULAR     | equity                 | engine       |            9 |      4 |      5 |         0 |              0 |           17 |                 9 |
|    1130 | Equity.US.FCX/USD            | PRE_MARKET  | equity                 | engine       |            7 |      1 |      5 |         1 |              0 |           21 |                 0 |
|    1381 | Equity.US.RTX/USD            | PRE_MARKET  | equity                 | engine       |            7 |      1 |      5 |         1 |              0 |           21 |                 2 |
|    2275 | Equity.US.BTBT/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           14 |                 0 |
|     930 | Equity.US.ADM/USD            | POST_MARKET | equity                 | engine       |            6 |      1 |      5 |         0 |              0 |           24 |                 6 |
|    1116 | Equity.US.ETN/USD            | POST_MARKET | equity                 | engine       |            7 |      2 |      5 |         0 |              0 |           22 |                 4 |
|    1420 | Equity.US.TER/USD            | POST_MARKET | equity                 | engine       |            6 |      1 |      5 |         0 |              0 |           20 |                 0 |
|    2352 | Equity.US.BLSH/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           11 |                 0 |
|    2863 | Equity.US.SOXL/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |           15 |                 0 |
|    1781 | Metal.XPT/USD                | REGULAR     | metal                  | engine       |            5 |      0 |      5 |         0 |              0 |            8 |                 0 |
|    1191 | Equity.US.HWM/USD            | PRE_MARKET  | equity                 | engine       |            8 |      1 |      5 |         2 |              0 |           16 |                 0 |
|    1020 | Equity.US.CCL/USD            | REGULAR     | equity                 | engine       |           12 |      7 |      5 |         0 |              0 |           14 |                 1 |
|    1679 | Equity.US.BND/USD            | REGULAR     | equity                 | engine       |           12 |      7 |      5 |         0 |              0 |            8 |                 4 |
|    1780 | Metal.XPD/USD                | REGULAR     | metal                  | engine       |            5 |      0 |      5 |         0 |              0 |            5 |                 0 |
|    1047 | Equity.US.CPAY/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           19 |                 0 |
|    1374 | Equity.US.RL/USD             | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           20 |                 0 |
|    1151 | Equity.US.GEN/USD            | REGULAR     | equity                 | engine       |           14 |      7 |      5 |         2 |              0 |           13 |                 3 |
|    1170 | Equity.US.HAL/USD            | REGULAR     | equity                 | engine       |           11 |      6 |      5 |         0 |              0 |           17 |                 4 |
|    3227 | Equity.US.ALNY/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      5 |         1 |              0 |           11 |                 0 |
|     961 | Equity.US.APH/USD            | REGULAR     | equity                 | engine       |           13 |      8 |      5 |         0 |              0 |           13 |                 4 |
|    1344 | Equity.US.PKG/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      5 |         0 |              0 |           19 |                 0 |
|    3227 | Equity.US.ALNY/USD           | POST_MARKET | equity                 | engine       |            6 |      1 |      5 |         0 |              0 |           11 |                 0 |
|    1402 | Equity.US.STRK/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           14 |                 0 |
|    1445 | Equity.US.UBER/USD           | REGULAR     | equity                 | engine       |           14 |     10 |      4 |         0 |              0 |           14 |                 4 |
|    1728 | Equity.US.SCHB/USD           | REGULAR     | equity                 | engine       |           10 |      5 |      4 |         1 |              0 |           10 |                 4 |
|    1368 | Equity.US.REGN/USD           | REGULAR     | equity                 | engine       |            8 |      4 |      4 |         0 |              0 |           18 |                 5 |
|    1307 | Equity.US.NOC/USD            | REGULAR     | equity                 | engine       |           10 |      5 |      4 |         1 |              0 |           15 |                 5 |
|    1441 | Equity.US.TXN/USD            | REGULAR     | equity                 | engine       |           13 |      8 |      4 |         1 |              0 |           16 |                 4 |
|    1488 | Equity.US.WFC/USD            | REGULAR     | equity                 | engine       |           13 |      9 |      4 |         0 |              0 |           10 |                 1 |
|    1843 | Crypto.SPYX/USD              | REGULAR     | crypto                 | peer         |           14 |      9 |      4 |         1 |              0 |            6 |                 4 |
|    2363 | Equity.US.IREN/USD           | REGULAR     | equity                 | engine       |           10 |      4 |      4 |         2 |              0 |           14 |                 1 |
|    2420 | Equity.US.STRD/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |            9 |                 0 |
|    2372 | Equity.US.SMH/USD            | REGULAR     | equity                 | engine       |            9 |      4 |      4 |         1 |              0 |           14 |                 4 |
|    1483 | Equity.US.WBD/USD            | PRE_MARKET  | equity                 | engine       |            7 |      2 |      4 |         1 |              0 |           18 |                 1 |
|    2269 | Equity.US.AAL/USD            | REGULAR     | equity                 | engine       |           14 |      7 |      4 |         3 |              0 |           12 |                 1 |
|    1494 | Equity.US.WTW/USD            | REGULAR     | equity                 | engine       |            8 |      4 |      4 |         0 |              0 |           14 |                 1 |
|    1485 | Equity.US.WDC/USD            | REGULAR     | equity                 | engine       |           10 |      6 |      4 |         0 |              0 |           16 |                 3 |
|    1739 | Equity.US.SOXX/USD           | REGULAR     | equity                 | engine       |           12 |      8 |      4 |         0 |              0 |           13 |                 1 |
|    1473 | Equity.US.VRSK/USD           | REGULAR     | equity                 | engine       |           10 |      6 |      4 |         0 |              0 |           15 |                 2 |
|    1496 | Equity.US.WYNN/USD           | REGULAR     | equity                 | engine       |           10 |      5 |      4 |         1 |              0 |           14 |                 7 |
|    1417 | Equity.US.TEAM/USD           | POST_MARKET | equity                 | engine       |            7 |      2 |      4 |         1 |              0 |           17 |                 2 |
|    1466 | Equity.US.USO/USD            | REGULAR     | equity                 | engine       |           11 |      6 |      4 |         1 |              0 |           18 |                 2 |
|    2301 | Equity.US.TKO/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           15 |                 0 |
|    1499 | Equity.US.XOM/USD            | PRE_MARKET  | equity                 | engine       |            8 |      1 |      4 |         3 |              0 |           19 |                 1 |
|    1318 | Equity.US.NXPI/USD           | POST_MARKET | equity                 | engine       |            6 |      2 |      4 |         0 |              0 |           20 |                 4 |
|    1385 | Equity.US.SCHW/USD           | REGULAR     | equity                 | engine       |           15 |     11 |      4 |         0 |              0 |           10 |                 4 |
|    1427 | Equity.US.TMUS/USD           | POST_MARKET | equity                 | engine       |            7 |      3 |      4 |         0 |              0 |           18 |                 3 |
|    1779 | Equity.US.YINN/USD           | REGULAR     | equity                 | engine       |            5 |      1 |      4 |         0 |              0 |           15 |                 0 |
|    1413 | Equity.US.T/USD              | REGULAR     | equity                 | engine       |           12 |      8 |      4 |         0 |              0 |           10 |                 2 |
|    1364 | Equity.US.RBLX/USD           | REGULAR     | equity                 | engine       |            7 |      3 |      4 |         0 |              0 |           17 |                 1 |
|    1742 | Equity.US.SPYG/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           15 |                 0 |
|    1303 | Equity.US.NEM/USD            | REGULAR     | equity                 | engine       |           17 |     12 |      4 |         1 |              0 |           11 |                 2 |
|    1361 | Equity.US.PYPL/USD           | OVER_NIGHT  | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           23 |                 0 |
|    1731 | Equity.US.SCHG/USD           | REGULAR     | equity                 | engine       |           11 |      6 |      4 |         1 |              0 |           10 |                 4 |
|    1393 | Equity.US.SNPS/USD           | REGULAR     | equity                 | engine       |           11 |      6 |      4 |         1 |              0 |           15 |                 4 |
|    1721 | Equity.US.NVO/USD            | REGULAR     | equity                 | engine       |           11 |      7 |      4 |         0 |              0 |           14 |                 0 |
|    1713 | Equity.US.MAGS/USD           | POST_MARKET | equity                 | engine       |            6 |      1 |      4 |         1 |              0 |           19 |                 2 |
|    1362 | Equity.US.QCOM/USD           | REGULAR     | equity                 | engine       |           13 |      9 |      4 |         0 |              0 |           17 |                 6 |
|    1411 | Equity.US.SYK/USD            | REGULAR     | equity                 | engine       |           11 |      6 |      4 |         1 |              0 |           14 |                 4 |
|    1368 | Equity.US.REGN/USD           | PRE_MARKET  | equity                 | engine       |            6 |      2 |      4 |         0 |              0 |           20 |                 0 |
|    3230 | Equity.US.ZM/USD             | POST_MARKET | equity                 | engine       |            7 |      1 |      4 |         2 |              0 |           12 |                 1 |
|    1203 | Equity.US.INVH/USD           | REGULAR     | equity                 | engine       |           14 |      9 |      4 |         1 |              0 |           12 |                 6 |
|     997 | Equity.US.BR/USD             | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           21 |                 0 |
|    1125 | Equity.US.EZBC/USD           | REGULAR     | equity                 | engine       |            7 |      2 |      4 |         1 |              0 |           16 |                 0 |
|     963 | Equity.US.APP/USD            | POST_MARKET | equity                 | engine       |            5 |      1 |      4 |         0 |              0 |           24 |                 5 |
|    1120 | Equity.US.EWH/USD            | REGULAR     | equity                 | engine       |            9 |      5 |      4 |         0 |              0 |           15 |                 4 |
|    2930 | Equity.US.SHLD/USD           | PRE_MARKET  | equity                 | engine       |            7 |      1 |      4 |         2 |              0 |           16 |                 0 |
|     962 | Equity.US.APO/USD            | REGULAR     | equity                 | engine       |           10 |      6 |      4 |         0 |              0 |           16 |                 7 |
|    2947 | Crypto.JUPUSD/USD            | REGULAR     | crypto                 | peer         |            7 |      3 |      4 |         0 |              0 |            3 |                 1 |
|    2892 | Equity.US.XBI/USD            | OVER_NIGHT  | equity                 | engine       |            6 |      0 |      4 |         2 |              0 |           18 |                 0 |
|     955 | Equity.US.ANET/USD           | REGULAR     | equity                 | engine       |            6 |      2 |      4 |         0 |              0 |           24 |                 2 |
|     949 | Equity.US.AMD/USD            | REGULAR     | equity                 | engine       |           16 |     10 |      4 |         2 |              0 |           16 |                 5 |
|    1150 | Equity.US.GEHC/USD           | REGULAR     | equity                 | engine       |           13 |      8 |      4 |         1 |              0 |           12 |                 3 |
|    1173 | Equity.US.HCA/USD            | REGULAR     | equity                 | engine       |            8 |      4 |      4 |         0 |              0 |           16 |                 0 |
|    1061 | Equity.US.CTVA/USD           | REGULAR     | equity                 | engine       |           12 |      8 |      4 |         0 |              0 |           12 |                 5 |
|    1174 | Equity.US.HD/USD             | PRE_MARKET  | equity                 | engine       |           10 |      2 |      4 |         4 |              0 |           19 |                 2 |
|    1182 | Equity.US.HOOD/USD           | REGULAR     | equity                 | engine       |           16 |     10 |      4 |         2 |              0 |           14 |                 4 |
|    2853 | Equity.US.SLV/USD            | PRE_MARKET  | equity                 | engine       |           11 |      4 |      4 |         3 |              0 |           13 |                 0 |
|     932 | Equity.US.ADSK/USD           | POST_MARKET | equity                 | engine       |            6 |      2 |      4 |         0 |              0 |           20 |                 0 |
|    1184 | Equity.US.HPQ/USD            | REGULAR     | equity                 | engine       |           12 |      8 |      4 |         0 |              0 |           13 |                 4 |
|    1183 | Equity.US.HPE/USD            | REGULAR     | equity                 | engine       |           12 |      8 |      4 |         0 |              0 |           16 |                 4 |
|    1170 | Equity.US.HAL/USD            | POST_MARKET | equity                 | engine       |            9 |      3 |      4 |         2 |              0 |           19 |                 2 |
|    1170 | Equity.US.HAL/USD            | OVER_NIGHT  | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           23 |                 0 |
|    1194 | Equity.US.IBIT/USD           | REGULAR     | equity                 | engine       |           13 |      9 |      4 |         0 |              0 |           11 |                 2 |
|    2861 | Equity.US.SOFI/USD           | REGULAR     | equity                 | engine       |            7 |      3 |      4 |         0 |              0 |           15 |                 2 |
|    1114 | Equity.US.ES/USD             | REGULAR     | equity                 | engine       |           12 |      8 |      4 |         0 |              0 |           14 |                 8 |
|    3164 | Equity.US.BOT/USD            | POST_MARKET | equity                 | engine       |            6 |      1 |      4 |         1 |              0 |           15 |                 0 |
|    1005 | Equity.US.BTF/USD            | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           19 |                 0 |
|    1072 | Equity.US.DECK/USD           | REGULAR     | equity                 | engine       |            8 |      4 |      4 |         0 |              0 |           16 |                 1 |
|    1054 | Equity.US.CRWD/USD           | REGULAR     | equity                 | engine       |           11 |      6 |      4 |         1 |              0 |           18 |                 4 |
|    2746 | Equity.US.EFAV/USD           | REGULAR     | equity                 | engine       |            7 |      3 |      4 |         0 |              0 |            8 |                 1 |
|    3103 | Equity.US.SCZ/USD            | REGULAR     | equity                 | engine       |            7 |      3 |      4 |         0 |              0 |            7 |                 2 |
|    1041 | Equity.US.COF/USD            | POST_MARKET | equity                 | engine       |            7 |      2 |      4 |         1 |              0 |           21 |                 1 |
|    3097 | Crypto.SATUSD/USD            | REGULAR     | crypto                 | peer         |            5 |      1 |      4 |         0 |              0 |            1 |                 0 |
|    3055 | Equity.US.EWT/USD            | REGULAR     | equity                 | engine       |            8 |      4 |      4 |         0 |              0 |           14 |                 2 |
|    1053 | Equity.US.CRM/USD            | POST_MARKET | equity                 | engine       |            7 |      2 |      4 |         1 |              0 |           23 |                 3 |
|    3066 | Equity.US.PAYP/USD           | PRE_MARKET  | equity                 | engine       |           11 |      0 |      4 |         7 |              0 |           10 |                 0 |
|    1065 | Equity.US.D/USD              | REGULAR     | equity                 | engine       |           15 |     11 |      4 |         0 |              0 |           10 |                 2 |
|    1071 | Equity.US.DE/USD             | REGULAR     | equity                 | engine       |           14 |     10 |      4 |         0 |              0 |           11 |                 2 |
|    1060 | Equity.US.CTSH/USD           | REGULAR     | equity                 | engine       |           11 |      6 |      4 |         1 |              0 |           14 |                 3 |
|    3164 | Equity.US.BOT/USD            | PRE_MARKET  | equity                 | engine       |            6 |      1 |      4 |         1 |              0 |           15 |                 0 |
|    3066 | Equity.US.PAYP/USD           | POST_MARKET | equity                 | engine       |            8 |      0 |      4 |         4 |              0 |           13 |                 0 |
|    3054 | Equity.US.KORU/USD           | REGULAR     | equity                 | engine       |            8 |      4 |      4 |         0 |              0 |           14 |                 1 |
|    1086 | Equity.US.DOW/USD            | REGULAR     | equity                 | engine       |            9 |      5 |      4 |         0 |              0 |           17 |                 5 |
|    1026 | Equity.US.CFG/USD            | REGULAR     | equity                 | engine       |           15 |     11 |      4 |         0 |              0 |           11 |                 6 |
|    1093 | Equity.US.DXCM/USD           | REGULAR     | equity                 | engine       |           11 |      5 |      4 |         2 |              0 |           15 |                 4 |
|    1019 | Equity.US.CCI/USD            | REGULAR     | equity                 | engine       |           13 |      9 |      4 |         0 |              0 |           13 |                 5 |
|    1016 | Equity.US.CBOE/USD           | REGULAR     | equity                 | engine       |            6 |      2 |      4 |         0 |              0 |           19 |                 4 |
|    1015 | Equity.US.CB/USD             | REGULAR     | equity                 | engine       |           14 |     10 |      4 |         0 |              0 |           12 |                 6 |
|    1013 | Equity.US.CARR/USD           | REGULAR     | equity                 | engine       |            9 |      5 |      4 |         0 |              0 |           17 |                 9 |
|    2971 | Equity.US.EWJ/USD            | REGULAR     | equity                 | engine       |            9 |      5 |      4 |         0 |              0 |           16 |                 2 |
|    3299 | Equity.US.ABCL/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           13 |                 0 |
|    1057 | Equity.US.CSX/USD            | POST_MARKET | equity                 | engine       |            7 |      3 |      4 |         0 |              0 |           18 |                 5 |
|    3297 | Equity.US.IOVA/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           13 |                 0 |
|    1236 | Equity.US.KR/USD             | REGULAR     | equity                 | engine       |           15 |     10 |      4 |         1 |              0 |            9 |                 3 |
|     604 | Crypto.USD1/USD              | REGULAR     | crypto                 | peer         |           11 |      7 |      4 |         0 |              0 |            7 |                 0 |
|    1229 | Equity.US.KIM/USD            | REGULAR     | equity                 | engine       |           17 |     11 |      4 |         2 |              0 |            7 |                 1 |
|    1233 | Equity.US.KMI/USD            | REGULAR     | equity                 | engine       |           15 |     10 |      4 |         1 |              0 |           10 |                 2 |
|    3355 | Equity.US.POET/USD           | REGULAR     | equity                 | engine       |            7 |      2 |      4 |         1 |              0 |           13 |                 1 |
|    1250 | Equity.US.LRCX/USD           | REGULAR     | equity                 | engine       |           11 |      7 |      4 |         0 |              0 |           17 |                 6 |
|    1228 | Equity.US.KHC/USD            | POST_MARKET | equity                 | engine       |            7 |      2 |      4 |         1 |              0 |           20 |                 1 |
|     434 | Crypto.GHO/USD               | REGULAR     | crypto                 | peer         |            6 |      2 |      4 |         0 |              0 |           10 |                 0 |
|     187 | Crypto.BTT/USD               | REGULAR     | crypto                 | peer         |           10 |      6 |      4 |         0 |              0 |            9 |                 4 |
|    3303 | Equity.US.FLNC/USD           | REGULAR     | equity                 | engine       |            8 |      3 |      4 |         1 |              0 |           12 |                 0 |
|    3349 | Equity.US.SPMO/USD           | REGULAR     | equity                 | engine       |            9 |      4 |      4 |         1 |              0 |           10 |                 1 |
|    2769 | Equity.US.FLUT/USD           | POST_MARKET | equity                 | engine       |            8 |      0 |      4 |         4 |              0 |           15 |                 0 |
|    1239 | Equity.US.LDOS/USD           | PRE_MARKET  | equity                 | engine       |            4 |      0 |      4 |         0 |              0 |           20 |                 0 |
|     407 | Crypto.COQ/USD               | REGULAR     | crypto                 | peer         |           12 |      7 |      4 |         1 |              0 |            1 |                 1 |
|     228 | Crypto.FRAX/USD              | REGULAR     | crypto                 | peer         |           10 |      4 |      4 |         2 |              0 |           13 |                10 |
|    1235 | Equity.US.KO/USD             | OVER_NIGHT  | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           23 |                 0 |
|    2774 | Equity.US.GDXJ/USD           | OVER_NIGHT  | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           17 |                 0 |
|    2779 | Equity.US.GRAB/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      4 |         3 |              0 |           16 |                 0 |
|     305 | Crypto.SATS/USD              | REGULAR     | crypto                 | peer         |            8 |      4 |      4 |         0 |              0 |           17 |                 7 |
|    1284 | Equity.US.MOS/USD            | REGULAR     | equity                 | engine       |           13 |      8 |      4 |         1 |              0 |           12 |                 2 |
|    1291 | Equity.US.MSCI/USD           | REGULAR     | equity                 | engine       |            5 |      1 |      4 |         0 |              0 |           20 |                 0 |
|    3298 | Equity.US.AMBA/USD           | REGULAR     | equity                 | engine       |            5 |      0 |      4 |         1 |              0 |           13 |                 0 |
|    2815 | Equity.US.KWEB/USD           | POST_MARKET | equity                 | engine       |            9 |      0 |      4 |         5 |              0 |           14 |                 0 |
|    2799 | Equity.US.IONQ/USD           | REGULAR     | equity                 | engine       |            9 |      5 |      4 |         0 |              0 |           14 |                 0 |
|    2752 | Equity.US.EMXC/USD           | REGULAR     | equity                 | engine       |            7 |      3 |      4 |         0 |              0 |            8 |                 0 |
|    2747 | Equity.US.EFG/USD            | REGULAR     | equity                 | engine       |            8 |      4 |      4 |         0 |              0 |            8 |                 2 |
|      88 | Crypto.FDUSD/USD             | REGULAR     | crypto                 | peer         |           11 |      6 |      4 |         1 |              0 |           19 |                 6 |
|    2721 | Equity.US.BE/USD             | REGULAR     | equity                 | engine       |            6 |      2 |      4 |         0 |              0 |           16 |                 1 |
|    1440 | Equity.US.TTWO/USD           | PRE_MARKET  | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           21 |                 1 |
|     240 | Crypto.EURC/USD              | REGULAR     | crypto                 | peer         |            7 |      4 |      3 |         0 |              0 |           10 |                 6 |
|    3102 | Equity.US.IDEV/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |            8 |                 0 |
|    3354 | Equity.US.UMC/USD            | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           12 |                 0 |
|    1444 | Equity.US.UAL/USD            | REGULAR     | equity                 | engine       |           12 |      8 |      3 |         1 |              0 |           11 |                 5 |
|    1056 | Equity.US.CSGP/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           18 |                 4 |
|    1426 | Equity.US.TMO/USD            | REGULAR     | equity                 | engine       |           11 |      8 |      3 |         0 |              0 |           12 |                 4 |
|    1436 | Equity.US.TSM/USD            | REGULAR     | equity                 | engine       |           11 |      8 |      3 |         0 |              0 |           18 |                10 |
|     206 | Crypto.LEO/USD               | REGULAR     | crypto                 | peer         |           10 |      6 |      3 |         1 |              0 |           17 |                 7 |
|    1024 | Equity.US.CEG/USD            | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           20 |                 7 |
|    1028 | Equity.US.CHRW/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           19 |                 2 |
|    3107 | Equity.US.ACWX/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |            9 |                 0 |
|      94 | Crypto.MOVE/USD              | REGULAR     | crypto                 | peer         |           14 |     10 |      3 |         1 |              0 |           16 |                14 |
|    1044 | Equity.US.COP/USD            | REGULAR     | equity                 | engine       |           14 |     10 |      3 |         1 |              0 |           14 |                 3 |
|    1653 | Equity.HK.3988/HKD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |            4 |                 0 |
|    3355 | Equity.US.POET/USD           | PRE_MARKET  | equity                 | engine       |            8 |      2 |      3 |         3 |              0 |           11 |                 0 |
|    1692 | Equity.US.IEF/USD            | PRE_MARKET  | equity                 | engine       |           12 |      5 |      3 |         4 |              0 |           13 |                 5 |
|    3356 | Equity.US.QUBT/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           13 |                 1 |
|    1680 | Equity.US.BNDX/USD           | REGULAR     | equity                 | engine       |           11 |      8 |      3 |         0 |              0 |            8 |                 3 |
|     993 | Equity.US.BKR/USD            | POST_MARKET | equity                 | engine       |            6 |      2 |      3 |         1 |              0 |           20 |                 5 |
|     124 | Crypto.BABYDOGE/USD          | REGULAR     | crypto                 | peer         |            9 |      5 |      3 |         1 |              0 |           16 |                 8 |
|    3104 | Equity.US.IQLT/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |            9 |                 2 |
|    3111 | Equity.US.ESGE/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |            9 |                 0 |
|    1425 | Equity.US.TLT/USD            | PRE_MARKET  | equity                 | engine       |           11 |      6 |      3 |         2 |              0 |           17 |                 3 |
|    3112 | Equity.US.REET/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |            9 |                 1 |
|    1439 | Equity.US.TTD/USD            | REGULAR     | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           17 |                 4 |
|    1038 | Equity.US.CMS/USD            | REGULAR     | equity                 | engine       |           13 |     10 |      3 |         0 |              0 |           12 |                 5 |
|    1034 | Equity.US.CMCSA/USD          | REGULAR     | equity                 | engine       |           13 |      8 |      3 |         2 |              0 |           12 |                 2 |
|    2286 | Equity.US.EXE/USD            | REGULAR     | equity                 | engine       |            9 |      6 |      3 |         0 |              0 |           14 |                 3 |
|    1822 | Crypto.MCDX/USD              | REGULAR     | crypto                 | peer         |            7 |      4 |      3 |         0 |              0 |           10 |                 1 |
|    1454 | Equity.US.URTH/USD           | REGULAR     | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           11 |                 6 |
|     885 | Equity.HK.0003/HKD           | REGULAR     | equity                 | engine       |            5 |      2 |      3 |         0 |              0 |            4 |                 1 |
|     948 | Equity.US.AMCR/USD           | REGULAR     | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |           16 |                 8 |
|    3307 | Equity.US.USAR/USD           | REGULAR     | equity                 | engine       |            8 |      3 |      3 |         2 |              0 |           10 |                 0 |
|    1764 | Equity.US.VT/USD             | REGULAR     | equity                 | engine       |            8 |      4 |      3 |         1 |              0 |           16 |                 2 |
|    1756 | Equity.US.VGIT/USD           | REGULAR     | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |            9 |                 4 |
|     937 | Equity.US.AI/USD             | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           18 |                 1 |
|    3233 | Equity.US.BEKE/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      3 |         3 |              0 |           11 |                 0 |
|    3234 | Equity.US.TME/USD            | PRE_MARKET  | equity                 | engine       |            4 |      0 |      3 |         1 |              0 |           16 |                 0 |
|    3302 | Equity.US.NOK/USD            | REGULAR     | equity                 | engine       |            8 |      4 |      3 |         1 |              0 |           13 |                 1 |
|     928 | Equity.US.ADBE/USD           | REGULAR     | equity                 | engine       |           13 |     10 |      3 |         0 |              0 |           15 |                 4 |
|    1483 | Equity.US.WBD/USD            | POST_MARKET | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           18 |                 6 |
|    1732 | Equity.US.SCHX/USD           | REGULAR     | equity                 | engine       |           14 |     10 |      3 |         1 |              0 |            7 |                 4 |
|    3232 | Equity.US.LI/USD             | POST_MARKET | equity                 | engine       |            6 |      1 |      3 |         2 |              0 |           11 |                 0 |
|    3236 | Equity.US.P/USD              | POST_MARKET | equity                 | engine       |            6 |      0 |      3 |         3 |              0 |           11 |                 0 |
|    3306 | Equity.HK.7747/HKD           | REGULAR     | equity                 | engine       |            4 |      1 |      3 |         0 |              0 |            2 |                 0 |
|    1745 | Equity.US.TQQQ/USD           | PRE_MARKET  | equity                 | engine       |           11 |      5 |      3 |         3 |              0 |           14 |                 5 |
|    3239 | Equity.US.MDLN/USD           | POST_MARKET | equity                 | engine       |            5 |      2 |      3 |         0 |              0 |           11 |                 1 |
|     927 | Equity.US.ACN/USD            | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           20 |                 6 |
|     926 | Equity.US.ACGL/USD           | REGULAR     | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           18 |                 9 |
|    3237 | Equity.US.LITE/USD           | REGULAR     | equity                 | engine       |            7 |      3 |      3 |         1 |              0 |           13 |                 2 |
|     921 | Equity.US.A/USD              | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           18 |                 7 |
|    3318 | Equity.US.MUU/USD            | REGULAR     | equity                 | engine       |            6 |      2 |      3 |         1 |              0 |           12 |                 1 |
|     953 | Equity.US.AMT/USD            | REGULAR     | equity                 | engine       |           14 |     11 |      3 |         0 |              0 |           13 |                 7 |
|    1734 | Equity.US.SGOV/USD           | POST_MARKET | equity                 | engine       |           10 |      6 |      3 |         1 |              0 |           13 |                 2 |
|    1476 | Equity.US.VST/USD            | OVER_NIGHT  | equity                 | engine       |            6 |      1 |      3 |         2 |              0 |           20 |                 2 |
|     977 | Equity.US.AZN/USD            | PRE_MARKET  | equity                 | engine       |           11 |      5 |      3 |         3 |              0 |           17 |                 7 |
|     337 | FX.NZD/USD                   | REGULAR     | fx                     | engine       |           16 |     10 |      3 |         3 |              0 |            6 |                 4 |
|     983 | Equity.US.BBY/USD            | REGULAR     | equity                 | engine       |           15 |     11 |      3 |         1 |              0 |           12 |                 3 |
|     976 | Equity.US.AXP/USD            | POST_MARKET | equity                 | engine       |            8 |      4 |      3 |         1 |              0 |           22 |                 3 |
|    1752 | Equity.US.VCIT/USD           | REGULAR     | equity                 | engine       |            9 |      6 |      3 |         0 |              0 |           11 |                 7 |
|    3223 | Equity.US.URA/USD            | OVER_NIGHT  | equity                 | engine       |            3 |      0 |      3 |         0 |              0 |           17 |                 0 |
|    1723 | Equity.US.QQQM/USD           | PRE_MARKET  | equity                 | engine       |           10 |      4 |      3 |         3 |              0 |           16 |                 5 |
|     963 | Equity.US.APP/USD            | REGULAR     | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           21 |                 2 |
|     971 | Equity.US.AVB/USD            | REGULAR     | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |           20 |                10 |
|     415 | Crypto.DSOL/USD              | REGULAR     | crypto                 | peer         |            7 |      4 |      3 |         0 |              0 |            2 |                 2 |
|    3227 | Equity.US.ALNY/USD           | REGULAR     | equity                 | engine       |            5 |      1 |      3 |         1 |              0 |           12 |                 0 |
|     966 | Equity.US.ARKB/USD           | PRE_MARKET  | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           18 |                 6 |
|     970 | Equity.US.ATO/USD            | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           18 |                10 |
|     964 | Equity.US.APTV/USD           | REGULAR     | equity                 | engine       |            9 |      6 |      3 |         0 |              0 |           18 |                 0 |
|     955 | Equity.US.ANET/USD           | POST_MARKET | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           22 |                 9 |
|    3347 | Equity.US.PR/USD             | REGULAR     | equity                 | engine       |            8 |      4 |      3 |         1 |              0 |           11 |                 1 |
|     959 | Equity.US.APA/USD            | REGULAR     | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           19 |                 7 |
|    3228 | Equity.US.INSM/USD           | REGULAR     | equity                 | engine       |            5 |      1 |      3 |         1 |              0 |           12 |                 0 |
|     946 | Equity.US.AMAT/USD           | REGULAR     | equity                 | engine       |           13 |     10 |      3 |         0 |              0 |           17 |                 2 |
|    1299 | Equity.US.NCLH/USD           | REGULAR     | equity                 | engine       |            9 |      6 |      3 |         0 |              0 |           16 |                 5 |
|    1415 | Equity.US.TDG/USD            | REGULAR     | equity                 | engine       |            9 |      5 |      3 |         1 |              0 |           16 |                 4 |
|    3101 | Equity.US.ACWI/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |           10 |                 1 |
|    2986 | Crypto.XSGD/USD              | REGULAR     | crypto                 | peer         |            6 |      3 |      3 |         0 |              0 |            5 |                 0 |
|    2377 | Equity.US.TSLL/USD           | REGULAR     | equity                 | engine       |           11 |      7 |      3 |         1 |              0 |           11 |                 1 |
|    1188 | Equity.US.HSY/USD            | REGULAR     | equity                 | engine       |            9 |      6 |      3 |         0 |              0 |           16 |                 5 |
|    1337 | Equity.US.PEP/USD            | REGULAR     | equity                 | engine       |           15 |     11 |      3 |         1 |              0 |           10 |                 3 |
|    2375 | Equity.US.TEM/USD            | PRE_MARKET  | equity                 | engine       |           12 |      5 |      3 |         4 |              0 |           10 |                 3 |
|    1347 | Equity.US.PM/USD             | REGULAR     | equity                 | engine       |           13 |     10 |      3 |         0 |              0 |           12 |                 5 |
|    2853 | Equity.US.SLV/USD            | REGULAR     | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |           14 |                 2 |
|    1355 | Equity.US.PPLT/USD           | REGULAR     | equity                 | engine       |            9 |      5 |      3 |         1 |              0 |           14 |                 5 |
|    2869 | Equity.US.TCOM/USD           | PRE_MARKET  | equity                 | engine       |           12 |      4 |      3 |         5 |              0 |            9 |                 0 |
|    1365 | Equity.US.RCL/USD            | REGULAR     | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           17 |                 2 |
|    2378 | Equity.US.XPEV/USD           | REGULAR     | equity                 | engine       |            8 |      4 |      3 |         1 |              0 |           12 |                 3 |
|    1172 | Equity.US.HBAN/USD           | REGULAR     | equity                 | engine       |           12 |      9 |      3 |         0 |              0 |           12 |                 7 |
|    2368 | Equity.US.NVDL/USD           | REGULAR     | equity                 | engine       |            9 |      5 |      3 |         1 |              0 |           12 |                 0 |
|    2887 | Equity.US.VRT/USD            | OVER_NIGHT  | equity                 | engine       |            6 |      2 |      3 |         1 |              0 |           15 |                 2 |
|    2941 | Crypto.SYRUPUSDC/USD         | REGULAR     | crypto                 | peer         |            7 |      3 |      3 |         1 |              0 |            2 |                 0 |
|    1160 | Equity.US.GME/USD            | PRE_MARKET  | equity                 | engine       |           10 |      4 |      3 |         3 |              0 |           17 |                 3 |
|    1160 | Equity.US.GME/USD            | REGULAR     | equity                 | engine       |           12 |      8 |      3 |         1 |              0 |           15 |                 5 |
|    1147 | Equity.US.GD/USD             | REGULAR     | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |           15 |                 6 |
|    1138 | Equity.US.FITB/USD           | REGULAR     | equity                 | engine       |           14 |     10 |      3 |         1 |              0 |           10 |                 2 |
|    1140 | Equity.US.FOX/USD            | POST_MARKET | equity                 | engine       |            6 |      1 |      3 |         2 |              0 |           19 |                 0 |
|    1145 | Equity.US.FTV/USD            | REGULAR     | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |           14 |                 5 |
|    2366 | Equity.US.NIO/USD            | REGULAR     | equity                 | engine       |            8 |      3 |      3 |         2 |              0 |           12 |                 4 |
|    2826 | Equity.US.NBIS/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |           15 |                 3 |
|    1329 | Equity.US.PANW/USD           | PRE_MARKET  | equity                 | engine       |            9 |      3 |      3 |         3 |              0 |           20 |                 5 |
|    1202 | Equity.US.INTU/USD           | PRE_MARKET  | equity                 | engine       |           12 |      5 |      3 |         4 |              0 |           16 |                 6 |
|    2774 | Equity.US.GDXJ/USD           | REGULAR     | equity                 | engine       |            9 |      6 |      3 |         0 |              0 |           13 |                 0 |
|    1294 | Equity.US.MSTR/USD           | REGULAR     | equity                 | engine       |           12 |      8 |      3 |         1 |              0 |           19 |                 4 |
|    1306 | Equity.US.NKE/USD            | REGULAR     | equity                 | engine       |           10 |      6 |      3 |         1 |              0 |           17 |                 1 |
|    2731 | Equity.US.CELH/USD           | REGULAR     | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           15 |                 2 |
|    1269 | Equity.US.MDT/USD            | REGULAR     | equity                 | engine       |           11 |      7 |      3 |         1 |              0 |           14 |                 3 |
|    1257 | Equity.US.MA/USD             | POST_MARKET | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           20 |                 6 |
|    1298 | Equity.US.MU/USD             | REGULAR     | equity                 | engine       |           12 |      8 |      3 |         1 |              0 |           18 |                 4 |
|    1256 | Equity.US.LYV/USD            | REGULAR     | equity                 | engine       |            5 |      2 |      3 |         0 |              0 |           20 |                 2 |
|    1246 | Equity.US.LLY/USD            | REGULAR     | equity                 | engine       |           13 |     10 |      3 |         0 |              0 |           14 |                 4 |
|    1248 | Equity.US.LNT/USD            | REGULAR     | equity                 | engine       |           14 |     11 |      3 |         0 |              0 |           11 |                 3 |
|    2702 | Equity.US.AAAU/USD           | REGULAR     | equity                 | engine       |            8 |      4 |      3 |         1 |              0 |           17 |                 2 |
|    1214 | Equity.US.IVZ/USD            | REGULAR     | equity                 | engine       |           12 |      9 |      3 |         0 |              0 |           13 |                 5 |
|    2709 | Equity.US.ARKG/USD           | REGULAR     | equity                 | engine       |            8 |      4 |      3 |         1 |              0 |            9 |                 0 |
|    1231 | Equity.US.KLAC/USD           | REGULAR     | equity                 | engine       |           13 |      9 |      3 |         1 |              0 |           15 |                 3 |
|    1240 | Equity.US.LEN/USD            | REGULAR     | equity                 | engine       |            9 |      5 |      3 |         1 |              0 |           15 |                 6 |
|    1228 | Equity.US.KHC/USD            | OVER_NIGHT  | equity                 | engine       |            4 |      0 |      3 |         1 |              0 |           23 |                 0 |
|    1228 | Equity.US.KHC/USD            | REGULAR     | equity                 | engine       |           12 |      8 |      3 |         1 |              0 |           16 |                 1 |
|    1225 | Equity.US.KDP/USD            | POST_MARKET | equity                 | engine       |            6 |      0 |      3 |         3 |              0 |           18 |                 2 |
|    1325 | Equity.US.ORLY/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      3 |         4 |              0 |           19 |                 0 |
|    1226 | Equity.US.KEY/USD            | REGULAR     | equity                 | engine       |           14 |     10 |      3 |         1 |              0 |           10 |                 2 |
|    1208 | Equity.US.IRM/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      3 |         2 |              0 |           20 |                 0 |
|    1139 | Equity.US.FMC/USD            | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           17 |                 1 |
|    2884 | Equity.US.VIXY/USD           | REGULAR     | equity                 | engine       |            8 |      4 |      3 |         1 |              0 |            8 |                 0 |
|    1373 | Equity.US.RKLB/USD           | REGULAR     | equity                 | engine       |           17 |     11 |      3 |         3 |              0 |           11 |                 2 |
|    1094 | Equity.US.EA/USD             | PRE_MARKET  | equity                 | engine       |            8 |      3 |      3 |         2 |              0 |           18 |                 3 |
|    2971 | Equity.US.EWJ/USD            | POST_MARKET | equity                 | engine       |            6 |      0 |      3 |         3 |              0 |           19 |                 0 |
|    3025 | Equity.US.SILJ/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           15 |                 1 |
|    1396 | Equity.US.SPG/USD            | REGULAR     | equity                 | engine       |           13 |      9 |      3 |         1 |              0 |           12 |                 5 |
|    1397 | Equity.US.SPGI/USD           | REGULAR     | equity                 | engine       |           12 |      9 |      3 |         0 |              0 |           13 |                 6 |
|    1116 | Equity.US.ETN/USD            | OVER_NIGHT  | equity                 | engine       |            4 |      0 |      3 |         1 |              0 |           25 |                 0 |
|    1388 | Equity.US.SIVR/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      3 |         3 |              0 |           21 |                 0 |
|    1390 | Equity.US.SLB/USD            | REGULAR     | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |           18 |                 2 |
|    3025 | Equity.US.SILJ/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      3 |         2 |              0 |           17 |                 0 |
|    1390 | Equity.US.SLB/USD            | POST_MARKET | equity                 | engine       |           10 |      1 |      3 |         6 |              0 |           18 |                 0 |
|    3025 | Equity.US.SILJ/USD           | OVER_NIGHT  | equity                 | engine       |            5 |      0 |      3 |         2 |              0 |           17 |                 0 |
|    1384 | Equity.US.SBUX/USD           | REGULAR     | equity                 | engine       |           16 |     13 |      3 |         0 |              0 |           13 |                 3 |
|    3036 | Equity.US.SPYM/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      3 |         0 |              0 |           14 |                 2 |
|    3036 | Equity.US.SPYM/USD           | PRE_MARKET  | equity                 | engine       |            9 |      3 |      3 |         3 |              0 |           12 |                 3 |
|    1081 | Equity.US.DIS/USD            | REGULAR     | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |           20 |                 6 |
|    3048 | Equity.US.ONDS/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |           15 |                 3 |
|    1066 | Equity.US.DAL/USD            | REGULAR     | equity                 | engine       |           13 |     10 |      3 |         0 |              0 |           12 |                 5 |
|    3074 | Equity.US.FXI/USD            | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |           13 |                 5 |
|    3074 | Equity.US.FXI/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      3 |         2 |              0 |           14 |                 0 |
|    1418 | Equity.US.TECH/USD           | REGULAR     | equity                 | engine       |            8 |      5 |      3 |         0 |              0 |           15 |                 7 |
|    1410 | Equity.US.SYF/USD            | REGULAR     | equity                 | engine       |           12 |      9 |      3 |         0 |              0 |           16 |                 6 |
|    1384 | Equity.US.SBUX/USD           | POST_MARKET | equity                 | engine       |           10 |      7 |      3 |         0 |              0 |           19 |                 5 |
|    1093 | Equity.US.DXCM/USD           | PRE_MARKET  | equity                 | engine       |            8 |      0 |      3 |         5 |              0 |           18 |                 0 |
|    2943 | Equity.US.CPER/USD           | PRE_MARKET  | equity                 | engine       |            8 |      3 |      3 |         2 |              0 |           15 |                 2 |
|    1118 | Equity.US.EVRG/USD           | REGULAR     | equity                 | engine       |           13 |     10 |      3 |         0 |              0 |           11 |                 5 |
|    2997 | Equity.HK.2823/HKD           | REGULAR     | equity                 | engine       |            6 |      3 |      3 |         0 |              0 |            3 |                 0 |
|    1116 | Equity.US.ETN/USD            | REGULAR     | equity                 | engine       |           12 |      8 |      3 |         1 |              0 |           17 |                 5 |
|    1389 | Equity.US.SJM/USD            | REGULAR     | equity                 | engine       |            5 |      2 |      3 |         0 |              0 |           20 |                 7 |
|    2298 | Equity.US.SHOP/USD           | REGULAR     | equity                 | engine       |            9 |      5 |      3 |         1 |              0 |           10 |                 2 |
|    3351 | Equity.US.NU/USD             | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           11 |                 1 |
|    3077 | Crypto.SIREN/USD             | REGULAR     | crypto                 | peer         |            6 |      4 |      2 |         0 |              0 |           11 |                 0 |
|    2795 | Equity.US.IGE/USD            | REGULAR     | equity                 | engine       |           10 |      5 |      2 |         3 |              0 |           11 |                 1 |
|    1721 | Equity.US.NVO/USD            | PRE_MARKET  | equity                 | engine       |           12 |      6 |      2 |         4 |              0 |           13 |                 5 |
|    1721 | Equity.US.NVO/USD            | POST_MARKET | equity                 | engine       |            9 |      2 |      2 |         5 |              0 |           16 |                 2 |
|    3110 | Equity.US.IXN/USD            | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            9 |                 1 |
|    2929 | Equity.US.AIQ/USD            | POST_MARKET | equity                 | engine       |            5 |      1 |      2 |         2 |              0 |           19 |                 1 |
|    1729 | Equity.US.SCHD/USD           | REGULAR     | equity                 | engine       |           10 |      7 |      2 |         1 |              0 |            9 |                 4 |
|    2892 | Equity.US.XBI/USD            | REGULAR     | equity                 | engine       |           11 |      9 |      2 |         0 |              0 |           12 |                 2 |
|    1735 | Equity.US.SH/USD             | REGULAR     | equity                 | engine       |            9 |      6 |      2 |         1 |              0 |           12 |                 4 |
|    3225 | Equity.US.SNY/USD            | REGULAR     | equity                 | engine       |            6 |      3 |      2 |         1 |              0 |           11 |                 1 |
|    2418 | Equity.US.OKLO/USD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |           15 |                 0 |
|    2685 | Crypto.NFLXX/USD             | REGULAR     | crypto                 | peer         |            6 |      4 |      2 |         0 |              0 |            5 |                 0 |
|    3225 | Equity.US.SNY/USD            | PRE_MARKET  | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           12 |                 3 |
|    1730 | Equity.US.SCHF/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      2 |         1 |              0 |           12 |                 5 |
|    1744 | Equity.US.SQQQ/USD           | POST_MARKET | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           17 |                 6 |
|    2771 | Equity.US.FUTU/USD           | POST_MARKET | equity                 | engine       |            7 |      0 |      2 |         5 |              0 |           14 |                 1 |
|    2297 | Equity.US.QS/USD             | REGULAR     | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           15 |                 2 |
|    2722 | Equity.US.BIDU/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      2 |         1 |              0 |           15 |                 3 |
|    1690 | Equity.US.GRND/USD           | REGULAR     | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           16 |                 2 |
|    3223 | Equity.US.URA/USD            | REGULAR     | equity                 | engine       |            7 |      4 |      2 |         1 |              0 |           13 |                 3 |
|    3357 | Equity.US.CIEN/USD           | PRE_MARKET  | equity                 | engine       |           10 |      5 |      2 |         3 |              0 |            9 |                 0 |
|    1698 | Equity.US.IUSB/USD           | REGULAR     | equity                 | engine       |           11 |      9 |      2 |         0 |              0 |            9 |                 3 |
|    1705 | Equity.US.IWR/USD            | REGULAR     | equity                 | engine       |            5 |      2 |      2 |         1 |              0 |           15 |                 1 |
|    3074 | Equity.US.FXI/USD            | OVER_NIGHT  | equity                 | engine       |            3 |      1 |      2 |         0 |              0 |           16 |                 8 |
|    3175 | Equity.US.DKNG/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      2 |         1 |              0 |           13 |                 3 |
|    3224 | Equity.US.AGRO/USD           | POST_MARKET | equity                 | engine       |            7 |      1 |      2 |         4 |              0 |           15 |                 1 |
|    2353 | Equity.US.BMNR/USD           | REGULAR     | equity                 | engine       |            9 |      5 |      2 |         2 |              0 |           15 |                 3 |
|    2760 | Equity.US.EWZ/USD            | REGULAR     | equity                 | engine       |           11 |      6 |      2 |         3 |              0 |           11 |                 2 |
|    1712 | Equity.US.LQD/USD            | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           11 |                 4 |
|    1714 | Equity.US.MBB/USD            | REGULAR     | equity                 | engine       |            9 |      6 |      2 |         1 |              0 |           13 |                 3 |
|    2911 | Equity.US.PURR/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      2 |         1 |              0 |           17 |                 2 |
|    2760 | Equity.US.EWZ/USD            | PRE_MARKET  | equity                 | engine       |            9 |      4 |      2 |         3 |              0 |           13 |                 3 |
|    2276 | Equity.US.BTDR/USD           | REGULAR     | equity                 | engine       |            5 |      2 |      2 |         1 |              0 |           12 |                 1 |
|    3319 | Equity.US.MVLL/USD           | PRE_MARKET  | equity                 | engine       |            9 |      4 |      2 |         3 |              0 |           10 |                 2 |
|    1745 | Equity.US.TQQQ/USD           | POST_MARKET | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           17 |                 6 |
|    2377 | Equity.US.TSLL/USD           | PRE_MARKET  | equity                 | engine       |           11 |      5 |      2 |         4 |              0 |           11 |                 2 |
|    1753 | Equity.US.VCSH/USD           | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           10 |                 6 |
|    1934 | Equity.HK.2057/HKD           | REGULAR     | equity                 | engine       |            7 |      4 |      2 |         1 |              0 |            3 |                 1 |
|    2860 | Equity.US.SNOW/USD           | REGULAR     | equity                 | engine       |            8 |      4 |      2 |         2 |              0 |           10 |                 2 |
|    1739 | Equity.US.SOXX/USD           | PRE_MARKET  | equity                 | engine       |           10 |      5 |      2 |         3 |              0 |           15 |                 7 |
|    1739 | Equity.US.SOXX/USD           | POST_MARKET | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           18 |                 6 |
|    3233 | Equity.US.BEKE/USD           | PRE_MARKET  | equity                 | engine       |            6 |      1 |      2 |         3 |              0 |           11 |                 0 |
|    3235 | Equity.US.NTES/USD           | PRE_MARKET  | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           12 |                 2 |
|    2863 | Equity.US.SOXL/USD           | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           13 |                 1 |
|    1837 | Crypto.QQQX/USD              | REGULAR     | crypto                 | peer         |            9 |      7 |      2 |         0 |              0 |            6 |                 4 |
|    3234 | Equity.US.TME/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      2 |         3 |              0 |           15 |                 0 |
|    2378 | Equity.US.XPEV/USD           | POST_MARKET | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           13 |                 3 |
|    3234 | Equity.US.TME/USD            | REGULAR     | equity                 | engine       |            7 |      4 |      2 |         1 |              0 |           13 |                 4 |
|    2289 | Equity.US.HIMS/USD           | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           14 |                 1 |
|    2377 | Equity.US.TSLL/USD           | POST_MARKET | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           14 |                 3 |
|    2943 | Equity.US.CPER/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      2 |         4 |              0 |           17 |                 0 |
|    2291 | Equity.US.KRE/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           13 |                 2 |
|    2815 | Equity.US.KWEB/USD           | REGULAR     | equity                 | engine       |           11 |      7 |      2 |         2 |              0 |           12 |                 2 |
|    3165 | Equity.US.BB/USD             | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           14 |                 3 |
|    1743 | Equity.US.SPYV/USD           | REGULAR     | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           15 |                 2 |
|    2419 | Equity.US.STRC/USD           | REGULAR     | equity                 | engine       |            9 |      6 |      2 |         1 |              0 |           11 |                 1 |
|    1749 | Equity.US.VALE/USD           | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           12 |                 3 |
|    2298 | Equity.US.SHOP/USD           | POST_MARKET | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           11 |                 4 |
|    2869 | Equity.US.TCOM/USD           | POST_MARKET | equity                 | engine       |            8 |      1 |      2 |         5 |              0 |           13 |                 0 |
|    2815 | Equity.US.KWEB/USD           | PRE_MARKET  | equity                 | engine       |           11 |      5 |      2 |         4 |              0 |           12 |                 2 |
|    3280 | Equity.US.BILI/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      2 |         1 |              0 |           14 |                 3 |
|    3141 | Equity.US.ASTS/USD           | REGULAR     | equity                 | engine       |           10 |      6 |      2 |         2 |              0 |           13 |                 2 |
|    3287 | Equity.US.AAOI/USD           | POST_MARKET | equity                 | engine       |            9 |      6 |      2 |         1 |              0 |           12 |                 3 |
|    3141 | Equity.US.ASTS/USD           | PRE_MARKET  | equity                 | engine       |           12 |      7 |      2 |         3 |              0 |           11 |                 3 |
|    3230 | Equity.US.ZM/USD             | REGULAR     | equity                 | engine       |            9 |      5 |      2 |         2 |              0 |           11 |                 1 |
|    2798 | Equity.US.INDA/USD           | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           14 |                 4 |
|    3284 | Equity.US.AVEX/USD           | PRE_MARKET  | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           13 |                 2 |
|    1681 | Equity.US.BSV/USD            | REGULAR     | equity                 | engine       |           12 |      9 |      2 |         1 |              0 |            9 |                 3 |
|       8 | Crypto.USDT/USD              | REGULAR     | crypto                 | peer         |           11 |      8 |      2 |         1 |              0 |           14 |                 9 |
|    1673 | Equity.US.AGG/USD            | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           11 |                 4 |
|    1112 | Equity.US.EQT/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           17 |                 5 |
|    1176 | Equity.US.HIG/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           16 |                 7 |
|    1168 | Equity.US.GS/USD             | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           17 |                 8 |
|    1166 | Equity.US.GPN/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           17 |                 1 |
|    1160 | Equity.US.GME/USD            | POST_MARKET | equity                 | engine       |            7 |      3 |      2 |         2 |              0 |           20 |                 4 |
|    1152 | Equity.US.GEV/USD            | POST_MARKET | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           19 |                 8 |
|    1144 | Equity.US.FTNT/USD           | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           15 |                 3 |
|    1130 | Equity.US.FCX/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           20 |                 5 |
|    1129 | Equity.US.FBTC/USD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           16 |                 2 |
|    1133 | Equity.US.FE/USD             | REGULAR     | equity                 | engine       |           13 |     11 |      2 |         0 |              0 |           12 |                 6 |
|    1127 | Equity.US.FANG/USD           | POST_MARKET | equity                 | engine       |            6 |      0 |      2 |         4 |              0 |           18 |                 3 |
|    1122 | Equity.US.EXPD/USD           | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           18 |                 8 |
|    1119 | Equity.US.EW/USD             | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           18 |                 8 |
|    1105 | Equity.US.EMN/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           15 |                 3 |
|    1192 | Equity.US.HYG/USD            | REGULAR     | equity                 | engine       |           13 |     11 |      2 |         0 |              0 |           10 |                 4 |
|    1095 | Equity.US.EBAY/USD           | POST_MARKET | equity                 | engine       |            8 |      1 |      2 |         5 |              0 |           21 |                 3 |
|    1095 | Equity.US.EBAY/USD           | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           20 |                 5 |
|    1104 | Equity.US.ELV/USD            | REGULAR     | equity                 | engine       |           15 |     12 |      2 |         1 |              0 |           10 |                 4 |
|    1094 | Equity.US.EA/USD             | POST_MARKET | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |           19 |                 7 |
|    1097 | Equity.US.ED/USD             | REGULAR     | equity                 | engine       |            9 |      6 |      2 |         1 |              0 |           17 |                 8 |
|    1090 | Equity.US.DUK/USD            | REGULAR     | equity                 | engine       |           16 |     12 |      2 |         2 |              0 |           10 |                 3 |
|    1082 | Equity.US.DLR/USD            | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           18 |                 5 |
|    1084 | Equity.US.DOC/USD            | REGULAR     | equity                 | engine       |           13 |     11 |      2 |         0 |              0 |           12 |                 3 |
|    1063 | Equity.US.CVX/USD            | POST_MARKET | equity                 | engine       |           16 |     12 |      2 |         2 |              0 |           13 |                 4 |
|    1063 | Equity.US.CVX/USD            | REGULAR     | equity                 | engine       |           16 |     13 |      2 |         1 |              0 |           13 |                 3 |
|    1076 | Equity.US.DG/USD             | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           18 |                 4 |
|    1067 | Equity.US.DASH/USD           | POST_MARKET | equity                 | engine       |            6 |      3 |      2 |         1 |              0 |           22 |                 1 |
|    1178 | Equity.US.HLT/USD            | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           15 |                 5 |
|    1187 | Equity.US.HST/USD            | REGULAR     | equity                 | engine       |           13 |     11 |      2 |         0 |              0 |           11 |                 3 |
|    1055 | Equity.US.CSCO/USD           | PRE_MARKET  | equity                 | engine       |           12 |      6 |      2 |         4 |              0 |           18 |                 4 |
|    1321 | Equity.US.OKE/USD            | REGULAR     | equity                 | engine       |           13 |     10 |      2 |         1 |              0 |           12 |                 5 |
|    1363 | Equity.US.QQQ/USD            | PRE_MARKET  | equity                 | engine       |           14 |      8 |      2 |         4 |              0 |           18 |                 2 |
|    1375 | Equity.US.RMD/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           19 |                 5 |
|    1368 | Equity.US.REGN/USD           | POST_MARKET | equity                 | engine       |            6 |      2 |      2 |         2 |              0 |           20 |                 0 |
|    1362 | Equity.US.QCOM/USD           | PRE_MARKET  | equity                 | engine       |            9 |      4 |      2 |         3 |              0 |           21 |                 7 |
|    1369 | Equity.US.RF/USD             | REGULAR     | equity                 | engine       |           12 |      9 |      2 |         1 |              0 |           13 |                 2 |
|    1350 | Equity.US.PNW/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           20 |                 2 |
|    1337 | Equity.US.PEP/USD            | POST_MARKET | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |           19 |                11 |
|    1335 | Equity.US.PDD/USD            | OVER_NIGHT  | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |           23 |                 7 |
|    1335 | Equity.US.PDD/USD            | REGULAR     | equity                 | engine       |           11 |      9 |      2 |         0 |              0 |           18 |                 5 |
|    1332 | Equity.US.PAYX/USD           | REGULAR     | equity                 | engine       |           11 |      9 |      2 |         0 |              0 |           15 |                 5 |
|    1334 | Equity.US.PCG/USD            | REGULAR     | equity                 | engine       |           11 |      8 |      2 |         1 |              0 |           13 |                 3 |
|    1323 | Equity.US.ON/USD             | REGULAR     | equity                 | engine       |           10 |      7 |      2 |         1 |              0 |           17 |                 5 |
|    1303 | Equity.US.NEM/USD            | POST_MARKET | equity                 | engine       |           10 |      7 |      2 |         1 |              0 |           18 |                 6 |
|    1193 | Equity.US.IAU/USD            | PRE_MARKET  | equity                 | engine       |            7 |      3 |      2 |         2 |              0 |           21 |                 6 |
|    1290 | Equity.US.MS/USD             | REGULAR     | equity                 | engine       |           12 |     10 |      2 |         0 |              0 |           13 |                 4 |
|    1268 | Equity.US.MDLZ/USD           | POST_MARKET | equity                 | engine       |            8 |      1 |      2 |         5 |              0 |           18 |                 0 |
|    1259 | Equity.US.MAR/USD            | PRE_MARKET  | equity                 | engine       |            7 |      1 |      2 |         4 |              0 |           19 |                 0 |
|    1254 | Equity.US.LW/USD             | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |           18 |                 2 |
|    1247 | Equity.US.LMT/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           20 |                 8 |
|    1252 | Equity.US.LUV/USD            | REGULAR     | equity                 | engine       |           12 |      9 |      2 |         1 |              0 |           13 |                 4 |
|    1249 | Equity.US.LOW/USD            | REGULAR     | equity                 | engine       |           10 |      7 |      2 |         1 |              0 |           15 |                 5 |
|    1238 | Equity.US.L/USD              | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           17 |                 6 |
|    1225 | Equity.US.KDP/USD            | REGULAR     | equity                 | engine       |           11 |      7 |      2 |         2 |              0 |           13 |                 4 |
|    1230 | Equity.US.KKR/USD            | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           17 |                 3 |
|    1212 | Equity.US.ITW/USD            | REGULAR     | equity                 | engine       |           11 |      9 |      2 |         0 |              0 |           13 |                 6 |
|    1204 | Equity.US.IP/USD             | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           15 |                 7 |
|    1064 | Equity.US.CZR/USD            | REGULAR     | equity                 | engine       |           10 |      7 |      2 |         1 |              0 |           14 |                 6 |
|    1062 | Equity.US.CVS/USD            | REGULAR     | equity                 | engine       |           18 |     15 |      2 |         1 |              0 |            7 |                 1 |
|    1387 | Equity.US.SHW/USD            | REGULAR     | equity                 | engine       |           12 |      9 |      2 |         1 |              0 |           13 |                 5 |
|     346 | Metal.XAU/USD                | REGULAR     | metal                  | engine       |           13 |     10 |      2 |         1 |              0 |            8 |                 7 |
|     934 | Equity.US.AEP/USD            | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           16 |                 7 |
|     933 | Equity.US.AEE/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           17 |                 9 |
|     923 | Equity.US.ABBV/USD           | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           19 |                10 |
|     916 | Equity.HK.9888/HKD           | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |            2 |                 1 |
|     917 | Equity.HK.9988/HKD           | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |            2 |                 1 |
|     912 | Equity.HK.3690/HKD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |            3 |                 2 |
|     908 | Equity.HK.2319/HKD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |            3 |                 2 |
|     907 | Equity.HK.2269/HKD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |            3 |                 2 |
|     903 | Equity.HK.1398/HKD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            4 |                 0 |
|     895 | Equity.HK.0939/HKD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            4 |                 1 |
|     893 | Equity.HK.0700/HKD           | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |            2 |                 1 |
|     503 | Crypto.MSOL/USD              | REGULAR     | crypto                 | peer         |           11 |      8 |      2 |         1 |              0 |           12 |                 3 |
|     338 | FX.USD/CAD                   | REGULAR     | fx                     | engine       |           17 |     13 |      2 |         2 |              0 |            7 |                 5 |
|     936 | Equity.US.AFL/USD            | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           17 |                10 |
|     323 | FX.EUR/JPY                   | REGULAR     | fx                     | engine       |            9 |      6 |      2 |         1 |              0 |           12 |                 8 |
|     291 | Crypto.WAVES/USD             | REGULAR     | crypto                 | peer         |            9 |      7 |      2 |         0 |              0 |           10 |                 9 |
|     257 | Crypto.IOTX/USD              | REGULAR     | crypto                 | peer         |           10 |      6 |      2 |         2 |              0 |           16 |                15 |
|     267 | Crypto.RLB/USD               | REGULAR     | crypto                 | peer         |            8 |      6 |      2 |         0 |              0 |            3 |                 0 |
|     207 | FundingRate.Binance.ETH/USDT | REGULAR     | funding-rate           | peer         |            3 |      1 |      2 |         0 |              0 |            0 |                 0 |
|     192 | Crypto.KCS/USD               | REGULAR     | crypto                 | peer         |           15 |     13 |      2 |         0 |              0 |            5 |                 3 |
|     185 | Crypto.NEXO/USD              | REGULAR     | crypto                 | peer         |           21 |     18 |      2 |         1 |              0 |            4 |                 2 |
|     167 | Crypto.AMP/USD               | REGULAR     | crypto                 | peer         |           12 |      9 |      2 |         1 |              0 |           19 |                11 |
|     161 | Crypto.GNO/USD               | REGULAR     | crypto                 | peer         |           12 |      9 |      2 |         1 |              0 |           18 |                15 |
|     152 | Crypto.MOG/USD               | REGULAR     | crypto                 | peer         |            8 |      5 |      2 |         1 |              0 |           17 |                11 |
|     109 | Crypto.WELL/USD              | REGULAR     | crypto                 | peer         |           10 |      7 |      2 |         1 |              0 |           16 |                15 |
|     103 | Crypto.WBTC/USD              | REGULAR     | crypto                 | peer         |           11 |      8 |      2 |         1 |              0 |           16 |                10 |
|     929 | Equity.US.ADI/USD            | REGULAR     | equity                 | engine       |           12 |      8 |      2 |         2 |              0 |           14 |                 6 |
|     932 | Equity.US.ADSK/USD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           19 |                 2 |
|    1057 | Equity.US.CSX/USD            | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           15 |                 2 |
|     989 | Equity.US.BITB/USD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           17 |                 3 |
|    1046 | Equity.US.COST/USD           | REGULAR     | equity                 | engine       |           16 |     13 |      2 |         1 |              0 |           13 |                 4 |
|    1049 | Equity.US.CPNG/USD           | REGULAR     | equity                 | engine       |           11 |      8 |      2 |         1 |              0 |           15 |                 3 |
|    1043 | Equity.US.COO/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           16 |                 3 |
|    1030 | Equity.US.CI/USD             | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           15 |                 7 |
|    1031 | Equity.US.CINF/USD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           18 |                 3 |
|    1018 | Equity.US.CCEP/USD           | REGULAR     | equity                 | engine       |           12 |      9 |      2 |         1 |              0 |           14 |                 5 |
|    1011 | Equity.US.CAH/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           17 |                 7 |
|    1008 | Equity.US.BXP/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           18 |                 3 |
|    1003 | Equity.US.BTCO/USD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |           17 |                 3 |
|     993 | Equity.US.BKR/USD            | PRE_MARKET  | equity                 | engine       |            7 |      4 |      2 |         1 |              0 |           19 |                 8 |
|     993 | Equity.US.BKR/USD            | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           16 |                 7 |
|     987 | Equity.US.BG/USD             | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |           18 |                 1 |
|     985 | Equity.US.BEN/USD            | REGULAR     | equity                 | engine       |           13 |     11 |      2 |         0 |              0 |           12 |                 4 |
|     938 | Equity.US.AIG/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           18 |                 9 |
|     982 | Equity.US.BAX/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           17 |                 4 |
|     980 | Equity.US.BAC/USD            | OVER_NIGHT  | equity                 | engine       |            4 |      1 |      2 |         1 |              0 |           25 |                11 |
|     980 | Equity.US.BAC/USD            | PRE_MARKET  | equity                 | engine       |           10 |      6 |      2 |         2 |              0 |           19 |                 6 |
|     976 | Equity.US.AXP/USD            | REGULAR     | equity                 | engine       |           11 |      9 |      2 |         0 |              0 |           19 |                 7 |
|     979 | Equity.US.BA/USD             | REGULAR     | equity                 | engine       |           16 |     13 |      2 |         1 |              0 |           13 |                 4 |
|     981 | Equity.US.BALL/USD           | REGULAR     | equity                 | engine       |           11 |      9 |      2 |         0 |              0 |           14 |                 6 |
|     960 | Equity.US.APD/USD            | REGULAR     | equity                 | engine       |           15 |     12 |      2 |         1 |              0 |           15 |                 3 |
|     951 | Equity.US.AMGN/USD           | POST_MARKET | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |           21 |                 6 |
|     957 | Equity.US.AON/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      2 |         0 |              0 |           18 |                 7 |
|     946 | Equity.US.AMAT/USD           | PRE_MARKET  | equity                 | engine       |            9 |      5 |      2 |         2 |              0 |           21 |                 5 |
|     952 | Equity.US.AMP/USD            | REGULAR     | equity                 | engine       |            9 |      6 |      2 |         1 |              0 |           17 |                 1 |
|     940 | Equity.US.AJG/USD            | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           18 |                 2 |
|    1373 | Equity.US.RKLB/USD           | PRE_MARKET  | equity                 | engine       |           13 |      8 |      2 |         3 |              0 |           15 |                 6 |
|    1186 | Equity.US.HSIC/USD           | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           17 |                 8 |
|    1381 | Equity.US.RTX/USD            | REGULAR     | equity                 | engine       |           15 |     12 |      2 |         1 |              0 |           13 |                 6 |
|    1495 | Equity.US.WY/USD             | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           14 |                 5 |
|    1432 | Equity.US.TROW/USD           | REGULAR     | equity                 | engine       |            8 |      6 |      2 |         0 |              0 |           15 |                 6 |
|    1427 | Equity.US.TMUS/USD           | REGULAR     | equity                 | engine       |           13 |     10 |      2 |         1 |              0 |           12 |                 3 |
|    1434 | Equity.US.TSCO/USD           | REGULAR     | equity                 | engine       |            9 |      5 |      2 |         2 |              0 |           14 |                 7 |
|    1446 | Equity.US.UDR/USD            | REGULAR     | equity                 | engine       |           11 |      8 |      2 |         1 |              0 |           12 |                 6 |
|    1449 | Equity.US.UNH/USD            | REGULAR     | equity                 | engine       |           14 |     11 |      2 |         1 |              0 |           12 |                 5 |
|    1464 | Equity.US.USB/USD            | REGULAR     | equity                 | engine       |           11 |      8 |      2 |         1 |              0 |           12 |                 4 |
|    1448 | Equity.US.ULTA/USD           | POST_MARKET | equity                 | engine       |            7 |      2 |      2 |         3 |              0 |           19 |                 1 |
|    1469 | Equity.US.VLO/USD            | REGULAR     | equity                 | engine       |            9 |      6 |      2 |         1 |              0 |           14 |                 6 |
|    1467 | Equity.US.V/USD              | REGULAR     | equity                 | engine       |           11 |      8 |      2 |         1 |              0 |           18 |                 7 |
|    1476 | Equity.US.VST/USD            | PRE_MARKET  | equity                 | engine       |           12 |      5 |      2 |         5 |              0 |           15 |                 4 |
|    1487 | Equity.US.WELL/USD           | REGULAR     | equity                 | engine       |           10 |      7 |      2 |         1 |              0 |           13 |                 5 |
|    1489 | Equity.US.WM/USD             | REGULAR     | equity                 | engine       |           12 |      9 |      2 |         1 |              0 |           11 |                 2 |
|    1501 | Equity.US.YUM/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           18 |                 4 |
|    1391 | Equity.US.SMCI/USD           | POST_MARKET | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           18 |                 6 |
|    1491 | Equity.US.WMT/USD            | REGULAR     | equity                 | engine       |           10 |      7 |      2 |         1 |              0 |           19 |                 6 |
|    1500 | Equity.US.XYL/USD            | REGULAR     | equity                 | engine       |            8 |      5 |      2 |         1 |              0 |           15 |                 5 |
|    1617 | Equity.HK.0288/HKD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            4 |                 0 |
|    1624 | Equity.HK.0762/HKD           | REGULAR     | equity                 | engine       |            6 |      3 |      2 |         1 |              0 |            4 |                 1 |
|    1623 | Equity.HK.0688/HKD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            4 |                 1 |
|    1627 | Equity.HK.0857/HKD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |            3 |                 1 |
|    1631 | Equity.HK.0960/HKD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            4 |                 0 |
|    1641 | Equity.HK.1876/HKD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            4 |                 0 |
|    1638 | Equity.HK.1177/HKD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            4 |                 0 |
|    1645 | Equity.HK.2313/HKD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |            3 |                 2 |
|    1647 | Equity.HK.2359/HKD           | REGULAR     | equity                 | engine       |            7 |      5 |      2 |         0 |              0 |            3 |                 2 |
|    1656 | Equity.HK.9901/HKD           | REGULAR     | equity                 | engine       |            6 |      4 |      2 |         0 |              0 |            4 |                 1 |
|    1421 | Equity.US.TFC/USD            | REGULAR     | equity                 | engine       |           11 |      8 |      2 |         1 |              0 |           11 |                 3 |
|    3409 | Equity.US.ECHO/USD           | REGULAR     | equity                 | engine       |            6 |      3 |      2 |         1 |              0 |            7 |                 0 |
|    1392 | Equity.US.SNA/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      2 |         0 |              0 |           20 |                 5 |
|    1379 | Equity.US.ROST/USD           | REGULAR     | equity                 | engine       |           10 |      8 |      2 |         0 |              0 |           16 |                 7 |
|    1384 | Equity.US.SBUX/USD           | PRE_MARKET  | equity                 | engine       |           13 |      8 |      2 |         3 |              0 |           16 |                 6 |
|     930 | Equity.US.ADM/USD            | OVER_NIGHT  | equity                 | engine       |            5 |      0 |      1 |         4 |              0 |           25 |                 0 |
|    1379 | Equity.US.ROST/USD           | POST_MARKET | equity                 | engine       |            5 |      0 |      1 |         4 |              0 |           21 |                 0 |
|    1626 | Equity.HK.0836/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1625 | Equity.HK.0823/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    2316 | Crypto.2Z/USD                | REGULAR     | crypto                 | peer         |           12 |     11 |      1 |         0 |              0 |            9 |                 7 |
|     954 | Equity.US.AMZN/USD           | POST_MARKET | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           23 |                10 |
|    2364 | Equity.US.JD/USD             | OVER_NIGHT  | equity                 | engine       |            6 |      0 |      1 |         5 |              0 |           19 |                 0 |
|     966 | Equity.US.ARKB/USD           | POST_MARKET | equity                 | engine       |            9 |      8 |      1 |         0 |              0 |           16 |                 4 |
|    2353 | Equity.US.BMNR/USD           | POST_MARKET | equity                 | engine       |            6 |      4 |      1 |         1 |              0 |           17 |                 6 |
|    3229 | Equity.US.VOD/USD            | REGULAR     | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           11 |                 4 |
|    1618 | Equity.HK.0291/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1620 | Equity.HK.0322/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            4 |                 2 |
|     979 | Equity.US.BA/USD             | PRE_MARKET  | equity                 | engine       |           12 |      8 |      1 |         3 |              0 |           18 |                 5 |
|    3226 | Equity.US.ERIC/USD           | REGULAR     | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           12 |                 3 |
|     984 | Equity.US.BDX/USD            | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           18 |                 0 |
|    3224 | Equity.US.AGRO/USD           | PRE_MARKET  | equity                 | engine       |            6 |      0 |      1 |         5 |              0 |           16 |                 0 |
|     930 | Equity.US.ADM/USD            | REGULAR     | equity                 | engine       |            8 |      7 |      1 |         0 |              0 |           22 |                 8 |
|    1633 | Equity.HK.0981/HKD           | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |            2 |                 1 |
|    3222 | Equity.US.ARGX/USD           | POST_MARKET | equity                 | engine       |            5 |      1 |      1 |         3 |              0 |           12 |                 0 |
|    1634 | Equity.HK.1024/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 1 |
|     913 | Equity.HK.6690/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     914 | Equity.HK.9618/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    3257 | Equity.HK.0100/HKD           | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |            2 |                 0 |
|    3237 | Equity.US.LITE/USD           | POST_MARKET | equity                 | engine       |            6 |      4 |      1 |         1 |              0 |           14 |                 4 |
|    3237 | Equity.US.LITE/USD           | PRE_MARKET  | equity                 | engine       |            8 |      4 |      1 |         3 |              0 |           12 |                 4 |
|    1708 | Equity.US.JEPQ/USD           | POST_MARKET | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           17 |                 6 |
|     915 | Equity.HK.9633/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1363 | Equity.US.QQQ/USD            | POST_MARKET | equity                 | engine       |           11 |      8 |      1 |         2 |              0 |           21 |                 6 |
|    3239 | Equity.US.MDLN/USD           | REGULAR     | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           11 |                 1 |
|    1636 | Equity.HK.1099/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     924 | Equity.US.ABNB/USD           | POST_MARKET | equity                 | engine       |            8 |      1 |      1 |         6 |              0 |           21 |                 2 |
|     928 | Equity.US.ADBE/USD           | PRE_MARKET  | equity                 | engine       |            9 |      5 |      1 |         3 |              0 |           19 |                 5 |
|    3232 | Equity.US.LI/USD             | REGULAR     | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           12 |                 2 |
|    1635 | Equity.HK.1088/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1637 | Equity.HK.1113/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1619 | Equity.HK.0316/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    3222 | Equity.US.ARGX/USD           | REGULAR     | equity                 | engine       |            6 |      4 |      1 |         1 |              0 |           11 |                 6 |
|    1054 | Equity.US.CRWD/USD           | PRE_MARKET  | equity                 | engine       |           10 |      5 |      1 |         4 |              0 |           19 |                 7 |
|    3143 | Equity.US.RDW/USD            | POST_MARKET | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           14 |                 2 |
|    3143 | Equity.US.RDW/USD            | REGULAR     | equity                 | engine       |            6 |      4 |      1 |         1 |              0 |           13 |                 0 |
|    1490 | Equity.US.WMB/USD            | REGULAR     | equity                 | engine       |           12 |     10 |      1 |         1 |              0 |           11 |                 3 |
|    3142 | Equity.US.LUNR/USD           | REGULAR     | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           13 |                 1 |
|    3151 | Equity.US.MSBT/USD           | REGULAR     | equity                 | engine       |            6 |      4 |      1 |         1 |              0 |           12 |                 2 |
|    1032 | Equity.US.CL/USD             | REGULAR     | equity                 | engine       |            9 |      8 |      1 |         0 |              0 |           17 |                 8 |
|    1033 | Equity.US.CLX/USD            | REGULAR     | equity                 | engine       |            8 |      7 |      1 |         0 |              0 |           18 |                 8 |
|    1039 | Equity.US.CNC/USD            | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           18 |                 8 |
|    1035 | Equity.US.CME/USD            | REGULAR     | equity                 | engine       |           16 |     14 |      1 |         1 |              0 |            9 |                 2 |
|    3109 | Equity.US.IOO/USD            | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            9 |                 5 |
|    1486 | Equity.US.WEC/USD            | REGULAR     | equity                 | engine       |            6 |      4 |      1 |         1 |              0 |           17 |                 7 |
|    1050 | Equity.US.CPRT/USD           | REGULAR     | equity                 | engine       |            8 |      7 |      1 |         0 |              0 |           17 |                 4 |
|    1384 | Equity.US.SBUX/USD           | OVER_NIGHT  | equity                 | engine       |            5 |      0 |      1 |         4 |              0 |           24 |                 0 |
|    1041 | Equity.US.COF/USD            | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           21 |                 8 |
|    2382 | Crypto.MET/USD               | REGULAR     | crypto                 | peer         |            8 |      7 |      1 |         0 |              0 |           11 |                10 |
|    1763 | Equity.US.VONG/USD           | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           15 |                 1 |
|    1485 | Equity.US.WDC/USD            | PRE_MARKET  | equity                 | engine       |            9 |      5 |      1 |         3 |              0 |           17 |                 6 |
|    1014 | Equity.US.CAT/USD            | REGULAR     | equity                 | engine       |           10 |      9 |      1 |         0 |              0 |           19 |                 5 |
|    3175 | Equity.US.DKNG/USD           | POST_MARKET | equity                 | engine       |            5 |      1 |      1 |         3 |              0 |           15 |                 2 |
|    1007 | Equity.US.BX/USD             | POST_MARKET | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           19 |                 6 |
|    1615 | Equity.HK.0175/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            4 |                 2 |
|    1613 | Equity.HK.0016/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    3170 | Equity.US.BIRD/USD           | PRE_MARKET  | equity                 | engine       |            7 |      0 |      1 |         6 |              0 |           12 |                 0 |
|    1609 | Equity.HK.0001/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1370 | Equity.US.RIO/USD            | REGULAR     | equity                 | engine       |            7 |      4 |      1 |         2 |              0 |           15 |                 2 |
|    1502 | Equity.US.ZBH/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           18 |                 2 |
|    2368 | Equity.US.NVDL/USD           | PRE_MARKET  | equity                 | engine       |           10 |      5 |      1 |         4 |              0 |           11 |                 3 |
|    2368 | Equity.US.NVDL/USD           | POST_MARKET | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           14 |                 4 |
|     992 | Equity.US.BKNG/USD           | PRE_MARKET  | equity                 | engine       |           10 |      6 |      1 |         3 |              0 |           18 |                 4 |
|    2370 | Equity.US.RGTI/USD           | REGULAR     | equity                 | engine       |            9 |      6 |      1 |         2 |              0 |           14 |                 3 |
|     999 | Equity.US.BRK-B/USD          | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            7 |                 2 |
|    1758 | Equity.US.VGT/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           15 |                 1 |
|    1497 | Equity.US.XEL/USD            | REGULAR     | equity                 | engine       |           11 |      8 |      1 |         2 |              0 |           16 |                 3 |
|    3141 | Equity.US.ASTS/USD           | POST_MARKET | equity                 | engine       |           10 |      8 |      1 |         1 |              0 |           13 |                 3 |
|    1485 | Equity.US.WDC/USD            | POST_MARKET | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |           20 |                 6 |
|    1708 | Equity.US.JEPQ/USD           | PRE_MARKET  | equity                 | engine       |           10 |      6 |      1 |         3 |              0 |           14 |                 6 |
|    1333 | Equity.US.PCAR/USD           | POST_MARKET | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           21 |                 6 |
|    3260 | Equity.HK.9880/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            2 |                 0 |
|    1700 | Equity.US.IVW/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           16 |                 2 |
|    1696 | Equity.US.IJR/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           15 |                 0 |
|    1380 | Equity.US.RSG/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           19 |                10 |
|     186 | Crypto.BSV/USD               | REGULAR     | crypto                 | peer         |           14 |     13 |      1 |         0 |              0 |            7 |                 6 |
|    1655 | Equity.HK.6862/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     208 | FundingRate.Binance.SOL/USDT | REGULAR     | funding-rate           | peer         |            4 |      3 |      1 |         0 |              0 |            0 |                 0 |
|    3349 | Equity.US.SPMO/USD           | PRE_MARKET  | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |           13 |                 0 |
|     220 | Crypto.BAND/USD              | REGULAR     | crypto                 | peer         |           12 |     10 |      1 |         1 |              0 |           19 |                18 |
|    1654 | Equity.HK.6618/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            4 |                 2 |
|     911 | Equity.HK.2688/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1652 | Equity.HK.3968/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            4 |                 2 |
|     314 | FX.AUD/NZD                   | REGULAR     | fx                     | engine       |           11 |      9 |      1 |         1 |              0 |            9 |                 7 |
|    1649 | Equity.HK.2388/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1648 | Equity.HK.2382/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     339 | FX.USD/CHF                   | REGULAR     | fx                     | engine       |           12 |      9 |      1 |         2 |              0 |           12 |                 8 |
|     340 | FX.USD/JPY                   | REGULAR     | fx                     | engine       |           11 |      9 |      1 |         1 |              0 |           14 |                10 |
|    1692 | Equity.US.IEF/USD            | POST_MARKET | equity                 | engine       |            8 |      5 |      1 |         2 |              0 |           16 |                 2 |
|     175 | Crypto.RSR/USD               | REGULAR     | crypto                 | peer         |           12 |     10 |      1 |         1 |              0 |           18 |                17 |
|     170 | Crypto.FTT/USD               | REGULAR     | crypto                 | peer         |           11 |      8 |      1 |         2 |              0 |           17 |                15 |
|     169 | Crypto.CORE/USD              | REGULAR     | crypto                 | peer         |           11 |     10 |      1 |         0 |              0 |           15 |                14 |
|    1695 | Equity.US.IJH/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           15 |                 1 |
|    3356 | Equity.US.QUBT/USD           | PRE_MARKET  | equity                 | engine       |            8 |      4 |      1 |         3 |              0 |           12 |                 3 |
|      47 | Crypto.GRT/USD               | REGULAR     | crypto                 | peer         |           14 |     12 |      1 |         1 |              0 |           19 |                18 |
|      58 | Crypto.STRK/USD              | REGULAR     | crypto                 | peer         |           13 |     11 |      1 |         1 |              0 |           18 |                15 |
|      60 | Crypto.FLOW/USD              | REGULAR     | crypto                 | peer         |           13 |     11 |      1 |         1 |              0 |           18 |                13 |
|      96 | Crypto.OSMO/USD              | REGULAR     | crypto                 | peer         |           11 |      9 |      1 |         1 |              0 |           19 |                18 |
|    1685 | Equity.US.DFAC/USD           | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           15 |                 3 |
|    1658 | Equity.HK.9999/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     108 | Crypto.BRETT/USD             | REGULAR     | crypto                 | peer         |            9 |      8 |      1 |         0 |              0 |           16 |                13 |
|     110 | Crypto.HYPE/USD              | REGULAR     | crypto                 | peer         |           14 |     13 |      1 |         0 |              0 |           12 |                11 |
|     125 | Crypto.BAT/USD               | REGULAR     | crypto                 | peer         |           13 |     11 |      1 |         1 |              0 |           20 |                19 |
|     148 | Crypto.LUNC/USD              | REGULAR     | crypto                 | peer         |           11 |      9 |      1 |         1 |              0 |           16 |                10 |
|    1693 | Equity.US.IEFA/USD           | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           15 |                 1 |
|     154 | Crypto.KAVA/USD              | REGULAR     | crypto                 | peer         |           12 |     10 |      1 |         1 |              0 |           17 |                16 |
|    1657 | Equity.HK.9961/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    3361 | Equity.US.KSTR/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      1 |         2 |              0 |            6 |                 2 |
|     389 | Crypto.BSOL/USD              | REGULAR     | crypto                 | peer         |           10 |      9 |      1 |         0 |              0 |            0 |                 0 |
|     412 | Crypto.DEGEN/USD             | REGULAR     | crypto                 | peer         |           13 |     11 |      1 |         1 |              0 |            9 |                 9 |
|     459 | Crypto.JLP/USD               | REGULAR     | crypto                 | peer         |            8 |      7 |      1 |         0 |              0 |            4 |                 1 |
|     897 | Equity.HK.1038/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 1 |
|     896 | Equity.HK.0992/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            4 |                 2 |
|     900 | Equity.HK.1109/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            4 |                 2 |
|     901 | Equity.HK.1209/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 1 |
|     902 | Equity.HK.1211/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 1 |
|    3286 | Equity.US.AXTI/USD           | POST_MARKET | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           14 |                 4 |
|     905 | Equity.HK.2015/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            4 |                 2 |
|    1724 | Equity.US.QUAL/USD           | REGULAR     | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           14 |                 2 |
|    3282 | Equity.US.IBKR/USD           | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           12 |                 2 |
|    1644 | Equity.HK.1997/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     906 | Equity.HK.2020/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     904 | Equity.HK.1810/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 1 |
|    1642 | Equity.HK.1928/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     909 | Equity.HK.2331/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     910 | Equity.HK.2628/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1640 | Equity.HK.1378/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|    1643 | Equity.HK.1929/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 1 |
|    1377 | Equity.US.ROL/USD            | REGULAR     | equity                 | engine       |           11 |      9 |      1 |         1 |              0 |           14 |                 7 |
|     455 | Crypto.INF/USD               | REGULAR     | crypto                 | peer         |            8 |      7 |      1 |         0 |              0 |            1 |                 1 |
|     892 | Equity.HK.0669/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 2 |
|     458 | Crypto.JITOSOL/USD           | REGULAR     | crypto                 | peer         |           15 |     14 |      1 |         0 |              0 |            7 |                 6 |
|    3319 | Equity.US.MVLL/USD           | POST_MARKET | equity                 | engine       |           10 |      4 |      1 |         5 |              0 |           11 |                 2 |
|     489 | Crypto.METIS/USD             | REGULAR     | crypto                 | peer         |            7 |      6 |      1 |         0 |              0 |           16 |                15 |
|    3318 | Equity.US.MUU/USD            | POST_MARKET | equity                 | engine       |            8 |      4 |      1 |         3 |              0 |           10 |                 2 |
|     533 | Crypto.PURR/USD              | REGULAR     | crypto                 | peer         |            7 |      6 |      1 |         0 |              0 |            7 |                 2 |
|    3314 | Equity.US.SPCX/USD           | REGULAR     | equity                 | engine       |            7 |      4 |      1 |         2 |              0 |           16 |                 4 |
|    2355 | Equity.US.CCJ/USD            | REGULAR     | equity                 | engine       |           11 |      9 |      1 |         1 |              0 |           15 |                 3 |
|     624 | Crypto.WAL/USD               | REGULAR     | crypto                 | peer         |           13 |     12 |      1 |         0 |              0 |            5 |                 4 |
|     740 | Crypto.SUSDE/USDE.RR         | REGULAR     | crypto-redemption-rate | peer         |           11 |      9 |      1 |         1 |              0 |            1 |                 0 |
|     886 | Equity.HK.0012/HKD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |            3 |                 2 |
|    3289 | Equity.US.LOGI/USD           | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           14 |                 4 |
|    3305 | Equity.HK.7709/HKD           | REGULAR     | equity                 | engine       |            4 |      3 |      1 |         0 |              0 |            2 |                 0 |
|     888 | Equity.HK.0027/HKD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |            3 |                 1 |
|    3288 | Equity.US.COHR/USD           | POST_MARKET | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           12 |                 4 |
|    3288 | Equity.US.COHR/USD           | PRE_MARKET  | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           14 |                 3 |
|    1058 | Equity.US.CTAS/USD           | REGULAR     | equity                 | engine       |            8 |      7 |      1 |         0 |              0 |           17 |                 7 |
|    1054 | Equity.US.CRWD/USD           | POST_MARKET | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           22 |                 8 |
|    2373 | Equity.US.SONY/USD           | REGULAR     | equity                 | engine       |           10 |      7 |      1 |         2 |              0 |           13 |                 3 |
|    1431 | Equity.US.TRMB/USD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |           17 |                 2 |
|    2269 | Equity.US.AAL/USD            | PRE_MARKET  | equity                 | engine       |            9 |      6 |      1 |         2 |              0 |           15 |                 0 |
|    1232 | Equity.US.KMB/USD            | REGULAR     | equity                 | engine       |            9 |      8 |      1 |         0 |              0 |           16 |                 7 |
|    1231 | Equity.US.KLAC/USD           | POST_MARKET | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           19 |                 7 |
|    1235 | Equity.US.KO/USD             | PRE_MARKET  | equity                 | engine       |           14 |     11 |      1 |         2 |              0 |           14 |                 3 |
|    2774 | Equity.US.GDXJ/USD           | PRE_MARKET  | equity                 | engine       |           11 |      6 |      1 |         4 |              0 |           12 |                 2 |
|    1235 | Equity.US.KO/USD             | POST_MARKET | equity                 | engine       |           16 |     13 |      1 |         2 |              0 |           12 |                 2 |
|    1239 | Equity.US.LDOS/USD           | POST_MARKET | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           19 |                 7 |
|    1242 | Equity.US.LHX/USD            | REGULAR     | equity                 | engine       |            8 |      7 |      1 |         0 |              0 |           16 |                 7 |
|    3074 | Equity.US.FXI/USD            | PRE_MARKET  | equity                 | engine       |            8 |      3 |      1 |         4 |              0 |           11 |                 4 |
|    1242 | Equity.US.LHX/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      1 |         4 |              0 |           19 |                 0 |
|    1429 | Equity.US.TPR/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           18 |                 3 |
|    1423 | Equity.US.TGT/USD            | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |           17 |                 7 |
|    1247 | Equity.US.LMT/USD            | PRE_MARKET  | equity                 | engine       |            7 |      3 |      1 |         3 |              0 |           21 |                 7 |
|    1247 | Equity.US.LMT/USD            | POST_MARKET | equity                 | engine       |            6 |      1 |      1 |         4 |              0 |           22 |                 1 |
|    2760 | Equity.US.EWZ/USD            | OVER_NIGHT  | equity                 | engine       |            5 |      0 |      1 |         4 |              0 |           16 |                 0 |
|    2271 | Equity.US.BABA/USD           | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           16 |                 5 |
|    1225 | Equity.US.KDP/USD            | PRE_MARKET  | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           17 |                 5 |
|    2310 | Crypto.ASTER/USD             | REGULAR     | crypto                 | peer         |           17 |     16 |      1 |         0 |              0 |            4 |                 3 |
|    2287 | Equity.US.FIG/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           13 |                 1 |
|    1219 | Equity.US.JCI/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           17 |                 9 |
|    1170 | Equity.US.HAL/USD            | PRE_MARKET  | equity                 | engine       |           10 |      7 |      1 |         2 |              0 |           18 |                 6 |
|    1442 | Equity.US.TXT/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           15 |                 3 |
|    2855 | Equity.US.SMR/USD            | POST_MARKET | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           13 |                 4 |
|    1199 | Equity.US.IFF/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           20 |                 6 |
|    1200 | Equity.US.INCY/USD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           18 |                 4 |
|    1197 | Equity.US.IDXX/USD           | POST_MARKET | equity                 | engine       |            6 |      1 |      1 |         4 |              0 |           19 |                 2 |
|    2849 | Equity.US.SAP/USD            | PRE_MARKET  | equity                 | engine       |            8 |      4 |      1 |         3 |              0 |            9 |                 3 |
|    2849 | Equity.US.SAP/USD            | REGULAR     | equity                 | engine       |            8 |      4 |      1 |         3 |              0 |            9 |                 3 |
|    1195 | Equity.US.IBM/USD            | PRE_MARKET  | equity                 | engine       |           10 |      7 |      1 |         2 |              0 |           19 |                 6 |
|    1195 | Equity.US.IBM/USD            | POST_MARKET | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           22 |                 7 |
|    1343 | Equity.US.PHM/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           20 |                 2 |
|    1388 | Equity.US.SIVR/USD           | PRE_MARKET  | equity                 | engine       |           10 |      6 |      1 |         3 |              0 |           17 |                 6 |
|    1209 | Equity.US.ISRG/USD           | REGULAR     | equity                 | engine       |           11 |      8 |      1 |         2 |              0 |           13 |                 4 |
|    1209 | Equity.US.ISRG/USD           | PRE_MARKET  | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           17 |                 7 |
|    1211 | Equity.US.ITA/USD            | REGULAR     | equity                 | engine       |           12 |     10 |      1 |         1 |              0 |           15 |                 4 |
|    1261 | Equity.US.MAS/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           16 |                 6 |
|    2271 | Equity.US.BABA/USD           | PRE_MARKET  | equity                 | engine       |            9 |      5 |      1 |         3 |              0 |           16 |                 7 |
|    1257 | Equity.US.MA/USD             | REGULAR     | equity                 | engine       |           11 |     10 |      1 |         0 |              0 |           17 |                 5 |
|    1404 | Equity.US.STX/USD            | OVER_NIGHT  | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           21 |                 4 |
|    1317 | Equity.US.NWSA/USD           | REGULAR     | equity                 | engine       |           10 |      9 |      1 |         0 |              0 |           15 |                 5 |
|    1308 | Equity.US.NOW/USD            | PRE_MARKET  | equity                 | engine       |           10 |      6 |      1 |         3 |              0 |           18 |                10 |
|    2702 | Equity.US.AAAU/USD           | POST_MARKET | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           17 |                 4 |
|    2702 | Equity.US.AAAU/USD           | PRE_MARKET  | equity                 | engine       |           10 |      5 |      1 |         4 |              0 |           15 |                 4 |
|    1308 | Equity.US.NOW/USD            | POST_MARKET | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           23 |                11 |
|    1319 | Equity.US.O/USD              | REGULAR     | equity                 | engine       |           13 |     11 |      1 |         1 |              0 |           12 |                 3 |
|    2418 | Equity.US.OKLO/USD           | PRE_MARKET  | equity                 | engine       |            9 |      5 |      1 |         3 |              0 |           12 |                 4 |
|    1414 | Equity.US.TAP/USD            | REGULAR     | equity                 | engine       |           10 |      8 |      1 |         1 |              0 |           13 |                 5 |
|    1405 | Equity.US.STZ/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           20 |                 4 |
|    1325 | Equity.US.ORLY/USD           | REGULAR     | equity                 | engine       |           14 |     12 |      1 |         1 |              0 |           12 |                 4 |
|    1325 | Equity.US.ORLY/USD           | POST_MARKET | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           19 |                 3 |
|    1342 | Equity.US.PH/USD             | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           19 |                 3 |
|    1327 | Equity.US.OXY/USD            | PRE_MARKET  | equity                 | engine       |           14 |     11 |      1 |         2 |              0 |           14 |                 4 |
|    1391 | Equity.US.SMCI/USD           | PRE_MARKET  | equity                 | engine       |           13 |      9 |      1 |         3 |              0 |           15 |                 7 |
|    1333 | Equity.US.PCAR/USD           | REGULAR     | equity                 | engine       |           11 |     10 |      1 |         0 |              0 |           15 |                 6 |
|    1316 | Equity.US.NWS/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           16 |                 4 |
|    1302 | Equity.US.NEE/USD            | REGULAR     | equity                 | engine       |           11 |     10 |      1 |         0 |              0 |           14 |                 5 |
|    1271 | Equity.US.MET/USD            | REGULAR     | equity                 | engine       |           14 |     12 |      1 |         1 |              0 |           11 |                 3 |
|    2690 | Equity.US.QBTS/USD           | REGULAR     | equity                 | engine       |           12 |      8 |      1 |         3 |              0 |           13 |                 0 |
|    1264 | Equity.US.MCHP/USD           | REGULAR     | equity                 | engine       |           10 |      8 |      1 |         1 |              0 |           16 |                 3 |
|    1273 | Equity.US.MGM/USD            | REGULAR     | equity                 | engine       |           12 |     10 |      1 |         1 |              0 |           13 |                 4 |
|    1270 | Equity.US.MELI/USD           | REGULAR     | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           17 |                 4 |
|    2722 | Equity.US.BIDU/USD           | PRE_MARKET  | equity                 | engine       |            9 |      5 |      1 |         3 |              0 |           13 |                 2 |
|    1268 | Equity.US.MDLZ/USD           | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           17 |                 7 |
|    2271 | Equity.US.BABA/USD           | POST_MARKET | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           19 |                 8 |
|    1288 | Equity.US.MRNA/USD           | REGULAR     | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           19 |                 2 |
|    1281 | Equity.US.MNST/USD           | REGULAR     | equity                 | engine       |           14 |     11 |      1 |         2 |              0 |           12 |                 4 |
|    1341 | Equity.US.PGR/USD            | REGULAR     | equity                 | engine       |           12 |     10 |      1 |         1 |              0 |           13 |                 6 |
|    1296 | Equity.US.MTCH/USD           | REGULAR     | equity                 | engine       |            8 |      7 |      1 |         0 |              0 |           17 |                 8 |
|    2706 | Equity.US.APLD/USD           | POST_MARKET | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           16 |                 3 |
|    1289 | Equity.US.MRVL/USD           | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           22 |                 8 |
|    1289 | Equity.US.MRVL/USD           | PRE_MARKET  | equity                 | engine       |           10 |      5 |      1 |         4 |              0 |           20 |                11 |
|    1289 | Equity.US.MRVL/USD           | POST_MARKET | equity                 | engine       |            6 |      4 |      1 |         1 |              0 |           24 |                11 |
|    2690 | Equity.US.QBTS/USD           | PRE_MARKET  | equity                 | engine       |           12 |      6 |      1 |         5 |              0 |           13 |                 5 |
|    2863 | Equity.US.SOXL/USD           | PRE_MARKET  | equity                 | engine       |            9 |      6 |      1 |         2 |              0 |           12 |                 2 |
|    1442 | Equity.US.TXT/USD            | POST_MARKET | equity                 | engine       |            5 |      0 |      1 |         4 |              0 |           18 |                 3 |
|    1672 | Equity.US.AEM/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           13 |                 3 |
|    1774 | Equity.US.XLF/USD            | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           13 |                 2 |
|    1367 | Equity.US.REG/USD            | REGULAR     | equity                 | engine       |           14 |     12 |      1 |         1 |              0 |           11 |                 4 |
|    1470 | Equity.US.VLTO/USD           | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           16 |                 6 |
|    2971 | Equity.US.EWJ/USD            | PRE_MARKET  | equity                 | engine       |            9 |      5 |      1 |         3 |              0 |           16 |                 5 |
|    1354 | Equity.US.PPL/USD            | REGULAR     | equity                 | engine       |           13 |     11 |      1 |         1 |              0 |           12 |                 4 |
|    1108 | Equity.US.EOG/USD            | REGULAR     | equity                 | engine       |           10 |      8 |      1 |         1 |              0 |           16 |                 7 |
|    1106 | Equity.US.EMR/USD            | REGULAR     | equity                 | engine       |            9 |      8 |      1 |         0 |              0 |           16 |                 4 |
|    1111 | Equity.US.EQR/USD            | REGULAR     | equity                 | engine       |            9 |      8 |      1 |         0 |              0 |           17 |                 8 |
|    2944 | Equity.US.EWY/USD            | PRE_MARKET  | equity                 | engine       |           10 |      6 |      1 |         3 |              0 |           16 |                 8 |
|    1803 | Crypto.EURCV/USD             | REGULAR     | crypto                 | peer         |            7 |      5 |      1 |         1 |              0 |            0 |                 0 |
|    1468 | Equity.US.VICI/USD           | REGULAR     | equity                 | engine       |           11 |      9 |      1 |         1 |              0 |           11 |                 3 |
|    1353 | Equity.US.PPG/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           20 |                 8 |
|    2943 | Equity.US.CPER/USD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           16 |                 1 |
|    1124 | Equity.US.EXR/USD            | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           18 |                 8 |
|    1126 | Equity.US.F/USD              | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           18 |                 8 |
|    2990 | Crypto.SOLVBTC/BTC.RR        | REGULAR     | crypto-redemption-rate | peer         |            7 |      5 |      1 |         1 |              0 |            5 |                 3 |
|    1467 | Equity.US.V/USD              | PRE_MARKET  | equity                 | engine       |           10 |      5 |      1 |         4 |              0 |           18 |                 6 |
|    1475 | Equity.US.VRTX/USD           | POST_MARKET | equity                 | engine       |            7 |      1 |      1 |         5 |              0 |           18 |                 4 |
|    2306 | Equity.US.XYZ/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           10 |                 2 |
|    1096 | Equity.US.ECL/USD            | REGULAR     | equity                 | engine       |           10 |      9 |      1 |         0 |              0 |           16 |                 3 |
|    1765 | Equity.US.VTEB/USD           | REGULAR     | equity                 | engine       |           13 |     11 |      1 |         1 |              0 |            6 |                 3 |
|    1480 | Equity.US.WAB/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           18 |                 2 |
|    1053 | Equity.US.CRM/USD            | PRE_MARKET  | equity                 | engine       |           11 |      8 |      1 |         2 |              0 |           19 |                 5 |
|    1768 | Equity.US.VUG/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           17 |                 0 |
|    3066 | Equity.US.PAYP/USD           | OVER_NIGHT  | equity                 | engine       |            4 |      0 |      1 |         3 |              0 |           17 |                 0 |
|    1770 | Equity.US.VWO/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           16 |                 4 |
|    1772 | Equity.US.VXX/USD            | REGULAR     | equity                 | engine       |            9 |      6 |      1 |         2 |              0 |           16 |                 1 |
|    1479 | Equity.US.VZ/USD             | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           17 |                 3 |
|    1063 | Equity.US.CVX/USD            | PRE_MARKET  | equity                 | engine       |           15 |     12 |      1 |         2 |              0 |           14 |                 4 |
|    1478 | Equity.US.VTRS/USD           | REGULAR     | equity                 | engine       |           10 |      8 |      1 |         1 |              0 |           12 |                 4 |
|    1063 | Equity.US.CVX/USD            | OVER_NIGHT  | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           24 |                 7 |
|    2398 | Crypto.ORE/USD               | REGULAR     | crypto                 | peer         |            6 |      4 |      1 |         1 |              0 |            1 |                 1 |
|    1477 | Equity.US.VTR/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           14 |                 6 |
|    2369 | Equity.US.PSKY/USD           | REGULAR     | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           12 |                 2 |
|    1773 | Equity.US.VYM/USD            | REGULAR     | equity                 | engine       |            5 |      3 |      1 |         1 |              0 |           15 |                 2 |
|    1127 | Equity.US.FANG/USD           | REGULAR     | equity                 | engine       |           10 |      9 |      1 |         0 |              0 |           14 |                 5 |
|    2928 | Equity.US.NLR/USD            | OVER_NIGHT  | equity                 | engine       |            6 |      0 |      1 |         5 |              0 |           19 |                 0 |
|    1185 | Equity.US.HRL/USD            | REGULAR     | equity                 | engine       |            8 |      7 |      1 |         0 |              0 |           17 |                 8 |
|    1445 | Equity.US.UBER/USD           | POST_MARKET | equity                 | engine       |            9 |      6 |      1 |         2 |              0 |           19 |                 8 |
|    1158 | Equity.US.GLW/USD            | PRE_MARKET  | equity                 | engine       |           10 |      7 |      1 |         2 |              0 |           18 |                 6 |
|    1854 | Crypto.WLFI/USD              | REGULAR     | crypto                 | peer         |           18 |     17 |      1 |         0 |              0 |            6 |                 5 |
|    1436 | Equity.US.TSM/USD            | POST_MARKET | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |           23 |                 7 |
|    2887 | Equity.US.VRT/USD            | PRE_MARKET  | equity                 | engine       |           10 |      6 |      1 |         3 |              0 |           11 |                 3 |
|    2887 | Equity.US.VRT/USD            | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |           15 |                 3 |
|    1171 | Equity.US.HAS/USD            | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           18 |                 6 |
|    1932 | Equity.HK.0300/HKD           | REGULAR     | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |            3 |                 2 |
|    2869 | Equity.US.TCOM/USD           | REGULAR     | equity                 | engine       |           10 |      7 |      1 |         2 |              0 |           11 |                 1 |
|    2882 | Equity.US.UVXY/USD           | PRE_MARKET  | equity                 | engine       |            9 |      5 |      1 |         3 |              0 |           11 |                 1 |
|    2882 | Equity.US.UVXY/USD           | REGULAR     | equity                 | engine       |            7 |      5 |      1 |         1 |              0 |           13 |                 2 |
|    2921 | Crypto.LIT/USD               | REGULAR     | crypto                 | peer         |            9 |      8 |      1 |         0 |              0 |            8 |                 7 |
|    1436 | Equity.US.TSM/USD            | PRE_MARKET  | equity                 | engine       |            9 |      6 |      1 |         2 |              0 |           20 |                 9 |
|    1162 | Equity.US.GOOG/USD           | PRE_MARKET  | equity                 | engine       |           12 |      8 |      1 |         3 |              0 |           16 |                 5 |
|    1181 | Equity.US.HON/USD            | REGULAR     | equity                 | engine       |           12 |     10 |      1 |         1 |              0 |           14 |                 5 |
|    1182 | Equity.US.HOOD/USD           | PRE_MARKET  | equity                 | engine       |            8 |      5 |      1 |         2 |              0 |           20 |                11 |
|    1158 | Equity.US.GLW/USD            | POST_MARKET | equity                 | engine       |            8 |      6 |      1 |         1 |              0 |           20 |                 9 |
|    1164 | Equity.US.GOVT/USD           | REGULAR     | equity                 | engine       |           17 |     15 |      1 |         1 |              0 |            5 |                 4 |
|    1444 | Equity.US.UAL/USD            | POST_MARKET | equity                 | engine       |            9 |      6 |      1 |         2 |              0 |           15 |                 7 |
|    2892 | Equity.US.XBI/USD            | PRE_MARKET  | equity                 | engine       |            8 |      5 |      1 |         2 |              0 |           15 |                 8 |
|    1831 | Crypto.NAV.USTB/USD          | REGULAR     | nav                    | peer         |            6 |      4 |      1 |         1 |              0 |            2 |                 2 |
|    1137 | Equity.US.FIS/USD            | REGULAR     | equity                 | engine       |            9 |      7 |      1 |         1 |              0 |           16 |                 7 |
|    1827 | Crypto.MSTRX/USD             | REGULAR     | crypto                 | peer         |           15 |     13 |      1 |         1 |              0 |            5 |                 5 |
|    1141 | Equity.US.FOXA/USD           | REGULAR     | equity                 | engine       |            7 |      6 |      1 |         0 |              0 |           18 |                 9 |
|    2930 | Equity.US.SHLD/USD           | REGULAR     | equity                 | engine       |            6 |      5 |      1 |         0 |              0 |           17 |                 6 |
|    1147 | Equity.US.GD/USD             | POST_MARKET | equity                 | engine       |            6 |      2 |      1 |         3 |              0 |           19 |                 2 |
|    2972 | Crypto.INX/USD               | REGULAR     | crypto                 | peer         |            8 |      6 |      1 |         1 |              0 |            9 |                 9 |
|    1349 | Equity.US.PNR/USD            | REGULAR     | equity                 | engine       |            5 |      4 |      1 |         0 |              0 |           20 |                 9 |
|    1149 | Equity.US.GE/USD             | REGULAR     | equity                 | engine       |           15 |     13 |      1 |         1 |              0 |           11 |                 3 |
|    2929 | Equity.US.AIQ/USD            | REGULAR     | equity                 | engine       |            8 |      7 |      1 |         0 |              0 |           16 |                 1 |
|    1154 | Equity.US.GILD/USD           | REGULAR     | equity                 | engine       |           11 |      9 |      1 |         1 |              0 |           13 |                 5 |
|    1159 | Equity.US.GM/USD             | REGULAR     | equity                 | engine       |           11 |      9 |      1 |         1 |              0 |           14 |                 7 |
|    1152 | Equity.US.GEV/USD            | REGULAR     | equity                 | engine       |            9 |      8 |      1 |         0 |              0 |           18 |                 5 |
|    1152 | Equity.US.GEV/USD            | PRE_MARKET  | equity                 | engine       |           10 |      7 |      1 |         2 |              0 |           17 |                 7 |
|    1834 | Crypto.OG/USD                | REGULAR     | crypto                 | peer         |           11 |      8 |      1 |         2 |              0 |            5 |                 3 |
|    1081 | Equity.US.DIS/USD            | PRE_MARKET  | equity                 | engine       |           10 |      6 |      1 |         3 |              0 |           20 |                 8 |
