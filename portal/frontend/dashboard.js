/**
 * Publisher Performance Dashboard JavaScript
 */

// State
const state = {
  publisherId: null,
  date: null,
  tab: "benchmark",
  benchmarkPage: 0,
  benchmarkLimit: 25,
  benchmarkTotal: 0,
  dashboardData: null,
};

// Chart instances
let benchmarkTrendChart = null;
let uptimeTrendChart = null;

// API base URL
const API_BASE = ""; // Same origin

// Initialize on page load
document.addEventListener("DOMContentLoaded", init);

async function init() {
  // Set default date to yesterday
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  document.getElementById("targetDate").value = yesterday
    .toISOString()
    .split("T")[0];

  // Load publishers
  await loadPublishers();

  // Load dashboard for selected publisher
  const publisherSelect = document.getElementById("publisherId");
  if (publisherSelect.value) {
    state.publisherId = parseInt(publisherSelect.value);
    state.date = document.getElementById("targetDate").value;
    await loadDashboard();
  }

  // Event listeners
  publisherSelect.addEventListener("change", async (e) => {
    state.publisherId = parseInt(e.target.value);
    state.benchmarkPage = 0;
    await loadDashboard();
  });

  document
    .getElementById("targetDate")
    .addEventListener("change", async (e) => {
      state.date = e.target.value;
      state.benchmarkPage = 0;
      await loadDashboard();
    });
}

async function loadPublishers() {
  try {
    const response = await fetch(`${API_BASE}/publishers/?has_results=true`);
    if (!response.ok) throw new Error("Failed to load publishers");

    const publishers = await response.json();
    const select = document.getElementById("publisherId");

    select.innerHTML = publishers
      .map(
        (p) =>
          `<option value="${p.publisher_id}">${
            p.name || "Publisher " + p.publisher_id
          } (${p.pass_rate_pct?.toFixed(1) || "N/A"}%)</option>`,
      )
      .join("");

    if (publishers.length > 0) {
      state.publisherId = publishers[0].publisher_id;
    }
  } catch (error) {
    console.error("Error loading publishers:", error);
    document.getElementById("publisherId").innerHTML =
      '<option value="">Error loading publishers</option>';
  }
}

async function loadDashboard() {
  if (!state.publisherId) return;

  state.date = document.getElementById("targetDate").value;

  try {
    // Load dashboard data
    const dashboardUrl = state.date
      ? `${API_BASE}/publishers/${state.publisherId}/dashboard?target_date=${state.date}`
      : `${API_BASE}/publishers/${state.publisherId}/dashboard`;

    const response = await fetch(dashboardUrl);
    if (!response.ok) throw new Error("Failed to load dashboard");

    state.dashboardData = await response.json();

    // Update summary cards
    updateSummaryCards(state.dashboardData);

    // Update alerts
    updateAlerts(state.dashboardData.alerts);

    // Load tab-specific data
    if (state.tab === "benchmark") {
      await loadBenchmarkResults();
    } else if (state.tab === "uptime") {
      await loadUptimeResults();
    } else if (state.tab === "trends") {
      await loadTrends();
    }
  } catch (error) {
    console.error("Error loading dashboard:", error);
  }
}

function updateSummaryCards(data) {
  // Pass rate
  const passRateEl = document.getElementById("passRate");
  if (data.benchmark.pass_rate_pct !== null) {
    passRateEl.textContent = `${data.benchmark.pass_rate_pct.toFixed(1)}%`;
    passRateEl.parentElement.className =
      data.benchmark.pass_rate_pct >= 90
        ? "summary-card summary-card--pass"
        : data.benchmark.pass_rate_pct >= 75
          ? "summary-card summary-card--warning"
          : "summary-card summary-card--fail";
  } else {
    passRateEl.textContent = "N/A";
  }

  // Median NRMSE
  const nrmseEl = document.getElementById("medianNrmse");
  if (data.benchmark.median_nrmse !== null) {
    nrmseEl.textContent = data.benchmark.median_nrmse.toFixed(4);
    nrmseEl.parentElement.className =
      data.benchmark.median_nrmse < 0.01
        ? "summary-card summary-card--pass"
        : data.benchmark.median_nrmse < 0.05
          ? "summary-card summary-card--warning"
          : "summary-card summary-card--fail";
  } else {
    nrmseEl.textContent = "N/A";
  }

  // Median Uptime
  const uptimeEl = document.getElementById("medianUptime");
  if (data.uptime.overall_median_uptime_pct !== null) {
    uptimeEl.textContent = `${data.uptime.overall_median_uptime_pct.toFixed(
      2,
    )}%`;
    uptimeEl.parentElement.className =
      data.uptime.overall_median_uptime_pct >= 99
        ? "summary-card summary-card--pass"
        : data.uptime.overall_median_uptime_pct >= 95
          ? "summary-card summary-card--warning"
          : "summary-card summary-card--fail";
  } else {
    uptimeEl.textContent = "N/A";
    uptimeEl.parentElement.className = "summary-card summary-card--info";
  }

  // Total Feeds
  document.getElementById("totalFeeds").textContent =
    data.benchmark.total_feeds || 0;
}

function updateAlerts(alerts) {
  const container = document.getElementById("alertsList");

  if (!alerts.top_issues || alerts.top_issues.length === 0) {
    container.innerHTML =
      '<div class="empty-state"><div class="empty-state__message">No issues to address</div></div>';
    return;
  }

  container.innerHTML = alerts.top_issues
    .map(
      (alert) => `
    <div class="alert-item alert-item--${alert.severity}">
      <span class="alert-item__icon">${
        alert.severity === "critical" ? "!" : "i"
      }</span>
      <span class="alert-item__message">${escapeHtml(alert.message)}</span>
    </div>
  `,
    )
    .join("");
}

async function loadBenchmarkResults() {
  const tableBody = document.getElementById("benchmarkTableBody");
  tableBody.innerHTML =
    '<tr><td colspan="6" class="loading">Loading data...</td></tr>';

  try {
    const skip = state.benchmarkPage * state.benchmarkLimit;
    const url = `${API_BASE}/publishers/${state.publisherId}/feeds?target_date=${state.date}&skip=${skip}&limit=${state.benchmarkLimit}`;

    const response = await fetch(url);
    if (!response.ok) throw new Error("Failed to load benchmark results");

    const data = await response.json();
    state.benchmarkTotal = data.total;

    if (data.items.length === 0) {
      tableBody.innerHTML =
        '<tr><td colspan="6" class="empty-state"><div class="empty-state__message">No benchmark results found</div></td></tr>';
    } else {
      tableBody.innerHTML = data.items
        .map((result) => {
          const rowClass = result.error
            ? "data-table__row--error"
            : result.passes
              ? "data-table__row--pass"
              : "data-table__row--fail";

          const statusBadge = result.error
            ? '<span class="badge badge--warning">Error</span>'
            : result.passes
              ? '<span class="badge badge--pass">Pass</span>'
              : '<span class="badge badge--fail">Fail</span>';

          return `
          <tr class="${rowClass}">
            <td>${escapeHtml(result.symbol || "Feed " + result.feed_id)}</td>
            <td>${escapeHtml(result.asset_class || "N/A")}</td>
            <td>${result.nrmse !== null ? result.nrmse.toFixed(4) : "N/A"}</td>
            <td>${
              result.hit_rate !== null
                ? result.hit_rate.toFixed(2) + "%"
                : "N/A"
            }</td>
            <td>${result.n_observations || 0}</td>
            <td>${statusBadge}</td>
          </tr>
        `;
        })
        .join("");
    }

    // Update pagination
    updateBenchmarkPagination(data);
  } catch (error) {
    console.error("Error loading benchmark results:", error);
    tableBody.innerHTML =
      '<tr><td colspan="6" class="empty-state"><div class="empty-state__message">Error loading data</div></td></tr>';
  }
}

function updateBenchmarkPagination(data) {
  const start = data.skip + 1;
  const end = Math.min(data.skip + data.items.length, data.total);
  document.getElementById("benchmarkPaginationInfo").textContent =
    data.total > 0 ? `Showing ${start}-${end} of ${data.total}` : "No results";

  document.getElementById("benchmarkPrevBtn").disabled =
    state.benchmarkPage === 0;
  document.getElementById("benchmarkNextBtn").disabled = !data.has_more;
}

function prevBenchmarkPage() {
  if (state.benchmarkPage > 0) {
    state.benchmarkPage--;
    loadBenchmarkResults();
  }
}

function nextBenchmarkPage() {
  const maxPage = Math.ceil(state.benchmarkTotal / state.benchmarkLimit) - 1;
  if (state.benchmarkPage < maxPage) {
    state.benchmarkPage++;
    loadBenchmarkResults();
  }
}

async function loadUptimeResults() {
  const tableBody = document.getElementById("uptimeTableBody");
  tableBody.innerHTML =
    '<tr><td colspan="6" class="loading">Loading data...</td></tr>';

  try {
    const url = `${API_BASE}/benchmarks/uptime?publisher_id=${state.publisherId}&target_date=${state.date}`;

    const response = await fetch(url);
    if (!response.ok) throw new Error("Failed to load uptime results");

    const results = await response.json();

    if (results.length === 0) {
      tableBody.innerHTML =
        '<tr><td colspan="6" class="empty-state"><div class="empty-state__message">No uptime data found</div></td></tr>';
    } else {
      tableBody.innerHTML = results
        .map((result) => {
          const rowClass =
            result.uptime_pct >= 99
              ? "data-table__row--pass"
              : result.uptime_pct >= 95
                ? ""
                : "data-table__row--fail";

          return `
          <tr class="${rowClass}">
            <td>${result.feed_id}</td>
            <td>${escapeHtml(result.asset_class || "N/A")}</td>
            <td>${escapeHtml(result.session)}</td>
            <td>${result.uptime_pct.toFixed(2)}%</td>
            <td>${formatDuration(result.downtime_ms)}</td>
            <td>${formatDuration(result.period_length_ms)}</td>
          </tr>
        `;
        })
        .join("");
    }
  } catch (error) {
    console.error("Error loading uptime results:", error);
    tableBody.innerHTML =
      '<tr><td colspan="6" class="empty-state"><div class="empty-state__message">Error loading data</div></td></tr>';
  }
}

async function loadTrends() {
  try {
    // Load benchmark trend
    const benchmarkResponse = await fetch(
      `${API_BASE}/benchmarks/trend/benchmark?publisher_id=${state.publisherId}&days=30&metric=pass_rate_pct`,
    );
    if (benchmarkResponse.ok) {
      const benchmarkTrend = await benchmarkResponse.json();
      renderBenchmarkTrendChart(benchmarkTrend);
    }

    // Load uptime trend
    const uptimeResponse = await fetch(
      `${API_BASE}/benchmarks/trend/uptime?publisher_id=${state.publisherId}&days=30&session=regular`,
    );
    if (uptimeResponse.ok) {
      const uptimeTrend = await uptimeResponse.json();
      renderUptimeTrendChart(uptimeTrend);
    }
  } catch (error) {
    console.error("Error loading trends:", error);
  }
}

function renderBenchmarkTrendChart(data) {
  const ctx = document.getElementById("benchmarkTrendChart").getContext("2d");

  if (benchmarkTrendChart) {
    benchmarkTrendChart.destroy();
  }

  benchmarkTrendChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.map((d) => d.date),
      datasets: [
        {
          label: "Pass Rate %",
          data: data.map((d) => d.value),
          borderColor: "#10B981",
          backgroundColor: "rgba(16, 185, 129, 0.1)",
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: false,
          min: 0,
          max: 100,
        },
      },
      plugins: {
        legend: {
          display: false,
        },
      },
    },
  });
}

function renderUptimeTrendChart(data) {
  const ctx = document.getElementById("uptimeTrendChart").getContext("2d");

  if (uptimeTrendChart) {
    uptimeTrendChart.destroy();
  }

  uptimeTrendChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.map((d) => d.date),
      datasets: [
        {
          label: "Uptime %",
          data: data.map((d) => d.value),
          borderColor: "#3B82F6",
          backgroundColor: "rgba(59, 130, 246, 0.1)",
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: false,
          min: 90,
          max: 100,
        },
      },
      plugins: {
        legend: {
          display: false,
        },
      },
    },
  });
}

function switchTab(tabName) {
  state.tab = tabName;

  // Update tab buttons
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("tab--active", tab.dataset.tab === tabName);
  });

  // Update tab content
  document.querySelectorAll(".tab-content").forEach((content) => {
    content.classList.toggle(
      "tab-content--active",
      content.id === `tab-${tabName}`,
    );
  });

  // Load tab-specific data
  if (tabName === "benchmark") {
    loadBenchmarkResults();
  } else if (tabName === "uptime") {
    loadUptimeResults();
  } else if (tabName === "trends") {
    loadTrends();
  }
}

async function refreshDashboard() {
  await loadDashboard();
}

// Utility functions
function escapeHtml(text) {
  if (text === null || text === undefined) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatDuration(ms) {
  if (ms === null || ms === undefined) return "N/A";

  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`;
  } else if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`;
  } else if (seconds > 0) {
    return `${seconds}s`;
  } else {
    return `${ms}ms`;
  }
}
