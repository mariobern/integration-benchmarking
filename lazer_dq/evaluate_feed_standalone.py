#!/usr/bin/env python3
"""Standalone version of publisher_benchmark_eval.ipynb.

Same logic as the notebook, but with the two ClickHouse queries that pull
publisher_updates and price_feeds patched to filter by [start_time, end_time]
(UTC) at the SQL level instead of pulling the entire UTC day. All other
queries and analysis code are unchanged from the notebook.

Run directly:
    python3 -m lazer_dq.evaluate_feed_standalone \\
        --feed-id 1021 --date 2026-05-04 --mode us-equities \\
        --cluster lazer-prod --start-time 14:30:00 --end-time 21:00:00
"""
import argparse
import sys

# === CELL 1 ===
import pandas as pd
import numpy as np
import plotly.io as pio
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.figure_factory as ff
from scipy import stats
from scipy.stats import wilcoxon, normaltest
from sklearn.metrics import mean_squared_error, mean_absolute_error
import warnings
import os
import re
import subprocess
import yaml
from pathlib import Path
from datetime import timedelta
from datetime import time
import pytz
from IPython.display import display
from jinja2 import Template
import clickhouse_connect

warnings.filterwarnings("ignore")
pio.renderers.default = "iframe_connected"
repo_root = Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
)


# === CELL 13 ===
# Define functions for data processing and pre-computation
def truncate_name(name, max_length=30):
    """Safely truncate names to specified length."""
    name_str = str(name)
    if len(name_str) > max_length:
        return name_str[:max_length] + "..."
    return name_str


def merge_benchmark_and_publisher_data(df_benchmark_data, df_publisher_data):
    """Prepare and align Exchange and Pyth data."""
    # # Copy dataframes
    df_benchmark_data_copy = df_benchmark_data.copy()
    df_publisher_data_copy = df_publisher_data.copy()

    # Convert timestamps if not already datetime
    df_benchmark_data_copy["benchmark_timestamp"] = pd.to_datetime(
        df_benchmark_data_copy["benchmark_timestamp"]
    ).astype("datetime64[ns]")
    df_publisher_data_copy["publisher_timestamp"] = pd.to_datetime(
        df_publisher_data_copy["publisher_timestamp"]
    ).astype("datetime64[ns]")

    # Sort timestamps (They should already be sorted though)
    df_benchmark_data_copy.sort_values("benchmark_timestamp", inplace=True)
    df_publisher_data_copy.sort_values("publisher_timestamp", inplace=True)

    # Use merge_asof to find nearest Exchange price for each Pyth observation
    previous_count = len(df_publisher_data_copy)
    df_aligned_prices = pd.merge_asof(
        df_publisher_data_copy,
        df_benchmark_data_copy,
        left_on="publisher_timestamp",
        right_on="benchmark_timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("60s"),
    )
    df_aligned_prices.dropna(subset=["benchmark_timestamp"], inplace=True)

    dropped_rows = previous_count - len(df_aligned_prices)
    dropped_percentage = dropped_rows / previous_count
    if dropped_rows > 0:
        print(
            f"Dropped {dropped_rows} rows ({dropped_percentage:.2%} of original) due to missing benchmark timestamp within 60s"
        )

    if len(df_aligned_prices) == 0:
        print(f"No timestamp matches found for feed {feed_id}")
        return None

    # Store benchmark data length for later check on the sample size relative to benchmark
    df_aligned_prices["benchmark_data_length"] = len(df_benchmark_data)
    df_aligned_prices["publisher_data_length"] = len(df_publisher_data)

    # Apply time filter for US equities mode
    if "mode" in globals() and mode in [
        "us-equities",
        "us-equities-pre",
        "us-equities-post",
    ]:
        # Define EST market hours based on mode
        est = pytz.timezone("US/Eastern")
        utc = pytz.UTC

        # Set time intervals based on mode
        if mode == "us-equities":
            start_time = time(9, 30, 0)
            end_time = time(16, 0, 0)
            time_label = "US equity market hours (9:30:00-16:00:00 EST)"
        elif mode == "us-equities-pre":
            start_time = time(4, 0, 0)
            end_time = time(9, 30, 0)
            time_label = "US pre-market hours (4:00:00-9:30:00 EST)"
        elif mode == "us-equities-post":
            start_time = time(16, 0, 0)
            end_time = time(20, 0, 0)
            time_label = "US post-market hours (16:00:00-20:00:00 EST)"
        elif mode == "us-equities-overnight":
            start_time = time(20, 0, 0)
            end_time = time(4, 0, 0)
            time_label = "US overnight hours (20:00:00-4:00:00 EST)"

        # Filter data by converting EST market hours to UTC for each day
        market_data = []

        # Group by date to handle DST transitions
        df_aligned_prices["date"] = df_aligned_prices["publisher_timestamp"].dt.date

        for date in df_aligned_prices["date"].unique():
            daily_data = df_aligned_prices[df_aligned_prices["date"] == date]

            # Create EST market open/close times for this date with seconds precision
            market_open_est = est.localize(pd.Timestamp.combine(date, start_time))
            market_close_est = est.localize(pd.Timestamp.combine(date, end_time))

            # Convert to UTC
            market_open_utc = market_open_est.astimezone(utc).replace(tzinfo=None)
            market_close_utc = market_close_est.astimezone(utc).replace(tzinfo=None)

            # Filter data for this day
            market_hours_mask = (
                daily_data["publisher_timestamp"] >= market_open_utc
            ) & (daily_data["publisher_timestamp"] <= market_close_utc)
            market_data.append(daily_data[market_hours_mask])

        df_aligned_prices = (
            pd.concat(market_data, ignore_index=True)
            if market_data
            else df_aligned_prices.iloc[:0]
        )
        df_aligned_prices = df_aligned_prices.drop(["date"], axis=1)

        print(
            f"   Filtered to equity market hours (9:30:00-16:00:00 EST): {len(df_aligned_prices):,} observations remaining"
        )

    # Calculate price difference
    df_aligned_prices["price_diff"] = (
        df_aligned_prices["publisher_price"] - df_aligned_prices["benchmark_price"]
    )
    df_aligned_prices["price_diff_pct"] = (
        df_aligned_prices["price_diff"] / df_aligned_prices["benchmark_price"]
    ) * 100
    df_aligned_prices["abs_price_diff"] = df_aligned_prices["price_diff"].abs()
    df_aligned_prices["spread"] = (
        df_aligned_prices["ask_price"] - df_aligned_prices["bid_price"]
    )

    return df_aligned_prices


def calculate_publisher_metrics(df_aligned_prices):
    """Calculate comprehensive metrics and precomputed visualization data for each publisher."""
    metrics = []

    for publisher in df_aligned_prices["publisher_id"].unique():
        pub_data = df_aligned_prices[df_aligned_prices["publisher_id"] == publisher]

        if len(pub_data) == 0:
            continue

        price_diff = pub_data["price_diff"]
        price_diff_pct = pub_data["price_diff_pct"]

        # --- Core statistical metrics ---
        mean_diff = price_diff.mean()
        std_diff = price_diff.std()
        mean_pct_diff = price_diff_pct.mean()
        std_pct_diff = price_diff_pct.std()
        mean_spread = pub_data["spread"].mean()

        rmse = np.sqrt(
            mean_squared_error(pub_data["benchmark_price"], pub_data["publisher_price"])
        )

        # Calculate nRMSE
        benchmark_range = (
            pub_data["benchmark_price"].max() - pub_data["benchmark_price"].min()
        )
        nrmse = rmse / benchmark_range if benchmark_range > 0 else np.nan

        rmse_over_spread = rmse / mean_spread
        mae = mean_absolute_error(
            pub_data["benchmark_price"], pub_data["publisher_price"]
        )

        # --- Statistical tests ---
        if len(pub_data) > 1:
            t_stat, t_pval = stats.ttest_1samp(price_diff, 0)
        else:
            t_stat, t_pval = np.nan, np.nan

        if len(pub_data) > 20:
            try:
                w_stat, w_pval = wilcoxon(price_diff)
            except:
                w_stat, w_pval = np.nan, np.nan
        else:
            w_stat, w_pval = np.nan, np.nan

        if len(pub_data) > 8:
            try:
                _, norm_pval = normaltest(price_diff)
            except:
                norm_pval = np.nan
        else:
            norm_pval = np.nan

        hit_rate = (price_diff_pct.abs() <= 0.1).mean() * 100

        if std_diff > 0:
            z_scores = (price_diff - mean_diff) / std_diff
            mean_abs_z_score = np.abs(z_scores).mean()
        else:
            mean_abs_z_score = 0

        # --- Pass/Fail criteria ---
        publisher_data_length = pub_data["publisher_data_length"].iloc[0]
        benchmark_data_length = pub_data["benchmark_data_length"].iloc[0]
        data_coverage = (
            publisher_data_length / benchmark_data_length
            if benchmark_data_length > 0
            else 0
        )

        pass_fail = (
            "pass"
            if (
                (nrmse < 0.01 or (nrmse < 0.05 and hit_rate > 98))
                and (
                    publisher_data_length >= 4800 or data_coverage >= 0.10
                )  # 4800 for 1 update every 3 seconds over 4 hours, the smallest session length
            )
            else "fail"
        )

        # --- Precompute histogram data (for distribution plot) ---
        nbins = 50
        counts, bin_edges = np.histogram(price_diff_pct, bins=nbins)
        bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

        hist_data = {
            "bin_centers": bin_centers.tolist(),
            "counts": counts.tolist(),
            "nbins": nbins,
        }

        # --- Precompute box plot data ---
        vals = price_diff_pct.dropna()
        if len(vals) > 0:
            q1 = vals.quantile(0.25)
            median = vals.quantile(0.5)
            q3 = vals.quantile(0.75)
            iqr = q3 - q1
            lower_whisker = max(vals.min(), q1 - 1.5 * iqr)
            upper_whisker = min(vals.max(), q3 + 1.5 * iqr)
        else:
            q1 = median = q3 = lower_whisker = upper_whisker = np.nan

        box_data = {
            "q1": q1,
            "median": median,
            "q3": q3,
            "lower": lower_whisker,
            "upper": upper_whisker,
        }

        # --- Store everything ---
        metrics.append(
            {
                "feed_id": feed_id,
                "publisher_id": publisher,
                "n_observations": len(pub_data),
                "mean_diff": mean_diff,
                "std_diff": std_diff,
                "mean_pct_diff": mean_pct_diff,
                "std_pct_diff": std_pct_diff,
                "rmse": rmse,
                "nrmse": nrmse,
                "rmse_over_spread": rmse_over_spread,
                "mae": mae,
                "t_statistic": t_stat,
                "t_pvalue": t_pval,
                "wilcoxon_statistic": w_stat,
                "wilcoxon_pvalue": w_pval,
                "normality_pvalue": norm_pval,
                "hit_rate_0.1pct": hit_rate,
                "mean_abs_z_score": mean_abs_z_score,
                "pass_fail": pass_fail,
                "histogram": hist_data,
                "boxplot": box_data,
            }
        )

    # Sort metrics by nrmse in descending order
    metrics = sorted(
        metrics,
        key=lambda x: x["nrmse"] if not np.isnan(x["nrmse"]) else float("-inf"),
        reverse=True,
    )

    return pd.DataFrame(metrics)


# === CELL 14 ===
# Define functions for creating Visualizations
def create_visualizations(df_aligned_prices, metrics_df):
    """Create comprehensive visualizations using Plotly."""

    publishers = df_aligned_prices["publisher_id"].unique()

    # Filter data using provided start and end times
    plot_start = pd.to_datetime(f"{date} {start_time}")
    plot_end = pd.to_datetime(f"{date} {end_time}")

    plot_df = df_aligned_prices[
        (df_aligned_prices["publisher_timestamp"] >= plot_start)
        & (df_aligned_prices["publisher_timestamp"] <= plot_end)
    ].copy()

    print(
        f"Plotting data from {plot_start} to {plot_end} ({len(plot_df):,} observations)"
    )

    # Color palette for publishers
    colors = px.colors.qualitative.Plotly
    publisher_colors = {
        pub: colors[i % len(colors)] for i, pub in enumerate(publishers)
    }

    # 1. Time series plot - Exchange vs Publishers
    fig_timeseries = go.Figure()

    # Add Exchange price
    exchange_sample = (
        plot_df.groupby("benchmark_timestamp")["benchmark_price"].first().reset_index()
    )
    fig_timeseries.add_trace(
        go.Scatter(
            x=exchange_sample["benchmark_timestamp"],
            y=exchange_sample["benchmark_price"],
            mode="lines",
            name="Exchange",
            line=dict(color="black", width=2),
            opacity=0.8,
        )
    )

    # Add publisher prices
    for publisher in plot_df["publisher_id"].unique():
        pub_data = plot_df[plot_df["publisher_id"] == publisher]
        fig_timeseries.add_trace(
            go.Scatter(
                x=pub_data["publisher_timestamp"],
                y=pub_data["publisher_price"],
                mode="markers",
                name=truncate_name(publisher, 30),
                marker=dict(size=4, color=publisher_colors[publisher]),
                opacity=0.6,
            )
        )

    fig_timeseries.update_layout(
        title="Benchmark vs Publisher Prices Over Time (Last 15 Minutes)",
        xaxis_title="Time",
        yaxis_title="Price ($)",
        height=600,
        hovermode="x unified",
    )

    # 2. Price differences over time (in percentage)
    fig_differences = go.Figure()

    for publisher in plot_df["publisher_id"].unique():
        pub_data = plot_df[plot_df["publisher_id"] == publisher]
        fig_differences.add_trace(
            go.Scatter(
                x=pub_data["publisher_timestamp"],
                y=pub_data["price_diff_pct"],
                mode="lines",
                name=truncate_name(publisher, 30),
                line=dict(color=publisher_colors[publisher]),
                opacity=0.7,
            )
        )

    # Add zero line
    fig_differences.add_hline(y=0, line_dash="dash", line_color="red", opacity=0.5)

    fig_differences.update_layout(
        title="Price Differences from Exchange Over Time (Last 15 Minutes)",
        xaxis_title="Time",
        yaxis_title="Price Difference (%)",
        height=600,
        hovermode="x unified",
    )

    # 3. Distribution of price differences (in percentage, using ALL data)
    fig_dist = go.Figure()

    for _, row in metrics_df.iterrows():
        fig_dist.add_trace(
            go.Bar(
                x=row["histogram"]["bin_centers"],
                y=row["histogram"]["counts"],
                name=truncate_name(row["publisher_id"], 30),
                opacity=0.5,
                marker_color=publisher_colors[row["publisher_id"]],
            )
        )

    # Add vertical line at 0
    fig_dist.add_vline(x=0, line_dash="dash", line_color="red", opacity=0.5)

    fig_dist.update_layout(
        title="Distribution of Price Differences (All Data)",
        xaxis_title="Price Difference (%)",
        yaxis_title="Frequency",
        height=600,
        barmode="overlay",
    )

    # 4. Box plot of price differences (in percentage, using ALL data)
    fig_box = go.Figure()

    # Collect precomputed stats for all publishers
    fig_box = go.Figure()
    fig_box.add_trace(
        go.Box(
            q1=[row["boxplot"]["q1"] for _, row in metrics_df.iterrows()],
            median=[row["boxplot"]["median"] for _, row in metrics_df.iterrows()],
            q3=[row["boxplot"]["q3"] for _, row in metrics_df.iterrows()],
            lowerfence=[row["boxplot"]["lower"] for _, row in metrics_df.iterrows()],
            upperfence=[row["boxplot"]["upper"] for _, row in metrics_df.iterrows()],
            name="Price Diff % (Precomputed)",
            marker_color="steelblue",
        )
    )

    # Reference line at 0
    fig_box.add_hline(y=0, line_dash="dash", line_color="red", opacity=0.5)

    fig_box.update_layout(
        title="Box Plot of Price Differences by Publisher (Precomputed)",
        yaxis_title="Price Difference (%)",
        xaxis=dict(
            tickmode="array", tickvals=list(range(len(publishers))), ticktext=publishers
        ),
        height=600,
        showlegend=False,
    )

    # 5. Heatmap of publisher metrics (without legend)
    heatmap_metrics = [
        "mean_diff",
        "std_diff",
        "rmse",
        "mae",
        "hit_rate_0.1pct",
        "mean_abs_z_score",
    ]
    heatmap_data = metrics_df.set_index("publisher_id")[heatmap_metrics]

    # Create text annotations
    text_values = []
    for metric in heatmap_metrics:
        text_values.append([f"{val:.3f}" for val in heatmap_data[metric].values])

    fig_heatmap = go.Figure(
        data=go.Heatmap(
            z=heatmap_data.T.values,
            x=[truncate_name(pub, 30) for pub in heatmap_data.index],
            y=heatmap_metrics,
            text=text_values,
            texttemplate="%{text}",
            colorscale="RdYlGn_r",
            showscale=False,  # Remove the color scale legend
        )
    )

    fig_heatmap.update_layout(
        title="Publisher Performance Metrics Heatmap",
        xaxis_title="Publisher",
        yaxis_title="Metric",
        height=500,
    )

    # 6. RMSE Ranking Chart
    # Sort metrics by RMSE (lowest to highest)
    rmse_sorted = metrics_df.sort_values("rmse")

    fig_rmse = go.Figure(
        data=[
            go.Bar(
                x=rmse_sorted["rmse"],
                y=[truncate_name(pub, 30) for pub in rmse_sorted["publisher_id"]],
                orientation="h",
                marker=dict(
                    color=rmse_sorted["rmse"], colorscale="RdYlGn_r", showscale=False
                ),
                text=rmse_sorted["rmse"].round(4),
                textposition="outside",
            )
        ]
    )

    fig_rmse.update_layout(
        title="Publisher RMSE Ranking (Lower is Better)",
        xaxis_title="RMSE ($)",
        yaxis_title="Publisher",
        height=max(
            400, len(metrics_df) * 25
        ),  # Dynamic height based on number of publishers
        margin=dict(l=200),  # More space for publisher names
    )

    # 7. Rolling statistics (using 30-minute window data)
    window = 20  # Reduced window size for 30-minute data

    # Rolling mean of absolute price difference
    fig_rolling_mean = go.Figure()

    # Get top 5 publishers by observation count
    top_publishers = metrics_df.nlargest(5, "n_observations")["publisher_id"].values

    for i, publisher in enumerate(top_publishers):
        pub_data = plot_df[plot_df["publisher_id"] == publisher].sort_values(
            "publisher_timestamp"
        )
        if len(pub_data) > window:
            rolling_mean = (
                pub_data["abs_price_diff"].rolling(window=window, min_periods=10).mean()
            )

            fig_rolling_mean.add_trace(
                go.Scatter(
                    x=pub_data["publisher_timestamp"],
                    y=rolling_mean,
                    mode="lines",
                    name=truncate_name(publisher, 30),
                    line=dict(color=colors[i % len(colors)]),
                )
            )

    fig_rolling_mean.update_layout(
        title=f"Rolling Mean of Absolute Price Difference (Last 15 Minutes, window={window})",
        xaxis_title="Time",
        yaxis_title="Mean Absolute Difference ($)",
        height=500,
    )

    # Rolling standard deviation
    fig_rolling_std = go.Figure()

    for i, publisher in enumerate(top_publishers):
        pub_data = plot_df[plot_df["publisher_id"] == publisher].sort_values(
            "publisher_timestamp"
        )
        if len(pub_data) > window:
            rolling_std = (
                pub_data["price_diff"].rolling(window=window, min_periods=10).std()
            )

            fig_rolling_std.add_trace(
                go.Scatter(
                    x=pub_data["publisher_timestamp"],
                    y=rolling_std,
                    mode="lines",
                    name=truncate_name(publisher, 30),
                    line=dict(color=colors[i % len(colors)]),
                )
            )

    fig_rolling_std.update_layout(
        title=f"Rolling Standard Deviation of Price Difference (Last 30 Minutes, window={window})",
        xaxis_title="Time",
        yaxis_title="Standard Deviation ($)",
        height=500,
    )

    return {
        "timeseries": fig_timeseries,
        "differences": fig_differences,
        "distribution": fig_dist,
        "boxplot": fig_box,
        "heatmap": fig_heatmap,
        "rmse": fig_rmse,
        "rolling_mean": fig_rolling_mean,
        "rolling_std": fig_rolling_std,
    }


# === CELL 15 ===
def print_summary_statistics(metrics_df, df_aligned_prices):
    """Print comprehensive summary statistics."""
    print("=" * 80)
    print("PUBLISHER PERFORMANCE SUMMARY")
    print("=" * 80)

    # Sort by RMSE (lower is better)
    metrics_sorted = metrics_df.sort_values("rmse")

    print("\nTop 5 Publishers by Accuracy (RMSE):")
    print("-" * 60)
    for idx, row in metrics_sorted.head().iterrows():
        pub_str = truncate_name(row["publisher_id"], 40)
        print(f"\n{pub_str}")
        print(f"  RMSE: ${row['rmse']:.6f}")
        print(f"  RMSE Over Spread: {row['rmse_over_spread']:.6f}")
        print(f"  MAE: ${row['mae']:.6f}")
        print(f"  Mean Difference: ${row['mean_diff']:.4f} ± ${row['std_diff']:.4f}")
        print(f"  Hit Rate (±0.1%): {row['hit_rate_0.1pct']:.1f}%")
        print(f"  Statistical Significance (t-test): p={row['t_pvalue']:.4f}")

    print("\n" + "=" * 80)
    print("STATISTICAL TEST RESULTS")
    print("=" * 80)

    # Count statistically significant deviations
    sig_level = 0.05
    sig_publishers = metrics_df[metrics_df["t_pvalue"] < sig_level]

    print(
        f"\nPublishers with statistically significant bias (p < {sig_level}): {len(sig_publishers)}/{len(metrics_df)}"
    )

    if len(sig_publishers) > 0:
        print("\nBiased Publishers:")
        for idx, row in sig_publishers.iterrows():
            bias_direction = "overpricing" if row["mean_diff"] > 0 else "underpricing"
            pub_str = truncate_name(row["publisher_id"], 40)
            print(f"  - {pub_str} ({bias_direction} by ${abs(row['mean_diff']):.4f})")

    print("\n" + "=" * 80)
    print("OVERALL MARKET STATISTICS")
    print("=" * 80)

    print(f"\nTotal observations: {len(df_aligned_prices):,}")
    print(
        f"Time period: {df_aligned_prices['publisher_timestamp'].min()} to {df_aligned_prices['publisher_timestamp'].max()}"
    )
    print(f"Number of publishers: {len(metrics_df)}")
    print(f"\nMarket-wide statistics:")
    print(
        f"  Mean absolute difference: ${df_aligned_prices['abs_price_diff'].mean():.4f}"
    )
    print(
        f"  Median absolute difference: ${df_aligned_prices['abs_price_diff'].median():.4f}"
    )
    print(
        f"  95th percentile difference: ${df_aligned_prices['abs_price_diff'].quantile(0.95):.4f}"
    )

    # Check for systematic market bias
    market_mean_diff = df_aligned_prices["price_diff"].mean()
    market_t_stat, market_p_val = stats.ttest_1samp(df_aligned_prices["price_diff"], 0)

    print(f"\nMarket-wide bias test:")
    print(f"  Mean difference: ${market_mean_diff:.4f}")
    print(f"  t-statistic: {market_t_stat:.4f}")
    print(f"  p-value: {market_p_val:.6f}")

    if market_p_val < 0.05:
        bias_dir = "overpriced" if market_mean_diff > 0 else "underpriced"
        print(f"  Result: Significant systematic bias detected - market is {bias_dir}")
    else:
        print("  Result: No significant systematic bias detected")


# === CELL 16 ===
# Main execution function
def run_analysis(df_benchmark_data, df_publisher_data):
    """Run the complete analysis pipeline."""
    print("Starting Exchange vs Pyth Publisher Analysis...")
    print("=" * 80)

    # Align prices
    print("\n1. Aligning Pyth prices with nearest Exchange prices...")
    df_aligned_prices = merge_benchmark_and_publisher_data(
        df_benchmark_data, df_publisher_data
    )

    if df_aligned_prices is None or len(df_aligned_prices) == 0:
        print(
            "ERROR: No aligned data found. Check if timestamps overlap between Exchange and Pyth data."
        )
        return None, None, []

    print(f"   Successfully aligned {len(df_aligned_prices):,} price observations")

    # Calculate metrics
    print("\n2. Calculating publisher metrics...")
    metrics_df = calculate_publisher_metrics(df_aligned_prices)

    # Add z-scores to aligned dataframe
    for publisher in df_aligned_prices["publisher_id"].unique():
        mask = df_aligned_prices["publisher_id"] == publisher
        pub_data = df_aligned_prices[mask]
        mean_diff = pub_data["price_diff"].mean()
        std_diff = pub_data["price_diff"].std()

        if std_diff > 0:
            df_aligned_prices.loc[mask, "z_score"] = (
                pub_data["price_diff"] - mean_diff
            ) / std_diff
        else:
            df_aligned_prices.loc[mask, "z_score"] = 0

    # Print summary statistics
    print("\n3. Summary Statistics:")
    print_summary_statistics(metrics_df, df_aligned_prices)

    # Create visualizations
    print("\n4. Creating visualizations...")
    figs = create_visualizations(df_aligned_prices, metrics_df)

    return df_aligned_prices, metrics_df, figs


# === CELL 17 ===
def output_plots(figs, output_path):
    plot_output_path = output_path / feed_id / date / "plots.html"
    plot_output_path.parent.mkdir(parents=True, exist_ok=True)
    figs_html = {
        name: fig.to_html(full_html=False, include_plotlyjs="cdn")
        for name, fig in figs.items()
    }

    # Basic HTML template with placeholders for multiple figures
    template_str = """
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>All Plots</title>
    </head>
    <body>
    {% for name, fig_html in figs.items() %}
    <h2>{{ name }}</h2>
    {{ fig_html|safe }}
    <hr/>
    {% endfor %}
    </body>
    </html>
    """
    template = Template(template_str)

    with open(plot_output_path, "w", encoding="utf-8") as f:
        f.write(template.render(figs=figs_html))

    print(f"Saved all plots for feed {feed_id} to {plot_output_path}")


def output_feed_readiness(metrics_df, output_path):
    readiness_output_path = output_path / "feed_readiness.csv"
    readiness_output_path.parent.mkdir(parents=True, exist_ok=True)

    acceptable_publishers = metrics_df.loc[
        (metrics_df["pass_fail"] == "pass")
        & (metrics_df["publisher_id"].notna())
        & (metrics_df["publisher_id"] != "")
        & (metrics_df["publisher_id"] != 0),
        "publisher_id",
    ].unique()

    df_new_row = pd.DataFrame(
        [
            {
                "feed_id": int(feed_id),
                "target_date": str(date),
                "target_pub_count": target_publisher_count,
                "acceptable_pub_count": len(acceptable_publishers),
                "ready": len(acceptable_publishers) >= target_publisher_count,
                "acceptable_publishers": sorted(list(acceptable_publishers)),
            }
        ]
    )

    if readiness_output_path.exists():
        df_existing = pd.read_csv(readiness_output_path)
        df_to_write = pd.concat([df_existing, df_new_row], ignore_index=True)
        done = df_to_write.drop_duplicates(
            subset=["feed_id", "target_date"], keep="last"
        )
    else:
        done = df_new_row

    done.to_csv(readiness_output_path, index=False)

    print(f"Updated feed {feed_id} readiness in {readiness_output_path}")


def output_feed_statistics(metrics_df, output_path):
    stats_output_path = output_path / feed_id / date / "stats.csv"
    stats_output_path.parent.mkdir(parents=True, exist_ok=True)

    output_df = metrics_df.drop(columns=["histogram", "boxplot"])
    output_df.to_csv(stats_output_path, index=False)

    print(f"Added feed {feed_id} readiness to {stats_output_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--feed-id", required=True, help="Pyth Lazer feed id, e.g. 1021"
    )
    parser.add_argument(
        "--date", required=True, help="UTC date YYYY-MM-DD, e.g. 2026-05-04"
    )
    parser.add_argument(
        "--mode",
        required=True,
        help="Mode (e.g. fx, metals, us-equities, us-equities-pre, us-equities-post, us-equities-overnight, hk-equities, us-futures, us-treasuries)",
    )
    parser.add_argument(
        "--cluster", required=True, help="Cluster name (e.g. lazer-prod)"
    )
    parser.add_argument(
        "--start-time",
        required=True,
        help="UTC start time HH:MM:SS (inclusive); pushed into ClickHouse WHERE clause",
    )
    parser.add_argument(
        "--end-time",
        required=True,
        help="UTC end time HH:MM:SS (inclusive); pushed into ClickHouse WHERE clause",
    )
    parser.add_argument(
        "--output-path",
        default=None,
        help="Base output path (default: <repo_root>/dq_reports)",
    )
    parser.add_argument(
        "--target-pub-count",
        type=int,
        default=4,
        help="Target acceptable publisher count for readiness (default: 4)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # === CELL 2 + 3 (replaced by argparse) ===
    global feed_id, date, mode, cluster, start_time, end_time, output_path, target_publisher_count
    NOTEBOOK_FEED_ID = args.feed_id
    NOTEBOOK_DATE = args.date
    NOTEBOOK_MODE = args.mode
    NOTEBOOK_CLUSTER = args.cluster
    NOTEBOOK_START_TIME = args.start_time
    NOTEBOOK_END_TIME = args.end_time
    NOTEBOOK_OUTPUT_PATH = (
        args.output_path if args.output_path else f"{repo_root}/dq_reports"
    )
    NOTEBOOK_TARGET_PUB_COUNT = args.target_pub_count

    # Convert to strings for use in the notebook
    feed_id = str(NOTEBOOK_FEED_ID)
    date = str(NOTEBOOK_DATE)
    mode = str(NOTEBOOK_MODE)
    cluster = str(NOTEBOOK_CLUSTER)
    start_time = str(NOTEBOOK_START_TIME)
    end_time = str(NOTEBOOK_END_TIME)
    output_path = Path(NOTEBOOK_OUTPUT_PATH) / f"{cluster}/{mode}"
    target_publisher_count = int(NOTEBOOK_TARGET_PUB_COUNT)

    # === CELL 4 ===
    config_path = repo_root / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    PYTH_CLICKHOUSE = config["clickhouse"]
    LAZER_CLICKHOUSE = config["lazer_clickhouse_prod"]
    ANALYTICS_CLICKHOUSE = config["analytics_clickhouse"]

    client_lazer = clickhouse_connect.get_client(
        host=LAZER_CLICKHOUSE["host"],
        # port=LAZER_CLICKHOUSE['host'],
        username=LAZER_CLICKHOUSE["user"],
        password=LAZER_CLICKHOUSE["password"],
        secure=True,
        connect_timeout=30,
        send_receive_timeout=300,
    )

    client_analytics = clickhouse_connect.get_client(
        host=ANALYTICS_CLICKHOUSE["host"],
        # port=LAZER_CLICKHOUSE['host'],
        username=ANALYTICS_CLICKHOUSE["user"],
        password=ANALYTICS_CLICKHOUSE["password"],
        secure=True,
        connect_timeout=30,
        send_receive_timeout=300,
    )

    # Initialize names that downstream branches may reference even when no
    # publisher / price-feed / benchmark data is loaded. Without these,
    # missing-data paths raise UnboundLocalError instead of reporting cleanly.
    symbol = None
    ticker = None
    ric = None

    # === CELL 5 ===
    # query mapping for feed_id and exponent
    feed_metadata_query = f"""
        SELECT
            pyth_lazer_id as feed_id,
            symbol,
            exponent,
            updated_at
        FROM feeds_metadata_latest
        FINAL
        WHERE pyth_lazer_id = {feed_id}
          AND exponent IS NOT NULL
        ORDER BY updated_at DESC
        LIMIT 1
    """
    try:
        df_feed_metadata = client_lazer.query_df(feed_metadata_query)
        print(f"Loaded ticker mapping from ClickHouse: {len(df_feed_metadata):,} rows")
        if not df_feed_metadata.empty:
            symbol = df_feed_metadata["symbol"].iloc[0]
            ticker = symbol.rsplit(".", 1)[-1].split("/")[0]
            print(f"Symbol: {symbol}, Ticker: {ticker}")
    except Exception as e:
        print(f"Error loading feed metadata from ClickHouse: {e}")

    # === CELL 6 ===
    print(df_feed_metadata.head())

    # === CELL 7 (PATCHED: time filter pushed into SQL) ===
    # Query Pyth data from ClickHouse instead of reading from file
    lazer_publisher_query = f"""
        SELECT
            pu.publisher_id,
            pu.price_feed_id as feed_id,
            pu.price as publisher_price,
            pu.publish_time as publisher_timestamp
        FROM publisher_updates pu
        INNER JOIN publishers_metadata_latest pml ON pu.publisher_id = pml.publisher_id
        WHERE (
            pu.price_feed_id = {feed_id}
            AND pu.publish_time >= '{date} {start_time}'
            AND pu.publish_time <= '{date} {end_time}'
            AND (pu.status = 'ACCEPTED' OR (pu.status = 'REJECTED' AND pu.status_reason = 'UNAUTHORIZED'))
            AND pu.price IS NOT NULL
            AND pml.key_type IN ('production','Production')
    )
    ORDER BY pu.publish_time ASCENDING
    """
    print("Querying Publisher Updates...")
    try:
        df_publisher_data = client_lazer.query_df(lazer_publisher_query)

        if len(df_publisher_data) > 0:
            print(
                f"Queried Publisher data from ClickHouse: {len(df_publisher_data):,} rows"
            )
        else:
            print(f"No Publisher data found for feed ID {feed_id} on {date}")
            df_publisher_data = pd.DataFrame()

    except Exception as e:
        print(f"Error querying Publisher data from ClickHouse: {e}")
        df_publisher_data = pd.DataFrame()

    if not df_publisher_data.empty:
        # Remove duplicates: keep last record when same publisher has same timestamp
        original_count = len(df_publisher_data)
        df_publisher_data.drop_duplicates(
            subset=["publisher_timestamp", "publisher_id"], keep="last", inplace=True
        )
        dropped_count = original_count - len(df_publisher_data)
        if dropped_count > 0:
            print(
                f"Removed {dropped_count} duplicate records (same publisher + timestamp)"
            )

        # Adjust price if exponent is not NaN
        exponent = df_feed_metadata["exponent"].iloc[0]
        if not pd.isna(exponent):
            # Convert price using exponent
            # If exponent is -5, divide by 10^5 (100000)
            divisor = 10 ** abs(exponent)
            df_publisher_data["publisher_price"] = (
                df_publisher_data["publisher_price"] / divisor
            )
            print(f"  Price adjusted by dividing by {divisor:,}")
        else:
            print("  Warning: Exponent is NaN, price not adjusted")

    else:
        print(f"No data loaded for feed ID {feed_id}")
        symbol = None
        ric = None

    # === CELL 8 (PATCHED: time filter pushed into SQL) ===
    # Query aggregate price feed data from ClickHouse
    lazer_feed_query = None
    df_feed_data_check = pd.DataFrame()
    for channel in [1, 2, 3]:
        lazer_feed_query = f"""
            SELECT
                0 as publisher_id,
                price_feed_id as feed_id,
                price as publisher_price,
                publish_time as publisher_timestamp
            FROM price_feeds
            WHERE price_feed_id = {feed_id}
              AND publish_time >= '{date} {start_time}'
              AND publish_time <= '{date} {end_time}'
              AND price IS NOT NULL
              AND channel = {channel}
            ORDER BY publish_time ASC
        """
        df_feed_data_check = client_lazer.query_df(lazer_feed_query)
        if len(df_feed_data_check) > 0:
            print(
                f"Using channel {channel} for Price Feed data ({len(df_feed_data_check):,} rows found)"
            )
            break
    else:
        print("No Price Feed data found on channels 1, 2, or 3")
        lazer_feed_query = None
    print("Querying Price Feed data...")
    try:
        if lazer_feed_query is None:
            df_feed_data = pd.DataFrame()
        else:
            df_feed_data = client_lazer.query_df(lazer_feed_query)

        if len(df_feed_data) > 0:
            print(
                f"Queried Price Feed data from ClickHouse: {len(df_feed_data):,} rows"
            )

            # Remove duplicates
            original_count = len(df_feed_data)
            df_feed_data.drop_duplicates(
                subset=["publisher_timestamp", "publisher_id"],
                keep="last",
                inplace=True,
            )
            dropped_count = original_count - len(df_feed_data)
            if dropped_count > 0:
                print(
                    f"Removed {dropped_count} duplicate records (same publisher + timestamp)"
                )

            # Adjust price using exponent
            exponent = df_feed_metadata["exponent"].iloc[0]
            if not pd.isna(exponent):
                divisor = 10 ** abs(exponent)
                df_feed_data["publisher_price"] = (
                    df_feed_data["publisher_price"] / divisor
                )
                print(f"  Price adjusted by dividing by {divisor:,}")
            else:
                print("  Warning: Exponent is NaN, price not adjusted")

            # Append to df_publisher_data
            df_publisher_data = pd.concat(
                [df_publisher_data, df_feed_data], ignore_index=True
            )
            print(
                f"Total publisher data rows after appending feed data: {len(df_publisher_data):,}"
            )
        else:
            print(f"No Price Feed data found for feed ID {feed_id} on {date}")

    except Exception as e:
        print(f"Error querying Price Feed data from ClickHouse: {e}")

    # === CELL 10 ===
    print(df_publisher_data.head())

    # === CELL 11 (UNCHANGED) ===
    # Process benchmark data if we have a valid RIC from ticker mapping
    if mode == "fx" or mode == "metals":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                pyth_lazer_id as feed_id,
                price as benchmark_price,
                bid_price,
                ask_price
            FROM datascope_fx_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND pyth_lazer_id = '{feed_id}'
              AND price IS NOT NULL
            ORDER BY benchmark_timestamp ASC, pyth_lazer_id
        """
    elif mode in (
        "us-equities",
        "us-equities-pre",
        "us-equities-post",
        "hk-equities",
    ):
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                pyth_lazer_id as feed_id,
                price as benchmark_price,
                bid_price,
                ask_price,
                qualifiers
            FROM datascope_global_equities_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND pyth_lazer_id = '{feed_id}'
              AND price IS NOT NULL
              AND (
                qualifiers IS NULL
                OR (
                qualifiers NOT LIKE '%CON[IRGCOND]%'
                AND qualifiers NOT LIKE '%ODD[IRGCOND]%'
                AND qualifiers NOT LIKE '%378[IRGCOND]%'
                AND qualifiers NOT LIKE '%705[IRGCOND]%'
                AND qualifiers NOT LIKE '%ODT[IRGCOND]%'
                AND qualifiers NOT LIKE '%DAB[IRGCOND]%'
                AND qualifiers NOT LIKE '%2795[IRGCOND]%'
                AND qualifiers NOT LIKE '%2315[IRGCOND]%'
                AND qualifiers NOT LIKE '%4445[IRGCOND]%'
                AND qualifiers NOT LIKE '%132[IRGCOND]%'
                AND qualifiers NOT LIKE '%4385[IRGCOND]%'
                AND qualifiers NOT LIKE '%DAP[IRGCOND]%'
                AND qualifiers NOT LIKE '%102[ODDSALCOND]%'
                AND qualifiers NOT LIKE '%101[IRGSALCOND]%'
                AND NOT match(qualifiers, 'PD_[A-Za-z0-9_]*')
                )
                )
            ORDER BY benchmark_timestamp ASC, pyth_lazer_id
        """
    elif mode == "us-equities-overnight":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                ric,
                {feed_id} as feed_id,
                price as benchmark_price,
                bid_price,
                ask_price,
                qualifiers
            FROM datascope_global_equities_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND ric = '{ticker}.BLUE'
              AND price IS NOT NULL
              AND (
                qualifiers IS NULL
                OR (
                    qualifiers NOT LIKE '%CON[IRGCOND]%'
                    OR qualifiers NOT LIKE '%ODD[IRGCOND]%'
                    OR qualifiers NOT LIKE '%378[IRGCOND]%'
                    OR qualifiers NOT LIKE '%2315[IRGCOND]%'
                    OR qualifiers NOT LIKE '%DAP[IRGCOND]%'
                    OR NOT match(qualifiers, 'PD_[A-Za-z0-9_]*'
                    )
                   )
                  )
            ORDER BY benchmark_timestamp ASC, feed_id
        """
    elif mode == "us-futures":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                pyth_lazer_id as feed_id,
                price as benchmark_price,
                bid_price,
                ask_price
            FROM datascope_futures_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND pyth_lazer_id = '{feed_id}'
              AND price IS NOT NULL
              AND (
                qualifiers IS NULL
                OR (
                    qualifiers NOT LIKE 'SBL[OFFBK_TYPE];K[BLKSALCOND]%'
                    AND qualifiers NOT LIKE 'Spread Price|Spread Volume[USER]%'
                    AND qualifiers NOT LIKE 'Block Trade[USER]%'
                    )
                  )
            ORDER BY benchmark_timestamp ASC, pyth_lazer_id
        """
    elif mode == "us-treasuries":
        benchmark_query = f"""
            SELECT
                date_time as benchmark_timestamp,
                pyth_lazer_id as feed_id,
                yield as benchmark_price,
                bid_yield as bid_price,
                ask_yield as ask_price
            FROM datascope_us_treasury_benchmark_data
            WHERE toDate(date_time) = '{date}'
              AND pyth_lazer_id = '{feed_id}'
              AND price IS NOT NULL
            ORDER BY benchmark_timestamp ASC, pyth_lazer_id
        """

    df_benchmark_data = pd.DataFrame()
    try:
        df_benchmark_data = client_analytics.query_df(benchmark_query)

        if len(df_benchmark_data) > 0:
            # Calculate Price (mid-price) if price is NaN
            # df_exchange['benchmark_price'] = (df_exchange['bid_price'] + df_exchange['ask_price']) / 2
            df_benchmark_data.loc[
                df_benchmark_data["benchmark_price"].isna(), "benchmark_price"
            ] = (df_benchmark_data["bid_price"] + df_benchmark_data["ask_price"]) / 2

            # Filter out rows where relevant price data is missing
            original_count = len(df_benchmark_data)
            df_benchmark_data.dropna(subset=["benchmark_price"], inplace=True)
            filtered_count = original_count - len(df_benchmark_data)

            # Metals benchmark is noisy; apply EMA smoothing to benchmark_price.
            if mode == "metals":
                df_benchmark_data.sort_values("benchmark_timestamp", inplace=True)
                df_benchmark_data["benchmark_price"] = (
                    df_benchmark_data["benchmark_price"]
                    .ewm(span=10, adjust=False)
                    .mean()
                )

            print(
                f"Benchmark data: {len(df_benchmark_data)} rows (filtered {filtered_count} rows with NaN values)"
            )
        else:
            print(f"No data found for RIC '{ric}' in benchmark data")
            df_exchange = pd.DataFrame()

    except Exception as e:
        print(f"Error querying benchmark data from ClickHouse: {e}")
        df_exchange = pd.DataFrame()

    # === CELL 12 ===
    print(df_benchmark_data.head())

    # Bail out cleanly when there is no benchmark data — downstream
    # merge_benchmark_and_publisher_data assumes a `benchmark_timestamp` column.
    if df_benchmark_data.empty:
        print(
            f"No benchmark data available for feed {feed_id} on {date} "
            f"(mode={mode}, ric={ric}, ticker={ticker}); skipping analysis."
        )
        sys.exit(2)

    # === CELL 16 bottom: run analysis ===
    df_aligned_prices, metrics_df, figs = run_analysis(
        df_benchmark_data, df_publisher_data
    )

    if df_aligned_prices is None or metrics_df is None:
        print(
            f"No alignable publisher/benchmark timestamps for feed {feed_id} on {date} "
            f"(mode={mode}); skipping analysis."
        )
        sys.exit(2)

    # === CELL 18 ===
    output_plots(figs, output_path)
    output_feed_statistics(metrics_df, output_path)
    output_feed_readiness(metrics_df, output_path)


if __name__ == "__main__":
    main()
