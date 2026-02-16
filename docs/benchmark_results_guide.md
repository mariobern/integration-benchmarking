# Benchmark Results Interpretation Guide

This guide explains how to read and interpret your benchmark results CSV. Each row compares your published prices against the Datascope exchange benchmark, second by second, for a single feed on a single day.

---

## 1. Quick Start

### What Does Pass/Fail Mean?

Your feed **passes** if it meets either of these criteria:

| Path | Condition | What It Means |
|------|-----------|---------------|
| **Path 1** | `nrmse < 0.01` | Your error is less than 1% of the benchmark price range. Automatic pass. |
| **Path 2** | `nrmse < 0.05` AND `hit_rate >= 95%` | Your error is under 5% of the price range AND at least 95% of your prices land within 10 basis points (0.1%) of the benchmark. |

If neither condition is met, the feed **fails**.

### The 6 Columns to Check First

When you open your CSV, start with these columns:

| Column | What It Tells You |
|--------|-------------------|
| `symbol` | Which feed this row is about (e.g., `Metal.XPT/USD`, `FX.EUR/USD`) |
| `passes` | `True` or `False` — did this feed meet the pass criteria? |
| `nrmse` | Normalized error: RMSE divided by the benchmark price range. Lower is better. |
| `hit_rate` | Percentage of your prices within 10 basis points of the benchmark. Higher is better. |
| `n_observations` | How many data points were compared. Minimum 100 required for a valid evaluation. |
| `error` | If non-empty, the evaluation could not run — this column explains why. |

### Example: Reading a Row

Here is a real row from a metals benchmark evaluation:

| symbol | passes | nrmse | hit_rate | n_observations |
|--------|--------|-------|----------|----------------|
| Metal.XPT/USD | False | 0.061 | 22.46 | 72,212 |

How to read this:

1. **Check `passes`:** It's `False`, so the feed failed. Why?
2. **Check `nrmse`:** 0.061 is greater than 0.01, so Path 1 (automatic pass) does not apply.
3. **Check Path 2:** nrmse (0.061) is greater than 0.05, so Path 2 cannot apply either — the feed fails regardless of hit_rate.
4. **Look at `hit_rate`:** 22.46% — only about 1 in 5 prices were within 10 basis points of the benchmark.
5. **Check `n_observations`:** 72,212 — well above the 100 minimum, so this is a valid evaluation with plenty of data.

**Bottom line:** This feed has a normalized error of ~6% of the price range, and only 22% of prices are close to the benchmark. Both the nrmse and hit_rate need improvement.

---

## 2. Core Quality Metrics

This section explains each quality metric in the CSV. Understanding these will help you diagnose why a feed is failing and what to fix.

### nrmse (Normalized Root Mean Square Error)

**What it measures:** How large your pricing errors are, relative to how much the benchmark price moved during the evaluation period.

**Formula:** `nrmse = rmse / benchmark_price_range`

Where `benchmark_price_range = max(benchmark_price) - min(benchmark_price)` over the evaluation day.

**How to read it:**

| nrmse Value | Interpretation |
|-------------|---------------|
| < 0.01 | Excellent — automatic pass (Path 1) |
| 0.01 – 0.05 | Acceptable — passes if hit_rate >= 95% (Path 2) |
| > 0.05 | Failing — cannot pass regardless of hit_rate |

**Why it matters:** nrmse puts your error in context. An RMSE of $9.15 sounds bad, but if Platinum moved $149.31 that day, it's only 6.1% of the range — not terrible. Conversely, an RMSE of $118.59 against a $111.76 range means your error exceeded the entire day's price movement.

### hit_rate

**What it measures:** The percentage of your price observations that landed within 10 basis points (0.1%) of the benchmark price.

**Formula:** `hit_rate = (count of observations where |publisher_price - benchmark_price| / benchmark_price < 0.001) / total_observations * 100`

**How to read it:**

| hit_rate | Interpretation |
|----------|---------------|
| >= 95% | Excellent — meets Path 2 threshold |
| 80% – 95% | Close but not passing via Path 2 |
| < 80% | Significant accuracy issues |
| 0% | No prices were within 10 basis points — severe problem |

**When it matters:** hit_rate only affects pass/fail when nrmse is between 0.01 and 0.05. But even for informational purposes, a low hit_rate signals that many individual price points are far from the benchmark.

### rmse (Root Mean Square Error)

**What it measures:** The average magnitude of your pricing errors, in the same units as the asset price (e.g., dollars for metals).

**Formula:** `rmse = sqrt(mean((publisher_price - benchmark_price)^2))`

**How to read it:** RMSE is context-dependent. A $9.15 RMSE is meaningful for Platinum at ~$1,000/oz but would be enormous for EUR/USD at ~1.08. Always interpret RMSE relative to the asset's price level, or use `nrmse` for a normalized view.

### benchmark_price_range

**What it measures:** The total range (high minus low) of the benchmark price over the evaluation period.

**Formula:** `max(benchmark_price) - min(benchmark_price)`

**Why it matters:** This is the denominator for nrmse. A wide price range makes it easier to achieve low nrmse. If you see nrmse is high on a day with a narrow range, it may indicate your errors are consistent but the benchmark didn't move much that day.

### mean_spread

**What it measures:** The average bid-ask spread from the benchmark source over the evaluation period.

**Why it matters:** This is the denominator for `rmse_over_spread`. The bid-ask spread represents the "natural" pricing uncertainty in the market. Your errors should ideally be within this spread.

### rmse_over_spread

**What it measures:** Your RMSE divided by the average benchmark bid-ask spread. This tells you whether your errors are within the market's natural pricing uncertainty.

**Formula:** `rmse_over_spread = rmse / mean_spread`

**How to read it:**

| rmse_over_spread | Interpretation |
|------------------|---------------|
| < 0.5 | Excellent — your errors are well within the spread |
| 0.5 – 1.0 | Good — your errors are comparable to the spread |
| 1.0 – 2.0 | Concerning — your errors exceed the spread |
| > 2.0 | Poor — your errors are multiple times the spread |

**Note:** This metric is NOT used for pass/fail. It is an additional quality indicator that measures your accuracy relative to market microstructure.

### mean_diff (Systematic Bias)

**What it measures:** The average of `(publisher_price - benchmark_price)` across all observations. This reveals systematic bias — whether your prices are consistently too high or too low.

**How to read it:**

| mean_diff | Interpretation |
|-----------|---------------|
| Near 0 | No systematic bias — your errors are random |
| Large positive | Your prices are consistently **higher** than benchmark |
| Large negative | Your prices are consistently **lower** than benchmark |

**Action if large:** This is often the most actionable metric. A consistent bias suggests a calibration issue with your price source — check for rounding errors, stale reference data, or timezone misalignment.

### mae (Mean Absolute Error)

**What it measures:** The average absolute deviation from the benchmark: `mean(|publisher_price - benchmark_price|)`.

**How to read it:** Similar to RMSE but less sensitive to outliers. If MAE is much lower than RMSE, you likely have occasional large spikes dragging up the RMSE. If MAE and RMSE are similar, your errors are fairly consistent in magnitude.

### n_observations

**What it measures:** The number of data points where your published price and the benchmark price were successfully matched by timestamp.

**Minimum required:** 100. If n_observations is below 100, the evaluation is invalid and will show an error.

**Typical values:** 60,000–75,000 for a full trading day of metals data. If your count is significantly lower than expected, it may indicate gaps in your publishing — missing updates or connectivity issues.

---

### Diagnostic Comparison: Two Real Examples

Here are two evaluations of the same asset (Platinum, Metal.XPT/USD) on different days, showing how the metrics tell different stories:

| Metric | Feb 12 (close but failing) | Feb 11 (badly broken) |
|--------|---------------------------|----------------------|
| `nrmse` | 0.061 | 1.061 |
| `hit_rate` | 22.46% | 0.00% |
| `rmse` | $9.15 | $118.59 |
| `benchmark_price_range` | $149.31 | $111.76 |
| `rmse_over_spread` | 0.69 | 8.79 |
| `mean_diff` | +$0.57 | -$116.27 |
| `mae` | $6.90 | $116.27 |

**Feb 12 diagnosis:** The nrmse (0.061) is just above the 0.05 threshold — close to passing but not there yet. The rmse_over_spread (0.69) is actually within the spread, suggesting your prices are reasonably close in market terms. The mean_diff (+$0.57) shows almost no bias. The main issue is scattered accuracy — individual price points vary enough to push nrmse above 0.05.

**Feb 11 diagnosis:** This is a clearly broken feed. The mean_diff (-$116.27) tells the whole story — prices were systematically $116 below benchmark, nearly equal to the MAE. This is not random error; it's a massive calibration problem. The rmse_over_spread (8.79) confirms the error is almost 9x the bid-ask spread.

---

### How to Improve Your Data Quality

**1. Fix Systematic Bias** (large `mean_diff`)
- Calibrate your price source against the benchmark
- Check for rounding or truncation errors in your pipeline
- Verify timezone handling — a timezone mismatch can cause prices to be compared against the wrong benchmark window

**2. Reduce Random Error** (high `rmse` but `mean_diff` near zero)
- Improve data freshness by reducing latency in your pipeline
- Increase your update frequency, especially during volatile periods
- Use faster upstream data sources

**3. Eliminate Outliers** (high `rmse` but low `mae`)
- Add spike detection before publishing — flag and suppress prices that deviate significantly from recent history
- Validate each price update against a moving window of recent prices
- Implement circuit breakers that pause publishing during extreme moves

---

## 3. Session Breakdown (Extended Hours and Overnight)

For US equities, your results may include metrics for additional trading sessions beyond regular hours. Each session is evaluated independently using the same pass/fail criteria.

### Trading Sessions

| Session | Time (ET) | Benchmark Source | CSV Column Prefix |
|---------|-----------|------------------|-------------------|
| Regular Hours | 9:30 AM – 4:00 PM | Datascope | *(no prefix — main columns)* |
| Pre-market | 4:00 AM – 9:30 AM | Datascope | `premarket_` |
| After-hours | 4:00 PM – 8:00 PM | Datascope | `afterhours_` |
| Overnight | 8:00 PM – 4:00 AM | Blue Ocean ATS | `overnight_` |

### Session-Specific Columns

Each session adds these columns (with the appropriate prefix):

| Column | Description |
|--------|-------------|
| `{session}_n_observations` | Data points matched in this session |
| `{session}_nrmse` | Normalized RMSE for this session |
| `{session}_hit_rate` | Hit rate for this session |
| `{session}_passes` | Pass/fail for this session (same criteria as regular hours) |
| `{session}_error` | Error message if session evaluation failed |

The overnight session also includes:
- `overnight_n_reference_observations` — data points from the reference publisher
- `overnight_reference_publisher_id` — which publisher is used as the overnight benchmark

### Key Points

**Same pass/fail criteria per session:** Each session is evaluated independently. A feed can pass during regular hours but fail during pre-market, or vice versa.

**Overnight is a peer comparison, not an official benchmark.** The overnight session uses Blue Ocean ATS as the reference because Datascope does not provide data during overnight hours. This means:
- Overnight metrics measure how closely your prices track Blue Ocean ATS
- If Blue Ocean ATS has errors during a period, your overnight metrics will be affected
- Overnight results should be interpreted with less confidence than regular-hours results

**Empty session columns** mean the session was not evaluated. This happens when:
- The evaluation was run without the extended hours or overnight flags
- The asset class doesn't have distinct sessions (e.g., metals and FX trade 24 hours, so pre-market/after-hours columns will be empty)

**Minimum observation thresholds:**
- Regular hours: 100 observations required
- Extended sessions (pre-market, after-hours, overnight): 50 observations required

---

## 4. Reading the Summary Sections

After the per-feed data rows, the CSV includes several summary blocks. These provide aggregate statistics across all your feeds.

### SUMMARY Block

The `SUMMARY` block is your overall scorecard. Key fields:

**Pass/Fail Overview:**

| Field | What It Tells You |
|-------|-------------------|
| `total_feeds` | Total number of feed/date combinations evaluated |
| `pass_count` | Feeds that met pass criteria |
| `fail_count` | Feeds that did not meet pass criteria |
| `error_count` | Feeds where evaluation could not run (data issues) |
| `pass_rate_pct` | `pass_count / (pass_count + fail_count) * 100` |
| `pass_by_nrmse_alone` | Feeds that passed via Path 1 (`nrmse < 0.01`) |
| `pass_by_nrmse_and_hit_rate` | Feeds that passed via Path 2 (`nrmse < 0.05 AND hit_rate >= 95%`) |

**Quality Distribution (nrmse):**

| Field | Meaning |
|-------|---------|
| `median_nrmse` | The middle value — 50% of your feeds are below this |
| `mean_nrmse` | The average across all feeds |
| `p90_nrmse` | 90% of your feeds are below this value |
| `p95_nrmse` | 95% of your feeds are below this value |
| `min_nrmse` / `max_nrmse` | Best and worst individual feed values |

The same distribution pattern applies to `hit_rate`, `rmse_over_spread`, and `mae`.

**How to read percentiles:** If `p90_nrmse = 1.06`, it means 90% of your feeds have nrmse below 1.06. The remaining 10% are worse. This helps you understand whether your failures are widespread or concentrated in a few outlier feeds.

**Per-Asset-Class Breakdown:**

The summary includes `pass_count_{mode}`, `fail_count_{mode}`, and `error_count_{mode}` for each asset class (e.g., `pass_count_metals`, `fail_count_fx`). This helps you identify which asset classes are performing well and which need attention.

#### Real Example

From a metals evaluation with 10 feed/date combinations:

| Summary Field | Value | Interpretation |
|---------------|-------|----------------|
| `pass_count` | 0 | No feeds passed |
| `fail_count` | 10 | All feeds failed |
| `pass_rate_pct` | 0.0% | — |
| `median_nrmse` | 0.467 | Typical feed has ~47% of price range as error |
| `p90_nrmse` | 1.061 | Worst 10% have nrmse above 1.0 |
| `median_rmse_over_spread` | 2.67 | Typical error is 2.7x the bid-ask spread |
| `median_mean_diff` | -29.13 | Systematic negative bias of ~$29 |

This summary immediately tells you: all feeds are failing, with a strong negative bias and errors well above the spread. The priority is fixing the systematic bias (median_mean_diff of -$29).

### EXTENDED_HOURS Block

The `EXTENDED_HOURS` block contains aggregate statistics for pre-market and after-hours sessions. Its structure mirrors the SUMMARY block but is scoped to those sessions only.

Fields include: `premarket_total_feeds`, `premarket_pass_count`, `premarket_fail_count`, `premarket_error_count`, `premarket_pass_rate_pct`, `premarket_median_nrmse`, `premarket_median_hit_rate` (and the same set with `afterhours_` prefix).

If all values are zero or empty, it means extended hours sessions were either not evaluated or not applicable for your asset class.

### OVERNIGHT_SESSION Block

The `OVERNIGHT_SESSION` block contains aggregate statistics for the overnight session. It includes:
- `overnight_reference_publisher_id` — the publisher used as benchmark (currently 32)
- `overnight_total_feeds`, `overnight_pass_count`, `overnight_fail_count`, etc.

Remember: overnight metrics are a peer comparison against Blue Ocean ATS, not an official benchmark.

### PER_DATE_BREAKDOWN Block

The `PER_DATE_BREAKDOWN` block shows one row per date, letting you see how your quality changed over time:

| Column | Description |
|--------|-------------|
| `date` | Evaluation date |
| `total` | Feeds evaluated on this date |
| `pass` / `fail` / `error` | Counts for this date |
| `pass_rate_pct` | Pass rate for this date |
| `median_nrmse` | Median nrmse across feeds for this date |
| `median_hit_rate` | Median hit_rate across feeds for this date |

#### Real Example

| date | total | pass | fail | median_nrmse | median_hit_rate |
|------|-------|------|------|-------------|----------------|
| 2026-02-09 | 2 | 0 | 2 | 0.519 | 2.59 |
| 2026-02-10 | 2 | 0 | 2 | 0.811 | 0.00 |
| 2026-02-11 | 2 | 0 | 2 | 0.903 | 0.00 |
| 2026-02-12 | 2 | 0 | 2 | 0.088 | 13.67 |
| 2026-02-13 | 2 | 0 | 2 | 0.260 | 8.37 |

**Reading the trend:** Feb 12 was the best day (median_nrmse = 0.088, closest to passing), while Feb 10–11 were the worst (median_nrmse > 0.8 with 0% hit rate). If you see a sudden spike in nrmse on a specific date, investigate what changed on your end that day — a data source switch, a deployment, a network issue, or a market event that exposed a weakness in your pricing.

---

## 5. Advanced: Statistical Tests

This section covers statistical metrics included in the CSV for deeper analysis beyond pass/fail. These columns may be empty if statistical tests were skipped during evaluation.

### Metric Reference

#### t_statistic / t_pvalue

**What it tests:** Whether your mean price difference is statistically different from zero (one-sample t-test).

**How to read it:**
- `t_pvalue < 0.05` means the bias is statistically significant — your prices are systematically off, not just randomly varying
- The magnitude of `t_statistic` indicates the strength of the evidence: values in the hundreds or thousands indicate overwhelming bias
- A significant t-test combined with a large `mean_diff` points to a calibration problem

#### wilcoxon_statistic / wilcoxon_pvalue

**What it tests:** Same question as the t-test (is there systematic bias?) but using a non-parametric method — the Wilcoxon signed-rank test.

**How to read it:**
- `wilcoxon_pvalue < 0.05` means significant bias
- More robust than the t-test when errors have outliers or skewed distributions
- If the t-test and Wilcoxon test disagree, trust the Wilcoxon — it makes fewer assumptions about your error distribution

#### normality_pvalue

**What it tests:** Whether your price errors follow a normal (bell curve) distribution, using the D'Agostino-Pearson test.

**How to read it:**
- `normality_pvalue >= 0.05` — errors are approximately normally distributed. This is good: it means your errors are consistent and predictable, likely caused by latency or timing rather than data corruption.
- `normality_pvalue < 0.05` — errors are NOT normally distributed. This suggests outliers, spikes, or irregular patterns in your pricing errors.

#### mean_abs_z_score

**What it measures:** The average absolute z-score of your price differences — how many standard deviations the typical error is from the mean error.

**How to read it:**
- ~0.8 is the expected value for a perfectly normal distribution
- < 0.5 indicates very stable, consistent errors (excellent)
- > 1.5 indicates frequent large deviations from the typical error — your feed has outlier problems

#### std_diff

**What it measures:** The standard deviation of `(publisher_price - benchmark_price)`. This is your error volatility — how much your errors vary from observation to observation.

**How to read it:**
- Low `std_diff` relative to `mean_diff` means your bias is consistent (the same offset every time) — easier to fix
- High `std_diff` relative to `mean_diff` means your errors are unpredictable — harder to fix, may indicate multiple sources of error

#### mean_pct_diff / std_pct_diff

**What they measure:** The same as `mean_diff` and `std_diff`, but expressed as percentages of the benchmark price rather than absolute values.

**When to use:** These are useful for comparing across assets with different price levels. A $0.57 mean_diff means very different things for Platinum at ~$1,000/oz versus Palladium at ~$950/oz. The percentage versions normalize this.

### Diagnostic Patterns

Use the statistical tests together to diagnose the root cause:

| Pattern | Likely Cause | Recommended Action |
|---------|-------------|-------------------|
| All t-tests significant + large `mean_diff` | Systematic calibration error | Recalibrate your price source against the benchmark |
| Low `normality_pvalue` + high `mean_abs_z_score` | Outlier/spike problem | Add spike detection before publishing; validate prices against recent history |
| Normal errors + low bias + moderate `nrmse` | Pure latency/timing noise | Improve update frequency; reduce pipeline latency |
| High `std_diff` relative to `mean_diff` | Inconsistent errors (not systematic) | Check for intermittent data source issues; review failover behavior |

### Real Examples

**Feb 11, Metal.XPD/USD (badly broken):**

| Metric | Value | Interpretation |
|--------|-------|----------------|
| `t_statistic` | -780.40 | Overwhelming evidence of negative bias |
| `t_pvalue` | 0.0 | Statistically significant beyond any doubt |
| `normality_pvalue` | 0.0 | Errors are NOT normally distributed |
| `mean_abs_z_score` | 0.85 | Moderate — but the systematic bias is the dominant problem |
| `mean_diff` | -$47.50 | Prices were consistently $47.50 below benchmark |

**Diagnosis:** Massive systematic bias confirmed by both t-test and Wilcoxon. Non-normal errors suggest the bias may not be constant — possibly getting worse or better during the day. Priority: fix the calibration offset.

**Feb 12, Metal.XPT/USD (much better):**

| Metric | Value | Interpretation |
|--------|-------|----------------|
| `t_statistic` | 16.75 | Much smaller magnitude than the broken example |
| `t_pvalue` | 0.0 | Still statistically significant (with 72K observations, even tiny biases are significant) |
| `normality_pvalue` | 0.0 | Errors are not normally distributed |
| `mean_abs_z_score` | 0.75 | Near the expected 0.8 — reasonable error distribution |
| `mean_diff` | +$0.57 | Tiny bias — prices are only $0.57 above benchmark on average |

**Diagnosis:** The t-test is significant, but this is expected with 72,000 observations — even a $0.57 average offset becomes statistically significant at that sample size. In practical terms, this feed's bias is negligible. The remaining errors are likely latency-driven.

---

## 6. Appendix: Full Column Reference

Quick-reference table for every column in the CSV.

### Per-Feed Row Columns

| Column | Type | Description | Target |
|--------|------|-------------|--------|
| `publisher_id` | int | Your publisher identifier | — |
| `feed_id` | int | Feed identifier | — |
| `date` | date | Evaluation date (YYYY-MM-DD) | — |
| `mode` | string | Asset class (fx, metals, us-equities, commodity, us-treasuries) | — |
| `symbol` | string | Feed symbol (e.g., `Metal.XPT/USD`, `FX.EUR/USD`) | — |
| `passes` | bool | Whether this feed met pass criteria | True |
| `n_observations` | int | Number of matched publisher/benchmark data points | > 100 |
| `nrmse` | float | RMSE normalized by benchmark price range | < 0.01 |
| `hit_rate` | float | % of prices within 10 basis points of benchmark | >= 95% |
| `benchmark_price_range` | float | Max minus min benchmark price for the day | — |
| `rmse` | float | Root Mean Square Error in price units | Low |
| `mean_spread` | float | Average benchmark bid-ask spread | — |
| `rmse_over_spread` | float | RMSE divided by mean spread | < 1.0 |
| `mean_diff` | float | Mean of (publisher - benchmark) price differences | Near 0 |
| `std_diff` | float | Standard deviation of price differences | Low |
| `mean_pct_diff` | float | Mean percentage difference | Near 0% |
| `std_pct_diff` | float | Standard deviation of percentage differences | Low |
| `mae` | float | Mean Absolute Error | Low |
| `t_statistic` | float | One-sample t-test statistic | Near 0 |
| `t_pvalue` | float | t-test p-value | > 0.05 |
| `wilcoxon_statistic` | float | Wilcoxon signed-rank test statistic | — |
| `wilcoxon_pvalue` | float | Wilcoxon test p-value | > 0.05 |
| `normality_pvalue` | float | D'Agostino-Pearson normality test p-value | > 0.05 |
| `mean_abs_z_score` | float | Mean absolute z-score of price differences | ~0.8 |
| `premarket_n_observations` | int | Pre-market matched data points | > 50 |
| `premarket_nrmse` | float | Pre-market normalized RMSE | < 0.01 |
| `premarket_hit_rate` | float | Pre-market hit rate | >= 95% |
| `premarket_passes` | bool | Pre-market pass/fail | True |
| `premarket_error` | string | Pre-market evaluation error (if any) | Empty |
| `afterhours_n_observations` | int | After-hours matched data points | > 50 |
| `afterhours_nrmse` | float | After-hours normalized RMSE | < 0.01 |
| `afterhours_hit_rate` | float | After-hours hit rate | >= 95% |
| `afterhours_passes` | bool | After-hours pass/fail | True |
| `afterhours_error` | string | After-hours evaluation error (if any) | Empty |
| `overnight_n_observations` | int | Overnight matched data points | > 50 |
| `overnight_n_reference_observations` | int | Data points from reference publisher | > 50 |
| `overnight_nrmse` | float | Overnight normalized RMSE (vs Blue Ocean ATS) | < 0.01 |
| `overnight_hit_rate` | float | Overnight hit rate (vs Blue Ocean ATS) | >= 95% |
| `overnight_passes` | bool | Overnight pass/fail | True |
| `overnight_reference_publisher_id` | int | Reference publisher for overnight (currently 32) | — |
| `overnight_error` | string | Overnight evaluation error (if any) | Empty |
| `error` | string | Main evaluation error (if any) | Empty |
| `execution_time_ms` | int | Processing time in milliseconds | — |

### Summary-Only Fields

These fields appear only in the `SUMMARY` block at the bottom of the CSV:

| Field | Type | Description |
|-------|------|-------------|
| `total_feeds` | int | Total feed/date combinations evaluated |
| `pass_count` | int | Number of passing feeds |
| `fail_count` | int | Number of failing feeds |
| `error_count` | int | Number of feeds with errors |
| `pass_rate_pct` | float | Pass rate as a percentage |
| `pass_by_nrmse_alone` | int | Feeds passing via Path 1 (nrmse < 0.01) |
| `pass_by_nrmse_and_hit_rate` | int | Feeds passing via Path 2 (nrmse < 0.05 + hit_rate >= 95%) |
| `median_nrmse` | float | Median nrmse across all feeds |
| `mean_nrmse` | float | Mean nrmse across all feeds |
| `p90_nrmse` | float | 90th percentile nrmse |
| `p95_nrmse` | float | 95th percentile nrmse |
| `min_nrmse` / `max_nrmse` | float | Best/worst nrmse |
| `median_hit_rate` / `mean_hit_rate` | float | Hit rate distribution |
| `min_hit_rate` / `max_hit_rate` | float | Best/worst hit rate |
| `median_rmse_over_spread` / `mean_rmse_over_spread` | float | RMSE/spread distribution |
| `p90_rmse_over_spread` / `p95_rmse_over_spread` | float | 90th/95th percentile RMSE/spread |
| `min_rmse_over_spread` / `max_rmse_over_spread` | float | Best/worst RMSE/spread |
| `total_observations` | int | Total data points across all feeds |
| `mean_observations_per_feed` | int | Average data points per feed |
| `median_observations_per_feed` | int | Median data points per feed |
| `median_mae` / `mean_mae` | float | MAE distribution |
| `p90_mae` / `p95_mae` | float | 90th/95th percentile MAE |
| `median_mean_diff` / `mean_mean_diff` | float | Bias distribution |
| `significant_t_tests` | int | Number of feeds with significant t-test (p < 0.05) |
| `total_t_tests` | int | Number of feeds where t-test was run |
| `t_test_significance_rate` | float | Percentage of feeds with significant bias |
| `normal_distributions` | int | Number of feeds with normally distributed errors |
| `total_normality_tests` | int | Number of feeds where normality was tested |
| `normality_rate` | float | Percentage of feeds with normal error distribution |
| `median_z_score` / `mean_z_score` | float | Z-score distribution |
| `pass_count_{mode}` | int | Per-asset-class pass count (e.g., `pass_count_metals`) |
| `fail_count_{mode}` | int | Per-asset-class fail count |
| `error_count_{mode}` | int | Per-asset-class error count |
