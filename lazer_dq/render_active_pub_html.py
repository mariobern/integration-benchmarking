"""Render active_pub_distribution CSVs into a self-contained HTML report.

Reads the summary + per-publisher CSVs written by
lazer_dq.active_pub_distribution (no ClickHouse) and writes one offline HTML
file: a worst-first gallery of per-minute active-count histograms, plus a
sortable table of every summary row.

Run:
    python3 -m lazer_dq.render_active_pub_html \
        --summary output_csv/active_pub_distribution_A_B.csv \
        --publishers output_csv/active_pub_publishers_A_B.csv
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

import pandas as pd

PAGE_CSS = """
:root{color-scheme:light;
 --surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
 --grid:#e1e0d9;--border:rgba(11,11,11,.10);--bar:#2a78d6;--bar-crit:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
 --surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--border:rgba(255,255,255,.10);--bar:#3987e5;--bar-crit:#d03b3b}}
:root[data-theme=dark]{color-scheme:dark;
 --surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--border:rgba(255,255,255,.10);--bar:#3987e5;--bar-crit:#d03b3b}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
 background:var(--page);color:var(--ink);margin:24px}
h1{font-size:20px}h2{font-size:16px;margin-top:28px}.sub{color:var(--ink-2)}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--border);
 border-radius:8px;padding:12px 14px}
.card h3{margin:0 0 10px;font-size:13px;font-weight:600}
.session{color:var(--muted);font-weight:400}
.chart{display:flex;align-items:flex-end;gap:2px;height:96px;
 border-bottom:1px solid var(--grid)}
.col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;
 height:100%;min-width:6px}
.bar{background:var(--bar);border-radius:2px 2px 0 0}
.bar.crit{background:var(--bar-crit)}
.k{font-size:9px;color:var(--muted);text-align:center;margin-top:2px}
.meta{font-size:11px;color:var(--ink-2);margin:8px 0 0;line-height:1.5}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;font-size:12px;margin-top:12px;background:var(--surface)}
th,td{border:1px solid var(--grid);padding:3px 8px;text-align:right;
 font-variant-numeric:tabular-nums;white-space:nowrap}
th{cursor:pointer;position:sticky;top:0;background:var(--surface)}
td:nth-child(-n+5),th:nth-child(-n+5){text-align:left}
"""

SORT_JS = """
document.querySelectorAll("th").forEach((th, i) => th.addEventListener("click", () => {
  const tb = th.closest("table").querySelector("tbody");
  const asc = th.dataset.asc !== "1";
  th.closest("tr").querySelectorAll("th").forEach(h => delete h.dataset.asc);
  th.dataset.asc = asc ? "1" : "";
  [...tb.rows].sort((a, b) => {
    const x = a.cells[i].textContent, y = b.cells[i].textContent;
    const nx = parseFloat(x), ny = parseFloat(y);
    const c = (isNaN(nx) || isNaN(ny)) ? x.localeCompare(y) : nx - ny;
    return asc ? c : -c;
  }).forEach(r => tb.appendChild(r));
}));
"""


def parse_hist(s) -> dict[int, float]:
    """'3:0.52;4:12.10' -> {3: 0.52, 4: 12.1}. Blank/NaN -> {}."""
    if not isinstance(s, str) or not s.strip():
        return {}
    out = {}
    for token in s.split(";"):
        k, pct = token.split(":")
        out[int(k)] = float(pct)
    return out


def gallery_rows(summary: pd.DataFrame, top: int) -> pd.DataFrame:
    """Metric rows (blank note) sorted worst-skew first."""
    rows = summary[summary["note"].fillna("") == ""].copy()
    return rows.sort_values(
        ["pct_minutes_le_min", "effective_publishers"], ascending=[False, True]
    ).head(top)


def top_publishers(detail: pd.DataFrame, feed_id, session, n=3) -> list[dict]:
    rows = detail[
        (detail["feed_id"] == feed_id) & (detail["session"] == session)
    ].nsmallest(n, "rank")
    return rows.to_dict("records")


def render_card(row, top_pubs) -> str:
    hist = parse_hist(row["active_hist"])
    min_pub = int(row["effective_min_pub"])
    allowed = int(row["allowed_count"])
    max_pct = max(hist.values(), default=0.0) or 1.0
    bars = []
    for k in range(0, allowed + 1):
        pct = hist.get(k, 0.0)
        height = round(100.0 * pct / max_pct) if pct else 0
        height = max(height, 1) if pct else 0
        crit = " crit" if k <= min_pub else ""
        bars.append(
            f'<div class="col" title="{k} active · {pct:.2f}% of open minutes">'
            f'<div class="bar{crit}" style="height:{height}%"></div>'
            f'<span class="k">{k}</span></div>'
        )
    pubs = ", ".join(
        f"{int(p['publisher_id'])} ({p['update_share_pct']:.0f}%)" for p in top_pubs
    )
    sym = html.escape(str(row["symbol"]))
    session = html.escape(str(row["session"]))
    return (
        f'<div class="card"><h3>{int(row["feed_id"])} · {sym} '
        f'<span class="session">{session}</span></h3>'
        f'<div class="chart">{"".join(bars)}</div>'
        f'<p class="meta">min pub {min_pub} (red bars ≤ min pub) · '
        f'≤min {row["pct_minutes_le_min"]:.1f}% of minutes · '
        f'active {int(row["active_pub_count"])}/{allowed} · '
        f'eff. pubs {row["effective_publishers"]:.2f} · '
        f'top-3 share {row["top3_share_pct"]:.0f}% · '
        f"top pubs: {pubs}</p></div>"
    )


def render_table(summary: pd.DataFrame) -> str:
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in summary.columns)
    body = []
    for _, r in summary.iterrows():
        tds = "".join(
            f"<td>{html.escape('' if pd.isna(v) else str(v))}</td>" for v in r
        )
        body.append(f"<tr>{tds}</tr>")
    return (
        f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def render_page(summary: pd.DataFrame, detail: pd.DataFrame, top: int) -> str:
    cards = [
        render_card(row, top_publishers(detail, row["feed_id"], row["session"]))
        for _, row in gallery_rows(summary, top).iterrows()
    ]
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Active publisher distribution</title>"
        f"<style>{PAGE_CSS}</style></head><body>"
        "<h1>Active publisher distribution</h1>"
        f'<p class="sub">{len(summary)} feed-session rows · gallery: worst '
        f"{len(cards)} by % of open minutes ≤ min pub · bar height = "
        "share of open minutes at that active-publisher count</p>"
        f'<div class="gallery">{"".join(cards)}</div>'
        "<h2>All feed-sessions (click a header to sort)</h2>"
        f"{render_table(summary)}"
        f"<script>{SORT_JS}</script></body></html>"
    )


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary", required=True)
    p.add_argument("--publishers", required=True)
    p.add_argument("--output", help="default: <summary path>.html")
    p.add_argument("--top", type=int, default=50)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    summary = pd.read_csv(args.summary)
    detail = pd.read_csv(args.publishers)
    out_path = (
        Path(args.output) if args.output else Path(args.summary).with_suffix(".html")
    )
    out_path.write_text(render_page(summary, detail, args.top), encoding="utf-8")
    print(f"Report written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
