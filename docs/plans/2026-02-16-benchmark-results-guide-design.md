# Benchmark Results Interpretation Guide — Design

**Date:** 2026-02-16
**Approach:** Diagnostic Walkthrough (Approach B)
**Output:** `docs/benchmark_results_guide.md` — standalone Markdown sent alongside CSV results

## Context

Publishers receive CSV output from `publisher_benchmark_95.py` containing ~43 columns per row plus multi-section summaries (SUMMARY, EXTENDED_HOURS, OVERNIGHT_SESSION, PER_DATE_BREAKDOWN). Currently no documentation exists to help them interpret these results.

## Audience

Publisher **engineering teams** who will use the metrics to diagnose and improve data quality.

## Design Decisions

- **Standalone Markdown** — sent alongside the CSV, not embedded in it
- **Real examples** from `pub21_metals.csv` to make interpretation concrete
- **Tiered depth** — core metrics explained in detail, statistical tests in an Advanced section
- **Pass criteria:** `nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)`
- No script filenames referenced — publishers don't run scripts, they receive results

## Document Structure

### Section 1: Quick Start

**Goal:** Orient the reader in < 2 minutes.

Contents:

1. What is this CSV — one sentence: your prices compared second-by-second against Datascope benchmark
2. Pass/fail criteria:
   - Path 1: `nrmse < 0.01` (auto-pass)
   - Path 2: `nrmse < 0.05 AND hit_rate >= 95%`
3. The 6 columns to look at first: `symbol`, `passes`, `nrmse`, `hit_rate`, `n_observations`, `error`
4. Worked example: Feb 12 XPT/USD from pub21_metals.csv — low nrmse (0.061) but hit_rate=22.46% → FAIL

### Section 2: Core Quality Metrics

**Goal:** Deep understanding of the metrics that matter most.

For each metric: plain English → formula → good/bad ranges → real example → what to do if bad.

Metrics covered:

| Metric             | Plain English                                 | Good                        | Bad                  |
| ------------------ | --------------------------------------------- | --------------------------- | -------------------- |
| `nrmse`            | Price error relative to benchmark price range | < 0.01 (auto-pass)          | > 0.05 (can't pass)  |
| `hit_rate`         | % of prices within 10 bps of benchmark        | >= 95%                      | < 95%                |
| `rmse`             | Raw average error in price units              | Context-dependent           | Context-dependent    |
| `rmse_over_spread` | Error relative to bid-ask spread              | < 0.5 excellent, < 1.0 good | > 1.0                |
| `mean_diff`        | Systematic bias (consistently high or low)    | Near 0                      | Large +/-            |
| `mae`              | Average absolute deviation from benchmark     | Low relative to price       | High                 |
| `n_observations`   | Matched data points                           | > 100                       | < 100 (insufficient) |

Two worked examples:

- **Feb 12 XPT/USD** (decent): nrmse=0.061, hit_rate=22.46%, mean_diff=0.57, rmse_over_spread=0.69
- **Feb 11 XPT/USD** (broken): nrmse=1.06, mean_diff=-116.27, rmse_over_spread=8.79

### Section 3: Session Breakdown

**Goal:** Explain extended hours and overnight columns.

Session overview table:

| Session     | Time (ET)         | Benchmark Source | Column Prefix |
| ----------- | ----------------- | ---------------- | ------------- |
| Regular     | 9:30 AM - 4:00 PM | Datascope        | _(no prefix)_ |
| Pre-market  | 4:00 AM - 9:30 AM | Datascope        | `premarket_`  |
| After-hours | 4:00 PM - 8:00 PM | Datascope        | `afterhours_` |
| Overnight   | 8:00 PM - 4:00 AM | Publisher 32     | `overnight_`  |

Key points:

- Same pass/fail criteria per session
- Overnight = peer comparison (Publisher 32), not official benchmark
- Empty session columns = session not applicable for that asset class
- Min observations: 100 regular, 50 extended

### Section 4: Reading the Summary Sections

**Goal:** Explain the 4 summary blocks appended to the CSV.

1. **SUMMARY** — overall scorecard, distribution metrics (median/mean/p90/p95), per-asset-class breakdown
2. **EXTENDED_HOURS** — pre-market and after-hours aggregates
3. **OVERNIGHT_SESSION** — overnight aggregates with reference publisher ID
4. **PER_DATE_BREAKDOWN** — daily trend (total/pass/fail/error/median_nrmse/median_hit_rate per date)

Worked examples from pub21_metals.csv summary:

- 0% pass rate, median_nrmse=0.467, median_rmse_over_spread=2.67
- Per-date: Feb 12 best (nrmse=0.088), Feb 10 worst (nrmse=0.811)

### Section 5: Advanced — Statistical Tests

**Goal:** Optional deep-dive for publishers wanting more than pass/fail.

| Metric                                   | What It Tests                | How to Read It                  |
| ---------------------------------------- | ---------------------------- | ------------------------------- |
| `t_statistic` / `t_pvalue`               | Mean diff != 0?              | p < 0.05 = significant bias     |
| `wilcoxon_statistic` / `wilcoxon_pvalue` | Non-parametric bias test     | p < 0.05 = significant bias     |
| `normality_pvalue`                       | Errors normally distributed? | >= 0.05 = normal                |
| `mean_abs_z_score`                       | Typical deviation magnitude  | ~0.8 expected, > 1.5 = outliers |
| `std_diff`                               | Error volatility             | High = inconsistent             |
| `mean_pct_diff` / `std_pct_diff`         | Relative error stats         | Cross-asset comparison          |

Diagnostic patterns:

- All t-tests significant + large mean_diff → calibration issue
- Low normality + high z-scores → outlier problem
- Normal errors + low bias → latency/timing noise

### Section 6: Appendix — Full Column Reference

Flat table of all ~43 columns: Column | Type | Description | Good Range. Purely for Ctrl+F lookup.

## What's NOT in Scope

- No changes to `publisher_benchmark_95.py` output format
- No embedded guide in the CSV itself
- No portal/web presentation (separate concern)
- No per-asset-class interpretation differences (covered generically)
