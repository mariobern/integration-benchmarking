# Benchmark Results Interpretation Guide — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a standalone Markdown document (`docs/benchmark_results_guide.md`) that publisher engineering teams can use to interpret benchmark CSV results.

**Architecture:** Single Markdown file with 6 sections progressing from quick-start orientation through core metrics, session breakdowns, summary interpretation, advanced statistical tests, and a full column reference appendix. Uses real examples from `pub21_metals.csv`.

**Tech Stack:** Markdown (no code changes required)

---

## Task 1: Write Section 1 — Quick Start

**Files:**

- Create: `docs/benchmark_results_guide.md`

**Step 1: Write the Quick Start section**

Write the document header and Section 1 with the following content:

```markdown
# Benchmark Results Interpretation Guide

This guide explains how to read and interpret your benchmark results CSV. Each row in the CSV compares your published prices against the Datascope exchange benchmark, second by second, for a single feed on a single day.

## 1. Quick Start

### What Does Pass/Fail Mean?

Your feed **passes** if it meets either of these criteria:

| Path       | Condition                            | What It Means                                                                                    |
| ---------- | ------------------------------------ | ------------------------------------------------------------------------------------------------ |
| **Path 1** | `nrmse < 0.01`                       | Your error is less than 1% of the benchmark price range. Automatic pass.                         |
| **Path 2** | `nrmse < 0.05` AND `hit_rate >= 95%` | Your error is under 5% AND at least 95% of your prices land within 10 basis points of benchmark. |

If neither condition is met, the feed **fails**.

### The 6 Columns to Check First

| Column           | What It Tells You                                                        |
| ---------------- | ------------------------------------------------------------------------ |
| `symbol`         | Which feed this row is about (e.g., `Metal.XPT/USD`)                     |
| `passes`         | `True` or `False` — did this feed meet the criteria above?               |
| `nrmse`          | Your normalized error (lower is better). The primary quality metric.     |
| `hit_rate`       | % of your prices within 10 basis points of benchmark (higher is better). |
| `n_observations` | How many data points were compared. Minimum 100 required.                |
| `error`          | If non-empty, the evaluation failed — this column explains why.          |

### Example: Reading a Row

Here is a real row from a metals benchmark evaluation (simplified):

| symbol        | passes | nrmse | hit_rate | n_observations |
| ------------- | ------ | ----- | -------- | -------------- |
| Metal.XPT/USD | False  | 0.061 | 22.46    | 72,212         |

How to read this:

- `nrmse = 0.061` — this is between 0.01 and 0.05, so Path 1 does not apply. We check Path 2.
- `hit_rate = 22.46%` — this is far below the 95% threshold.
- **Result: FAIL.** Even though the normalized error is relatively small, only 22% of prices were within 10 basis points of benchmark. The feed needs better price accuracy to pass via Path 2.
```

**Step 2: Verify the file was created**

Run: `wc -l docs/benchmark_results_guide.md`
Expected: ~40-50 lines

**Step 3: Commit**

```bash
git add docs/benchmark_results_guide.md
git commit -m "docs: add benchmark results guide - Section 1 Quick Start"
```

---

## Task 2: Write Section 2 — Core Quality Metrics

**Files:**

- Modify: `docs/benchmark_results_guide.md`

**Step 1: Append Section 2**

Append the Core Quality Metrics section after Section 1. For each metric, include: plain English description, formula, good/bad ranges, and actionable advice. Use these real example rows from `pub21_metals.csv`:

**Example A — "Close but failing" (Feb 12, Metal.XPT/USD):**

- `nrmse=0.061`, `hit_rate=22.46%`, `rmse=9.15`, `mean_spread=13.18`, `rmse_over_spread=0.69`, `mean_diff=0.57`, `mae=6.90`, `n_observations=72,212`

**Example B — "Badly broken" (Feb 11, Metal.XPT/USD):**

- `nrmse=1.061`, `hit_rate=0.00%`, `rmse=118.59`, `mean_spread=13.49`, `rmse_over_spread=8.79`, `mean_diff=-116.27`, `mae=116.27`, `n_observations=72,824`

Cover these metrics in this order:

1. **`nrmse`** — RMSE divided by (max - min) benchmark price over the evaluation period. Formula: `nrmse = rmse / benchmark_price_range`. Ranges: < 0.01 excellent (auto-pass), 0.01-0.05 acceptable (needs hit_rate >= 95%), > 0.05 failing.
2. **`hit_rate`** — percentage of observations where `|publisher_price - benchmark_price| / benchmark_price < 0.001` (10 basis points). Only matters when nrmse is between 0.01 and 0.05.
3. **`rmse`** — Root Mean Square Error in raw price units. Formula: `sqrt(mean((publisher - benchmark)^2))`. Context-dependent (a $9.15 RMSE means different things for gold vs forex).
4. **`benchmark_price_range`** — `max(benchmark_price) - min(benchmark_price)` over the evaluation period. Used to normalize RMSE into nrmse. High range = easier to pass.
5. **`mean_spread`** — average bid-ask spread from the benchmark. Used as denominator for `rmse_over_spread`.
6. **`rmse_over_spread`** — `rmse / mean_spread`. Measures error relative to the bid-ask spread. Ranges: < 0.5 excellent, 0.5-1.0 good, > 1.0 your error exceeds the spread. Not used for pass/fail but useful for quality assessment.
7. **`mean_diff`** — mean of `(publisher_price - benchmark_price)`. Positive = you're consistently high. Negative = consistently low. Near zero = no systematic bias. Action if large: calibrate your price source.
8. **`mae`** — Mean Absolute Error: `mean(|publisher_price - benchmark_price|)`. Similar to RMSE but less sensitive to outliers. Useful for understanding typical deviation.
9. **`n_observations`** — number of data points where publisher and benchmark timestamps were matched. Minimum 100 required for a valid evaluation.

Include a comparison table using Examples A and B side by side to show how to diagnose the difference between a "close but failing" feed and a "badly broken" feed.

End with a "How to Improve" subsection:

- Systematic bias (large `mean_diff`): calibrate price source, check rounding/truncation, verify timezone handling
- Random error (high `rmse` but low `mean_diff`): reduce latency, increase update frequency during volatility
- Outliers (high `rmse` but low `mae`): add spike detection, validate price updates against recent history

**Step 2: Verify the section was appended**

Run: `grep -c "^##" docs/benchmark_results_guide.md`
Expected: at least 3 (header + section 1 + section 2 headings)

**Step 3: Commit**

```bash
git add docs/benchmark_results_guide.md
git commit -m "docs: add benchmark results guide - Section 2 Core Quality Metrics"
```

---

## Task 3: Write Section 3 — Session Breakdown

**Files:**

- Modify: `docs/benchmark_results_guide.md`

**Step 1: Append Section 3**

Append the Session Breakdown section. Content:

1. **Session overview table** — 4 sessions (Regular, Pre-market, After-hours, Overnight), their times in ET, benchmark source, and CSV column prefix.
2. **Column mapping** — each session adds 4-5 columns with a prefix: `{session}_n_observations`, `{session}_nrmse`, `{session}_hit_rate`, `{session}_passes`, `{session}_error`. Overnight also adds `overnight_n_reference_observations` and `overnight_reference_publisher_id`.
3. **Same pass/fail criteria** — each session is evaluated independently using the same `nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)` rule.
4. **Overnight caveat** — clearly state: "The overnight benchmark is Publisher 32 (Blue Ocean ATS), another data provider. This is a peer comparison, not an official exchange benchmark. If Publisher 32 has errors, overnight metrics for all publishers will be affected."
5. **Empty columns** — explain that if session columns are empty, that session was not evaluated (either the flag wasn't used, or the asset class doesn't have distinct sessions — metals trade 24h, so pre-market/after-hours don't apply).
6. **Minimum observation thresholds** — 100 for regular hours, 50 for extended/overnight sessions.

**Step 2: Commit**

```bash
git add docs/benchmark_results_guide.md
git commit -m "docs: add benchmark results guide - Section 3 Session Breakdown"
```

---

## Task 4: Write Section 4 — Reading the Summary Sections

**Files:**

- Modify: `docs/benchmark_results_guide.md`

**Step 1: Append Section 4**

Append the Summary Sections walkthrough. The CSV has 4 summary blocks appended after the per-feed data rows. Explain each:

**4.1 SUMMARY block** — the overall scorecard. Key fields to explain:

- `pass_count`, `fail_count`, `error_count`, `pass_rate_pct` — your overall results
- `pass_by_nrmse_alone` vs `pass_by_nrmse_and_hit_rate` — which pass path feeds took
- Distribution metrics: `median_nrmse`, `mean_nrmse`, `p90_nrmse`, `p95_nrmse`, `min_nrmse`, `max_nrmse` — explain percentile interpretation ("p90_nrmse = 1.06 means 90% of your feeds have nrmse below 1.06")
- Same distributions for `hit_rate`, `rmse_over_spread`, `mae`, `mean_diff`
- `total_observations`, `mean_observations_per_feed`, `median_observations_per_feed` — data coverage
- Per-asset-class breakdown: `pass_count_{mode}`, `fail_count_{mode}`, `error_count_{mode}`

Worked example from pub21_metals.csv:

- `pass_count=0, fail_count=10` — 0% pass rate
- `median_nrmse=0.467` — typical feed has ~47% of price range as error
- `p90_nrmse=1.061` — worst 10% exceed 1.0
- `median_rmse_over_spread=2.67` — typical error is 2.7x the spread
- `median_mean_diff=-29.13` — systematic negative bias of ~$29

**4.2 EXTENDED_HOURS block** — pre-market and after-hours aggregates. Same structure as SUMMARY but scoped to those sessions. All zeros/empty means sessions weren't applicable.

**4.3 OVERNIGHT_SESSION block** — overnight aggregates. Notes the `overnight_reference_publisher_id` (Publisher 32).

**4.4 PER_DATE_BREAKDOWN block** — one row per date with `total`, `pass`, `fail`, `error`, `pass_rate_pct`, `median_nrmse`, `median_hit_rate`. Useful for spotting _when_ quality degraded.

Worked example from pub21_metals.csv per-date:

- Feb 12: `median_nrmse=0.088, median_hit_rate=13.67` — best day
- Feb 10: `median_nrmse=0.811, median_hit_rate=0.00` — worst day
- Advice: "If you see a sudden spike in nrmse on a specific date, investigate what changed on your end that day — data source switch, deployment, network issue, etc."

**Step 2: Commit**

```bash
git add docs/benchmark_results_guide.md
git commit -m "docs: add benchmark results guide - Section 4 Summary Sections"
```

---

## Task 5: Write Section 5 — Advanced Statistical Tests

**Files:**

- Modify: `docs/benchmark_results_guide.md`

**Step 1: Append Section 5**

Append the Advanced section. Frame it as optional: "This section covers statistical metrics included in the CSV for publishers who want deeper analysis beyond pass/fail. These columns may be empty if statistical tests were skipped during evaluation."

Metrics to explain:

1. **`t_statistic` / `t_pvalue`** — One-sample t-test against zero. Tests whether the mean price difference is statistically different from zero. `t_pvalue < 0.05` means statistically significant bias. Larger absolute `t_statistic` = stronger evidence.
2. **`wilcoxon_statistic` / `wilcoxon_pvalue`** — Wilcoxon signed-rank test. Non-parametric alternative to the t-test — doesn't assume errors are normally distributed. More robust when errors have outliers or skewed distributions. Same interpretation: `p < 0.05` = significant bias.
3. **`normality_pvalue`** — D'Agostino-Pearson test. Tests whether your price errors follow a normal (bell curve) distribution. `p >= 0.05` = errors are normally distributed. Low p = outliers, irregular patterns, or skewed errors.
4. **`mean_abs_z_score`** — Average absolute z-score of price differences. Measures how many standard deviations the typical error is from the mean. Expected ~0.8 for a normal distribution. > 1.5 indicates frequent large deviations (outliers).
5. **`std_diff`** — Standard deviation of price differences. Measures error volatility. High = inconsistent errors. Low = stable errors (even if biased).
6. **`mean_pct_diff` / `std_pct_diff`** — Same as `mean_diff`/`std_diff` but expressed as percentages. Useful for comparing across assets with different price levels (e.g., gold at $2000 vs EURUSD at 1.08).

Include a "Diagnostic Patterns" subsection:

| Pattern                                          | Likely Cause                         | Action                                     |
| ------------------------------------------------ | ------------------------------------ | ------------------------------------------ |
| All t-tests significant + large `mean_diff`      | Systematic calibration error         | Recalibrate price source against benchmark |
| Low `normality_pvalue` + high `mean_abs_z_score` | Outlier/spike problem                | Add spike detection before publishing      |
| Normal errors + low bias + moderate `nrmse`      | Pure latency/timing noise            | Improve update frequency, reduce latency   |
| High `std_diff` relative to `mean_diff`          | Inconsistent errors (not systematic) | Check for intermittent data source issues  |

Real example from pub21_metals.csv — Feb 11 XPD/USD (the "badly broken" row):

- `t_statistic=-780.40, t_pvalue=0.0` — overwhelming evidence of negative bias
- `normality_pvalue=0.0` — errors are NOT normally distributed
- `mean_abs_z_score=0.85` — moderate, but the systematic bias dominates

Contrast with Feb 12 XPT/USD (the "better" row):

- `t_statistic=16.75, t_pvalue=0.0` — still significant but vastly smaller magnitude
- `mean_diff=0.57` — tiny bias compared to -$47.50 on the bad row

**Step 2: Commit**

```bash
git add docs/benchmark_results_guide.md
git commit -m "docs: add benchmark results guide - Section 5 Advanced Statistical Tests"
```

---

## Task 6: Write Section 6 — Full Column Reference Appendix

**Files:**

- Modify: `docs/benchmark_results_guide.md`

**Step 1: Append Section 6**

Append a flat reference table of all CSV columns. This is a Ctrl+F lookup table — no narrative, just definitions. Include every column from the CSV header (all 43):

```
publisher_id, feed_id, date, mode, symbol, passes, n_observations,
nrmse, hit_rate, benchmark_price_range, rmse, mean_spread, rmse_over_spread,
mean_diff, std_diff, mean_pct_diff, std_pct_diff, mae,
t_statistic, t_pvalue, wilcoxon_statistic, wilcoxon_pvalue, normality_pvalue, mean_abs_z_score,
premarket_n_observations, premarket_nrmse, premarket_hit_rate, premarket_passes, premarket_error,
afterhours_n_observations, afterhours_nrmse, afterhours_hit_rate, afterhours_passes, afterhours_error,
overnight_n_observations, overnight_n_reference_observations, overnight_nrmse, overnight_hit_rate,
overnight_passes, overnight_reference_publisher_id, overnight_error,
error, execution_time_ms
```

Table format:

| Column | Type | Description | Good Range |
| ------ | ---- | ----------- | ---------- |

For each column, provide:

- **Type**: int, float, bool, string, date
- **Description**: One sentence max
- **Good Range**: The ideal value or range, or "—" if not applicable (identifiers, metadata)

Also include the summary-only fields that appear in the SUMMARY block but not in per-row data:

- `total_feeds`, `pass_count`, `fail_count`, `error_count`, `pass_rate_pct`
- `pass_by_nrmse_alone`, `pass_by_nrmse_and_hit_rate`
- `median_nrmse`, `mean_nrmse`, `p90_nrmse`, `p95_nrmse`, `min_nrmse`, `max_nrmse`
- `median_hit_rate`, `mean_hit_rate`, `min_hit_rate`, `max_hit_rate`
- `median_rmse_over_spread`, `mean_rmse_over_spread`, `p90_rmse_over_spread`, `p95_rmse_over_spread`
- `total_observations`, `mean_observations_per_feed`, `median_observations_per_feed`
- `median_mae`, `mean_mae`, `p90_mae`, `p95_mae`
- `median_mean_diff`, `mean_mean_diff`
- `significant_t_tests`, `total_t_tests`, `t_test_significance_rate`
- `normal_distributions`, `total_normality_tests`, `normality_rate`
- `median_z_score`, `mean_z_score`
- Per-asset breakdowns: `pass_count_{mode}`, `fail_count_{mode}`, `error_count_{mode}`

**Step 2: Verify completeness**

Run: `grep -c "|" docs/benchmark_results_guide.md`
Expected: high number (many table rows)

**Step 3: Commit**

```bash
git add docs/benchmark_results_guide.md
git commit -m "docs: add benchmark results guide - Section 6 Full Column Reference"
```

---

## Task 7: Final Review and Polish

**Files:**

- Modify: `docs/benchmark_results_guide.md`

**Step 1: Review the complete document**

Read the full document end to end. Check for:

- Consistent use of `>= 95%` (not 98%) for hit_rate threshold everywhere
- All real example values match `pub21_metals.csv` exactly (no rounding errors)
- No references to script filenames (`publisher_benchmark_95.py`, etc.)
- Section numbering is sequential (1-6)
- All cross-references between sections are correct
- No broken Markdown tables
- Consistent terminology (nrmse not NRMSE, hit_rate not hit rate, etc.)

**Step 2: Fix any issues found**

Apply edits as needed.

**Step 3: Final commit**

```bash
git add docs/benchmark_results_guide.md
git commit -m "docs: polish benchmark results interpretation guide"
```
