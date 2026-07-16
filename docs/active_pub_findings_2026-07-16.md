# Active publisher distribution — findings, 2026-07-08 → 2026-07-15

Last updated: 2026-07-16

First production run of `lazer_dq/active_pub_distribution.py` (PR #58), sweeping
every STABLE (feed, session) in `lazer_new.json` (prod snapshot 2026-07-15)
over the last 7 full UTC days — the same window as the incumbent quality sweep
(`docs/incumbent_quality_report_2026-07-15.md`), so concentration findings are
directly comparable.

**Run:** 1,661 STABLE feeds → 2,537 feed-sessions, 0 feed failures, ~35 min at
16 workers. Outputs: `output_csv/active_pub_distribution_2026-07-08_2026-07-15.csv`
(summary), `active_pub_publishers_…csv` (per-publisher),
`active_pub_participation_…csv` (derived), and the HTML report
`active_pub_report_2026-07-08_2026-07-15.html` (stat tiles + participation
distribution + worst-50 histogram gallery + full sortable table).

## Headline numbers

| Metric                                                                    | Value                                                        |
| ------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Feed-sessions swept                                                       | 2,537 (all with metrics; no NO_SCHEDULE / ZERO_OPEN_MINUTES) |
| Sessions with ≥1 open minute at/below min pub (audit-CRITICAL equivalent) | 310 (12.2%) — 271 excluding internal/test feeds              |
| Sessions spending ≥50% of open minutes at/below min pub                   | 78 — 39 excluding internal/test feeds                        |
| Median participation rate (publisher-minutes delivered ÷ possible)        | 91.1%; peak bin 97.5–100% holds 30% of sessions              |
| Sessions below 60% participation                                          | 116 (4.6%)                                                   |
| Median effective publishers (inverse HHI of update shares)                | 3.1                                                          |
| Sessions with effective publishers < their own min pub                    | 656 (26%)                                                    |
| Sessions where top-3 publishers carry ≥80% of updates                     | 1,755 (69%)                                                  |
| Sessions where one publisher carries ≥50% of updates                      | 1,014 (40%)                                                  |
| Allowed publisher slots with zero updates all week                        | 1,186, spread over 926 sessions                              |

## 1. Presence is healthy; the distribution is strongly right-massed

The participation histogram (each session once; x = publisher-minutes delivered
÷ allowed × open minutes) is heavily massed at the right: median 91%, 30% of
sessions in the top bin. In the framing from the team discussion, the network
as a whole sits "on the green." The risk is a long, thin left tail — 116
sessions below 60% — not a broad malaise.

## 2. But volume is concentrated almost everywhere

Participation measures presence (≥1 ACCEPTED update in a minute), not volume.
The same network that shows 91% median participation has a median of only
**3.1 effective publishers**, and on 656 sessions the effective count is below
the session's own minPublishers — rosters that look redundant on paper but run
on 2–3 real contributors. The "80% from 3 publishers" pattern raised in the
discussion is the norm: it holds on 69% of all sessions.

Most-frequent #1 contributors (by sessions where they rank first): pub 20
(713), pub 19 (683), pub 4 (221), pub 41 (197), pub 71 (148).

## 3. Pub 71: dominant and failing on 50 sessions (de-risk priority)

Cross-referencing with the incumbent quality sweep (same window): pub 71 is
the #1 contributor on 148 sessions (median share 48%) and an incumbent-quality
FAIL on 674. The overlap — **50 sessions where pub 71 both dominates update
volume (median 55% share) and fails quality** — is the highest-leverage
de-risking list. Worst examples: feed 1401 PRE_MARKET (70.8% share), 3278
POST/PRE_MARKET (~70/68%), 2300 REGULAR (69%), 3115 REGULAR (67%). Qualifying
backup publishers on these via the min_pub pipeline both fixes the audit
margin and dilutes a failing dominant source.

## 4. Worst offenders (excluding internal/test feeds)

Top of the left-skew list (`pct_minutes_le_min` desc):

| Feed                                             | Session    | min pub | allowed | active | % min ≤ min pub | Note                                |
| ------------------------------------------------ | ---------- | ------- | ------- | ------ | --------------- | ----------------------------------- |
| 3337 Equity.JP.285A/JPY                          | REGULAR    | 2       | 4       | 0      | 100%            | zero updates all week — misconfig?  |
| 1668 Equity.JP.1321/JPY                          | REGULAR    | 2       | 5       | 1      | 100%            | 1 of 5 allowed active               |
| 99973/99989/99990 Pyth.HL.\*, 99962 Pyth.DC.CRCL | REGULAR    | 1       | 3       | 0      | 100%            | new-listing cluster, zero updates   |
| 3307 Equity.US.USAR/USD                          | OVER_NIGHT | 2       | 4       | 4      | 98.7%           | all 4 present but rarely ≥3 at once |
| 3265 Commodities.Index.NATGAS/USD (+ 99941 twin) | REGULAR    | 1       | 3       | 3      | 95.4%           | median 0 active in open window      |
| 2980 Commodities.PTN6/USD                        | REGULAR    | 1       | 4       | 3      | 93.2%           | thin futures coverage               |

The two JP equities (3337, 1668) look like configuration problems, not
publisher outages: rosters exist but essentially nobody publishes.

## 5. Structural caveats (read before acting on the tail)

- **Low-cadence-by-design feeds skew the tail.** 39 of the 310 flagged
  sessions are internal/component/test feeds (`Internal.*`,
  `FeedComponent.*` dividend/K factors that update ~12–16 times per week by
  design, `Custom.PRF*`, `Pyth.BN.*`). The per-minute activity definition
  punishes them structurally. Consider excluding these prefixes from future
  sweeps or annotating them in the config.
- **Single-publisher feeds are "at min pub" by construction.** The 16
  one-publisher sessions include perfectly healthy by-design feeds
  (FundingRate.Hyperliquid.BTC/ETH at 92M/91.5M updates) alongside genuinely
  dead component feeds. `allowed_count = 1` needs its own policy, not the
  histogram lens.
- **`unlisted_active_count` fired on 1,129 sessions — too many for config
  drift alone.** Most likely production accepts on the feed-level publisher
  union while this tool scopes strictly per-session (plus real drift: the
  config snapshot is from 2026-07-15, inside the window). Needs confirmation
  with the Lazer team before treating per-session allowed lists as
  authoritative; per-session metrics here may slightly undercount
  cross-session publishers.
- **Participation ≠ volume.** A publisher ticking once per minute counts
  fully present here while contributing ~1% of updates. Read this report's
  participation view together with the concentration columns.

## 6. Suggested next steps

1. Triage the 39 real (non-internal) sessions spending ≥50% of open minutes
   at/below min pub — starting with the two JP equities and the USAR
   overnight session.
2. Run the pub-71 de-risking list (50 dominant-and-failing sessions) through
   `qualify_candidates` to find backup publishers.
3. Review the 1,186 never-publishing allowed slots (926 sessions) for
   pruning — dead entries make `allowed_count`-based margins misleading.
4. Confirm the per-session vs feed-union acceptance semantics
   (`unlisted_active_count` question) with the Lazer team.
5. Decide a policy for structurally low-cadence and single-publisher feeds
   (exclude-by-prefix or annotate) so future sweeps' tails are pure signal.

## Reproduce

```bash
python3 -m lazer_dq.active_pub_distribution --config lazer_new.json \
    --start-date 2026-07-08 --end-date 2026-07-15 --workers 16
python3 -m lazer_dq.render_active_pub_html \
    --summary output_csv/active_pub_distribution_2026-07-08_2026-07-15.csv \
    --publishers output_csv/active_pub_publishers_2026-07-08_2026-07-15.csv
```

Tool docs: `docs/active_pub_distribution.md`. Design spec:
`docs/superpowers/specs/2026-07-16-active-pub-distribution-design.md`.
