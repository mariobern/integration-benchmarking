function buildQuery() {
  const params = new URLSearchParams();
  const publisherId = document.getElementById("publisherId").value.trim();
  const targetDate = document.getElementById("targetDate").value.trim();
  const session = document.getElementById("session").value.trim();
  const assetClass = document.getElementById("assetClass").value.trim();
  const feedId = document.getElementById("feedId").value.trim();

  if (!publisherId || !targetDate) {
    alert("Publisher ID and Date are required.");
    return null;
  }
  params.set("publisher_id", publisherId);
  params.set("target_date", targetDate);
  if (session) params.set("session", session);
  if (assetClass) params.set("asset_class", assetClass);
  if (feedId) params.set("feed_id", feedId);

  return params.toString();
}

async function loadUptime() {
  const query = buildQuery();
  if (!query) return;

  const [detailRes, summaryRes] = await Promise.all([
    fetch(`/benchmarks/uptime?${query}`),
    fetch(`/benchmarks/uptime/summary?${query}`),
  ]);

  if (!detailRes.ok) {
    alert(`Failed to load uptime: ${detailRes.status}`);
    return;
  }
  if (!summaryRes.ok) {
    alert(`Failed to load uptime summary: ${summaryRes.status}`);
    return;
  }

  const data = await detailRes.json();
  const summary = await summaryRes.json();

  const summaryBody = document.getElementById("uptimeSummaryBody");
  summaryBody.innerHTML = "";
  summary.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.asset_class || ""}</td>
      <td>${row.session}</td>
      <td>${row.total_feeds}</td>
      <td>${Number(row.mean_uptime_pct).toFixed(4)}</td>
      <td>${Number(row.median_uptime_pct).toFixed(4)}</td>
      <td>${Number(row.min_uptime_pct).toFixed(4)}</td>
      <td>${Number(row.max_uptime_pct).toFixed(4)}</td>
    `;
    summaryBody.appendChild(tr);
  });

  const tbody = document.getElementById("uptimeBody");
  tbody.innerHTML = "";
  data.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.feed_id}</td>
      <td>${row.asset_class || ""}</td>
      <td>${row.session}</td>
      <td>${Number(row.uptime_pct).toFixed(4)}</td>
      <td>${row.downtime_ms}</td>
      <td>${row.period_length_ms}</td>
    `;
    tbody.appendChild(tr);
  });
}

document.getElementById("loadBtn").addEventListener("click", loadUptime);
