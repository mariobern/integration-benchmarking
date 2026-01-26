# Implementation Plan: Add Statistical Metrics + Interpretation Guide

## Overview

Add 10 statistical metrics from the research notebook (`pythresearch/data_quality/lazer/publisher_benchmark_eval.ipynb`) to `publisher_benchmark.py` and provide an interpretive summary to help publishers understand their data quality.

## New Metrics to Add

| Metric | Description | Why It Matters |
|--------|-------------|----------------|
| `mean_diff` | Mean of (publisher - benchmark) | Detects systematic bias |
| `std_diff` | Std dev of price differences | Measures error volatility |
| `mean_pct_diff` | Mean % difference | Relative accuracy |
| `std_pct_diff` | Std dev of % differences | Relative error volatility |
| `mae` | Mean Absolute Error | Average deviation magnitude |
| `t_statistic` | t-test statistic | Tests if bias is significant |
| `t_pvalue` | t-test p-value | < 0.05 = significant bias |
| `wilcoxon_statistic` | Wilcoxon test statistic | Non-parametric bias test |
| `wilcoxon_pvalue` | Wilcoxon p-value | < 0.05 = significant bias |
| `normality_pvalue` | Normality test p-value | >= 0.05 = errors are normal |
| `mean_abs_z_score` | Mean absolute z-score | Typical deviation magnitude |

---

## Files to Modify

| File | Changes |
|------|---------|
| `publisher_benchmark.py` | Add metrics calculation, summary stats, CSV output, interpretation guide |
| `requirements.txt` | Add scipy dependency |
| `CLAUDE.md` | Document new metrics |

---

## Implementation Phases

### Phase 1: Dependencies (5 min)

**File:** `requirements.txt`

Add scipy dependency:
```
scipy>=1.11.0
```

**File:** `publisher_benchmark.py` (imports section)

Add import:
```python
from scipy import stats
```

---

### Phase 2: Update Data Structures (10 min)

**File:** `publisher_benchmark.py`

**Location:** `PublisherBenchmarkResult` dataclass (lines 185-204)

Add new Optional fields after `benchmark_price_range`:

```python
# New statistical metrics
mean_diff: Optional[float] = None           # Mean of price differences
std_diff: Optional[float] = None            # Std dev of price differences
mean_pct_diff: Optional[float] = None       # Mean of percentage differences
std_pct_diff: Optional[float] = None        # Std dev of percentage differences
mae: Optional[float] = None                 # Mean Absolute Error

# Statistical tests
t_statistic: Optional[float] = None         # t-test statistic
t_pvalue: Optional[float] = None            # t-test p-value
wilcoxon_statistic: Optional[float] = None  # Wilcoxon signed-rank statistic
wilcoxon_pvalue: Optional[float] = None     # Wilcoxon p-value
normality_pvalue: Optional[float] = None    # D'Agostino-Pearson normality test p-value
mean_abs_z_score: Optional[float] = None    # Mean absolute z-score
```

---

### Phase 3: Calculation Logic (30 min)

**File:** `publisher_benchmark.py`

#### Step 3.1: Create helper function

Add after `get_benchmark_table()` function:

```python
def compute_statistical_metrics(
    diffs: list[float],
    pct_diffs: list[float],
    min_observations: int = 20
) -> dict:
    """
    Compute advanced statistical metrics for price differences.

    Args:
        diffs: List of price differences (publisher - benchmark)
        pct_diffs: List of percentage differences (signed, not absolute)
        min_observations: Minimum observations for statistical tests

    Returns:
        Dictionary containing all computed metrics (None for metrics
        that couldn't be computed due to insufficient data)
    """
    result = {
        "mean_diff": None,
        "std_diff": None,
        "mean_pct_diff": None,
        "std_pct_diff": None,
        "mae": None,
        "t_statistic": None,
        "t_pvalue": None,
        "wilcoxon_statistic": None,
        "wilcoxon_pvalue": None,
        "normality_pvalue": None,
        "mean_abs_z_score": None,
    }

    n = len(diffs)
    if n < 2:
        return result

    # Basic statistics (always computed if n >= 2)
    result["mean_diff"] = statistics.mean(diffs)
    result["std_diff"] = statistics.stdev(diffs)
    result["mean_pct_diff"] = statistics.mean(pct_diffs)
    result["std_pct_diff"] = statistics.stdev(pct_diffs) if n >= 2 else None
    result["mae"] = statistics.mean([abs(d) for d in diffs])

    # Z-score calculation
    if result["std_diff"] and result["std_diff"] > 0:
        z_scores = [(d - result["mean_diff"]) / result["std_diff"] for d in diffs]
        result["mean_abs_z_score"] = statistics.mean([abs(z) for z in z_scores])

    # Statistical tests require minimum observations
    if n < min_observations:
        return result

    # One-sample t-test: Is mean difference significantly different from 0?
    try:
        t_stat, t_pval = stats.ttest_1samp(diffs, 0)
        result["t_statistic"] = float(t_stat)
        result["t_pvalue"] = float(t_pval)
    except Exception:
        pass  # Keep as None if test fails

    # Wilcoxon signed-rank test: Non-parametric alternative
    try:
        non_zero_diffs = [d for d in diffs if d != 0]
        if len(non_zero_diffs) >= min_observations:
            w_stat, w_pval = stats.wilcoxon(non_zero_diffs)
            result["wilcoxon_statistic"] = float(w_stat)
            result["wilcoxon_pvalue"] = float(w_pval)
    except Exception:
        pass  # Keep as None if test fails

    # D'Agostino-Pearson normality test
    try:
        _, norm_pval = stats.normaltest(diffs)
        result["normality_pvalue"] = float(norm_pval)
    except Exception:
        pass  # Keep as None if test fails

    return result
```

#### Step 3.2: Update evaluate_publisher_feed()

**Location:** Around line 561, after initializing lists

Add new list to store raw differences:
```python
diffs = []  # Raw price differences for statistical tests
signed_pct_diffs = []  # Signed percentage differences
```

**Location:** In the loop (around line 574)

Add after computing `diff` and `pct_diff`:
```python
diffs.append(diff)
signed_pct_diffs.append((diff / bench_price) * 100)  # Signed pct diff
```

**Location:** After RMSE/hit_rate calculation (around line 617)

Add:
```python
# Compute advanced statistical metrics
stat_metrics = compute_statistical_metrics(diffs, signed_pct_diffs)
```

**Location:** Update return statement to include new fields

---

### Phase 4: Summary Statistics (20 min)

**File:** `publisher_benchmark.py`

**Location:** `compute_summary_stats()` function

Add aggregations for new metrics:

```python
# MAE statistics
valid_mae_results = [r for r in results if r.mae is not None and r.error is None]
valid_mae_values = [r.mae for r in valid_mae_results]

if valid_mae_values:
    sorted_mae = sorted(valid_mae_values)
    median_mae = statistics.median(sorted_mae)
    mean_mae = statistics.mean(sorted_mae)
    # Use quantiles for p90/p95
else:
    median_mae = mean_mae = p90_mae = p95_mae = None

# Mean difference statistics
valid_mean_diff = [r.mean_diff for r in results if r.mean_diff is not None and r.error is None]
if valid_mean_diff:
    median_mean_diff = statistics.median(valid_mean_diff)
    mean_mean_diff = statistics.mean(valid_mean_diff)
else:
    median_mean_diff = mean_mean_diff = None

# T-test summary (count of significant results)
significant_t_tests = sum(
    1 for r in results
    if r.t_pvalue is not None and r.t_pvalue < 0.05 and r.error is None
)
total_t_tests = sum(
    1 for r in results
    if r.t_pvalue is not None and r.error is None
)

# Normality test summary
normal_distributions = sum(
    1 for r in results
    if r.normality_pvalue is not None and r.normality_pvalue >= 0.05 and r.error is None
)
total_normality_tests = sum(
    1 for r in results
    if r.normality_pvalue is not None and r.error is None
)

# Mean absolute z-score statistics
valid_z_scores = [r.mean_abs_z_score for r in results if r.mean_abs_z_score is not None and r.error is None]
if valid_z_scores:
    median_z_score = statistics.median(valid_z_scores)
    mean_z_score = statistics.mean(valid_z_scores)
else:
    median_z_score = mean_z_score = None
```

Add to return dictionary:
```python
# New statistical metrics
"median_mae": median_mae,
"mean_mae": mean_mae,
"median_mean_diff": median_mean_diff,
"mean_mean_diff": mean_mean_diff,
"significant_t_tests": significant_t_tests,
"total_t_tests": total_t_tests,
"t_test_significance_rate": round((significant_t_tests / total_t_tests * 100), 2) if total_t_tests > 0 else None,
"normal_distributions": normal_distributions,
"total_normality_tests": total_normality_tests,
"normality_rate": round((normal_distributions / total_normality_tests * 100), 2) if total_normality_tests > 0 else None,
"median_z_score": median_z_score,
"mean_z_score": mean_z_score,
```

---

### Phase 5: CSV Output (15 min)

**File:** `publisher_benchmark.py`

**Location:** `write_results_csv()` function

#### Step 5.1: Update header (line 752)

Add new columns before `error` and `execution_time_ms`:
```python
"mean_diff",
"std_diff",
"mean_pct_diff",
"std_pct_diff",
"mae",
"t_statistic",
"t_pvalue",
"wilcoxon_statistic",
"wilcoxon_pvalue",
"normality_pvalue",
"mean_abs_z_score",
```

#### Step 5.2: Update row output (line 776)

Add new field formatting:
```python
f"{r.mean_diff:.8f}" if r.mean_diff is not None else "",
f"{r.std_diff:.8f}" if r.std_diff is not None else "",
f"{r.mean_pct_diff:.6f}" if r.mean_pct_diff is not None else "",
f"{r.std_pct_diff:.6f}" if r.std_pct_diff is not None else "",
f"{r.mae:.8f}" if r.mae is not None else "",
f"{r.t_statistic:.4f}" if r.t_statistic is not None else "",
f"{r.t_pvalue:.6f}" if r.t_pvalue is not None else "",
f"{r.wilcoxon_statistic:.4f}" if r.wilcoxon_statistic is not None else "",
f"{r.wilcoxon_pvalue:.6f}" if r.wilcoxon_pvalue is not None else "",
f"{r.normality_pvalue:.6f}" if r.normality_pvalue is not None else "",
f"{r.mean_abs_z_score:.4f}" if r.mean_abs_z_score is not None else "",
```

#### Step 5.3: Add summary rows

Add after existing summary rows:
```python
# New statistical summary metrics
write_summary_row("median_mae", summary_stats.get("median_mae"))
write_summary_row("mean_mae", summary_stats.get("mean_mae"))
write_summary_row("median_mean_diff", summary_stats.get("median_mean_diff"))
write_summary_row("mean_mean_diff", summary_stats.get("mean_mean_diff"))
write_summary_row("significant_t_tests", summary_stats.get("significant_t_tests"))
write_summary_row("total_t_tests", summary_stats.get("total_t_tests"))
write_summary_row("t_test_significance_rate", summary_stats.get("t_test_significance_rate"))
write_summary_row("normal_distributions", summary_stats.get("normal_distributions"))
write_summary_row("total_normality_tests", summary_stats.get("total_normality_tests"))
write_summary_row("normality_rate", summary_stats.get("normality_rate"))
write_summary_row("median_z_score", summary_stats.get("median_z_score"))
write_summary_row("mean_z_score", summary_stats.get("mean_z_score"))
```

---

### Phase 6: Interpretation Guide (20 min)

**File:** `publisher_benchmark.py`

**Location:** After `write_results_csv()` function

Add new function:

```python
def print_interpretation_guide(summary_stats: dict) -> None:
    """Print an interpretive guide explaining what the metrics mean."""
    print(f"\n{'='*70}")
    print("INTERPRETATION GUIDE - What These Numbers Mean")
    print(f"{'='*70}")

    print("\n--- PASS/FAIL CRITERIA ---")
    print("Your feed PASSES if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 98%)")
    print("  - nrmse: RMSE normalized by benchmark price range (lower is better)")
    print("  - hit_rate: % of prices within 10 basis points of benchmark (higher is better)")

    print("\n--- ACCURACY METRICS ---")
    print("MAE (Mean Absolute Error):")
    print("  - Average absolute deviation from benchmark price")
    print("  - Interpretation: Lower is better; should be small relative to asset price")
    if summary_stats.get("median_mae") is not None:
        print(f"  - Your median MAE: {summary_stats['median_mae']:.8f}")

    mean_diff = summary_stats.get("mean_mean_diff")
    if mean_diff is not None:
        print(f"\nMean Difference (Systematic Bias): {mean_diff:.8f}")
        if abs(mean_diff) < 1e-8:
            print("  - Your prices show NO systematic bias (excellent)")
        elif mean_diff > 0:
            print("  - Your prices tend to be HIGHER than benchmark")
            print("  - ACTION: Review price source calibration")
        else:
            print("  - Your prices tend to be LOWER than benchmark")
            print("  - ACTION: Review price source calibration")

    print("\n--- STATISTICAL TESTS ---")

    t_rate = summary_stats.get("t_test_significance_rate")
    total_t = summary_stats.get("total_t_tests", 0)
    sig_t = summary_stats.get("significant_t_tests", 0)
    if t_rate is not None:
        print(f"\nT-Test Significance: {sig_t}/{total_t} feeds ({t_rate:.1f}%)")
        print("  - Tests if mean price difference is statistically different from zero")
        if t_rate > 50:
            print("  - HIGH rate (>50%) suggests systematic pricing bias across many feeds")
            print("  - ACTION: Investigate price source accuracy and calibration")
        elif t_rate > 20:
            print("  - MODERATE rate suggests some feeds have systematic bias")
            print("  - ACTION: Review failing feeds individually")
        else:
            print("  - LOW rate (<20%) is good - differences appear mostly random")

    norm_rate = summary_stats.get("normality_rate")
    total_norm = summary_stats.get("total_normality_tests", 0)
    normal_count = summary_stats.get("normal_distributions", 0)
    if norm_rate is not None:
        print(f"\nNormality Test: {normal_count}/{total_norm} feeds ({norm_rate:.1f}%) have normally distributed errors")
        if norm_rate >= 70:
            print("  - HIGH rate indicates consistent, predictable error patterns")
            print("  - Errors are likely due to latency/timing rather than data issues")
        elif norm_rate >= 40:
            print("  - MODERATE rate - mixed error patterns")
        else:
            print("  - LOW rate suggests outliers or irregular error patterns")
            print("  - ACTION: Investigate data quality issues, latency spikes, or stale prices")

    median_z = summary_stats.get("median_z_score")
    if median_z is not None:
        print(f"\nMedian Z-Score: {median_z:.4f}")
        print("  - Average deviation from mean in standard deviation units")
        print("  - Expected value for normal distribution: ~0.8")
        if median_z > 1.5:
            print("  - HIGH z-scores indicate frequent large deviations (outliers)")
            print("  - ACTION: Add spike detection or validate price updates")
        elif median_z < 0.5:
            print("  - LOW z-scores indicate very stable, consistent pricing (excellent)")
        else:
            print("  - NORMAL range - typical error volatility")

    print(f"\n{'='*70}")
    print("HOW TO IMPROVE YOUR DATA QUALITY")
    print(f"{'='*70}")
    print("1. REDUCE SYSTEMATIC BIAS:")
    print("   - Calibrate your price source against benchmark")
    print("   - Check for rounding or truncation issues")
    print("   - Verify timezone handling is correct")
    print("\n2. REDUCE RANDOM ERROR:")
    print("   - Improve data freshness (reduce latency)")
    print("   - Increase update frequency during volatile periods")
    print("   - Use faster data sources")
    print("\n3. REDUCE OUTLIERS:")
    print("   - Add spike detection before publishing")
    print("   - Validate price updates against recent history")
    print("   - Implement circuit breakers for extreme moves")
    print("\n4. INCREASE HIT RATE:")
    print("   - Target: >98% of prices within 10 basis points")
    print("   - Monitor real-time deviation from benchmark")
    print("   - Alert on sustained deviations")
    print(f"{'='*70}\n")
```

**Location:** In `main()` function, after existing console summary

Add call:
```python
print_interpretation_guide(summary_stats)
```

---

### Phase 7: Documentation (10 min)

**File:** `CLAUDE.md`

Add new section after "Publisher Benchmark Summary":

```markdown
### Advanced Statistical Metrics

The `publisher_benchmark.py` script includes advanced statistical metrics for deeper analysis:

**Per-Feed Metrics:**

| Metric | Description | Interpretation |
|--------|-------------|----------------|
| `mean_diff` | Mean of (publisher - benchmark) | Systematic bias; should be ~0 |
| `std_diff` | Std dev of price differences | Error volatility; lower is better |
| `mean_pct_diff` | Mean % difference | Relative accuracy |
| `std_pct_diff` | Std dev of % differences | Relative error volatility |
| `mae` | Mean Absolute Error | Average deviation; lower is better |
| `t_statistic` | t-test statistic | Tests if bias is significant |
| `t_pvalue` | t-test p-value | < 0.05 indicates significant bias |
| `wilcoxon_statistic` | Wilcoxon test statistic | Non-parametric bias test |
| `wilcoxon_pvalue` | Wilcoxon p-value | < 0.05 indicates significant bias |
| `normality_pvalue` | Normality test p-value | >= 0.05 means errors are normally distributed |
| `mean_abs_z_score` | Mean |z-score| | Typical deviation magnitude; ~0.8 expected |

**Summary Metrics:**

| Metric | Description |
|--------|-------------|
| `t_test_significance_rate` | % of feeds with statistically significant bias (p < 0.05) |
| `normality_rate` | % of feeds with normally distributed errors |
| `median_z_score` | Typical z-score across all feeds |

**Interpretation Guide:**

The script outputs an interpretation guide explaining:
- What each metric means
- How to interpret your results (good/bad thresholds)
- Actionable recommendations for improving data quality
```

---

## Expected Performance Impact

| Operation | Time Added |
|-----------|------------|
| Basic stats (mean, std, mae) | ~1-2ms |
| Z-score calculation | ~1ms |
| t-test | ~1-2ms |
| Wilcoxon test | ~5-10ms |
| Normality test | ~1-2ms |
| **Total per feed** | **~10-20ms** |

Current average: ~200ms per feed
New average: ~215ms per feed
**Slowdown: ~5-10%** (acceptable)

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Statistical tests fail on edge cases | Medium | Wrap in try/except, return None |
| Performance degradation | Low | ~15ms per feed is acceptable |
| CSV backwards compatibility | Low | New columns added before error column |
| scipy import failure | Low | Already in venv; add to requirements.txt |

---

## Testing Checklist

- [ ] All 11 new metrics appear in per-feed CSV output
- [ ] Summary section includes aggregated statistical metrics
- [ ] Interpretation guide prints after summary
- [ ] Performance impact < 20ms per feed
- [ ] No errors when processing feeds with < 20 observations
- [ ] scipy declared in requirements.txt
- [ ] CLAUDE.md documents new metrics
- [ ] Existing pass/fail logic unchanged

---

## Execution Order

1. Phase 1: Dependencies (requirements.txt, imports)
2. Phase 2: Dataclass fields
3. Phase 3: Helper function + calculation logic
4. Phase 4: Summary statistics
5. Phase 5: CSV output
6. Phase 6: Interpretation guide
7. Phase 7: Documentation

**Estimated Total Time:** ~2 hours
