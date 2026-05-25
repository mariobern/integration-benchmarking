# Design: Apply dq_summary "allowed" sheet → after.json

**Date:** 2026-05-26
**Status:** Approved (design); pending implementation plan
**Author:** Mario (mario@pyth.network) with Claude

## Problem

`lazer_dq/summarize_feeds.py` produces a `dq_summary_<cluster>_<date>.xlsx` workbook whose
**"allowed" sheet** lists the final, vetted `allowedPublisherIds` per feed and per session
(REGULAR / PRE_MARKET / POST_MARKET / OVER_NIGHT), already filtered and topped-up to the
redundancy floor. We want to apply those results directly into the Lazer config
(`after.json` / `after_1.json`): set the per-session and top-level `allowedPublisherIds`,
update `minPublishers`, and promote feeds from `COMING_SOON` to `STABLE` — without disturbing
sessions that are already live.

The existing `update_config_from_summary.py` does a structurally similar job but consumes a
completely different input (the `feed_readiness.py` summary CSV) and applies different rules
(intersect-across-dates, unconditional STABLE refresh). It cannot read the dq_summary
workbook, and its STABLE-feed behavior is not what we want here. This design specifies a new,
dedicated tool.

## Inputs and outputs

- **Input A — summary workbook:** `dq_summary_<cluster>_<date>.xlsx`, "allowed" sheet.
  Columns: `Feed ID | Session | allowedPublisherIds | Notes`.
  - The `Session` column is one of `(aggregate)`, `REGULAR`, `PRE_MARKET`, `POST_MARKET`,
    `OVER_NIGHT`.
  - The `allowedPublisherIds` cell is either the literal string `(no data)` or a paste-ready
    fragment `"allowedPublisherIds": [ 41, 69 ],`.
  - `(aggregate)` is the sorted union of that feed's session lists.
  - One file is a single asset class for a single date (us-equities → up to 4 sessions;
    hk-equities → REGULAR only).
- **Input B — config:** `after.json` / `after_1.json`. Protobuf-style JSON, ~5 MB,
  formatting must be preserved for clean diffs.
- **Output:** the config file edited in place (with a `.bak` backup), or a dry-run preview.

## Command

```bash
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json \
    [--dry-run]
```

One `--xlsx` per run. Each summary file is one asset class / one date, and feeds do not
overlap across asset classes, so no cross-file merge is needed. Run the tool once per file.

## Decisions (locked during brainstorming)

| # | Decision |
|---|----------|
| Scope | Full promote: set `allowedPublisherIds` + `minPublishers`, flip `COMING_SOON→STABLE`, add missing sessions. |
| Gating | Only touch feeds that have a real publisher list; feeds showing `(no data)` everywhere are skipped. |
| Top-ups | Included as-is. The "allowed" sheet already folds below-threshold top-ups into the list; we keep whatever is there (even `0 passed + N top-up` sessions). |
| State changes | `COMING_SOON → STABLE` only. STABLE feeds never change state and never have existing sessions overwritten. |
| STABLE + missing session | **Approach A (additive):** add the missing session entry; this is safe because that session is not yet live. |
| Top-level fold | When a session is added to a STABLE feed, its publishers are folded into the feed's top-level `allowedPublisherIds` (union; nothing removed). |
| minPublishers | Reuse existing defaults, including the "REGULAR with ≤5 publishers ⇒ minPublishers 2" rule. |
| Input mode | One `--xlsx` per run; read the "allowed" sheet directly (no CSV). |

## Per-(feed, session) decision matrix

The unit of decision is **(feed, session)**, not the whole feed. "Only act on COMING_SOON"
governs state changes and overwriting *existing* sessions; *adding* a brand-new session is
always permitted because it is not yet live.

| Feed state in config | Session present in feed? | Summary has a list? | Action |
|---|---|---|---|
| `COMING_SOON` | yes | yes | Overwrite session `allowedPublisherIds` + set session `minPublishers`. |
| `COMING_SOON` | no | yes | Add a new session entry. |
| `COMING_SOON` | — | (any session has data) | Flip `state` → `STABLE`; set top-level `allowedPublisherIds` = aggregate list; set top-level `minPublishers` = 1. |
| `STABLE` | yes | yes | **Leave untouched** (session is live). |
| `STABLE` | no | yes | **Add** new session entry; fold its publishers into top-level `allowedPublisherIds`. Top-level `minPublishers` left as-is. |
| any | — | `(no data)` / absent | Leave untouched. |

Feeds whose `(aggregate)` is `(no data)` (all sessions empty) are skipped entirely. Feeds
present in the summary but absent from the config produce a `WARNING` and are skipped. Feeds
in states other than `COMING_SOON` or `STABLE` (e.g. `INACTIVE`) are skipped.

## Component breakdown

### 1. Workbook reader

`parse_allowed_sheet(path) -> dict[int, FeedAllowed]` where `FeedAllowed` holds:

- `aggregate: list[int] | None`
- `sessions: dict[str, list[int] | None]` keyed by `REGULAR`/`PRE_MARKET`/`POST_MARKET`/`OVER_NIGHT`

Parsing rules:
- Open the workbook read-only via `openpyxl`; select the `allowed` sheet by name.
- Skip the title row and the header row (`Feed ID`, ...).
- Group consecutive rows by the integer in the `Feed ID` column; blank divider rows and the
  trailing "Feeds skipped..." footer are ignored (non-integer Feed ID).
- For each value cell, if it starts with `"allowedPublisherIds"`, extract the bracketed ints
  via `re.search(r"\[(.*?)\]", cell)`; otherwise `None`.
- The `Notes` column is read but not used for decisions.

### 2. Safety filter

`EXCLUDED = {0, 1, 9, 13, 15}` (publisher 0 + Lazer publishers). Applied to every list before
it is written. If any IDs are removed, emit a per-feed warning naming them. This is defensive:
`summarize_feeds.py` excludes only `{0} ∪ .Test`, not Lazer IDs, so Lazer publishers could in
principle appear in a future workbook.

### 3. minPublishers policy (reused)

```
SESSION_MIN = {REGULAR: 3, PRE_MARKET: 2, POST_MARKET: 2, OVER_NIGHT: 1}
REGULAR with publisher_count <= 5  ⇒  minPublishers 2
top-level minPublishers = 1   (set only on COMING_SOON promotion)
```

### 4. Session-entry builder (for adds)

`build_session_entry(session, pub_ids, benchmark_mapping) -> str`

The added entry contains, in this order to match the file's style:
`allowedPublisherIds`, `benchmarkMapping`, `marketSchedule`, `minPublishers`, `session`.

- `benchmarkMapping` is **copied verbatim from the same feed's REGULAR session entry** (same
  RIC / datascope identifier). This fixes a gap in `update_config_from_summary.py`, which
  inserts session entries without a `benchmarkMapping`.
- `marketSchedule` comes from a per-session template (America/New_York timezone, session time
  windows, US-equity holiday calendar) — same templates as the existing tool.
- Adds apply only to sessions for which a template exists (the extended US-equity sessions).
  hk-equities files contain only REGULAR, which every feed already has, so no add ever fires
  for them.

### 5. Config editor (surgical)

Edits are performed as regex-scoped text replacements on the raw file string to preserve
formatting exactly, following the approach already used by `update_config_from_summary.py`:
locate a feed block by `feedId`, locate a session block by `"session": "<NAME>"` within it,
replace `allowedPublisherIds` / `minPublishers` / `state` in place, or insert a new session
entry before the closing `]` of `marketSchedules`.

**Code sharing:** extract the proven block-finding/replacement primitives
(`_find_feed_block`, `_find_session_block`, and the field-replace helpers) from
`update_config_from_summary.py` into a new module `lib/json_surgery.py`. Both
`update_config_from_summary.py` and the new tool import them. This is a pure extraction with
no behavior change; the existing tool's test suite
(`tests/test_update_config_from_summary.py`) guards the refactor. The new tool's high-level
apply logic (the decision matrix) lives only in `lazer_dq/apply_allowed_to_config.py`.

### 6. Orchestration / reporting

`main()`:
1. Validate `--xlsx` and `--config` exist.
2. Parse the allowed sheet.
3. For each feed, apply the decision matrix against the raw config text.
4. Unless `--dry-run`, write a `<config>.bak` backup, then the modified text.
5. Print per-feed lines and a summary tally.

Per-feed log labels: `PROMOTE` (COMING_SOON → STABLE), `ADD-SESSION` (session added to a
STABLE or COMING_SOON feed), `SKIP (live)` (STABLE session left untouched), `SKIP (no data)`,
`WARNING (not found)`. Summary tally: feeds promoted, sessions added, feeds skipped (no data),
feeds skipped (live/other state), not-found.

## Safety

- `--dry-run` previews all changes and writes nothing.
- A real run copies `<config>` to `<config>.bak` before writing.
- Only `COMING_SOON` and `STABLE` feeds are modified; other states are skipped.
- Existing live (STABLE) sessions are never overwritten.
- The defensive publisher filter prevents `{0, 1, 9, 13, 15}` from entering any list.

## Testing

`pytest` with small synthetic fixtures (a mini "allowed" workbook built with `openpyxl` and a
mini config string), covering:

1. COMING_SOON promote, REGULAR-only feed — REGULAR list overwritten, `minPublishers` set,
   state flipped, top-level set to aggregate, top-level `minPublishers` = 1.
2. COMING_SOON feed with `≤5` REGULAR publishers ⇒ REGULAR `minPublishers` = 2.
3. STABLE feed, REGULAR-only, summary has PRE_MARKET data ⇒ PRE_MARKET entry added,
   `benchmarkMapping` copied from REGULAR, publishers folded into top-level, REGULAR untouched,
   state stays STABLE, top-level `minPublishers` untouched.
4. STABLE feed with an existing PRE_MARKET ⇒ that session is left untouched.
5. `(no data)` feed ⇒ no edits anywhere.
6. Feed in summary but absent from config ⇒ WARNING, no crash.
7. Lazer/zero filter ⇒ `{0, 1, 9, 13, 15}` stripped, warning emitted.
8. `--dry-run` ⇒ file unchanged on disk; backup created only on a real run.
9. Top-up-only session (`0 passed + N top-up`) ⇒ list still written verbatim.
10. Refactor guard: existing `test_update_config_from_summary.py` still passes after the
    `lib/json_surgery.py` extraction.

## Expected result for the 05-20 file

`dq_summary_lazer-prod_2026-05-20.xlsx` against `after_1.json`:

- 226 us-equities feeds in the sheet; **174 have a list → promoted COMING_SOON → STABLE** on
  their REGULAR publishers; 52 skipped (no data).
- Only REGULAR has data (PRE/POST/OVERNIGHT all "mode missing"), so **zero sessions are
  added** on this run.
- All 174 list-feeds are currently `COMING_SOON`, so no STABLE feed is touched.

## Out of scope

- Cross-date intersection (the workbook already represents one date's vetted result).
- Merging multiple workbooks in one run.
- Generating or refreshing `benchmarkMapping` RICs (only copied from an existing REGULAR
  entry).
- Editing feeds in states other than `COMING_SOON` / `STABLE`.
