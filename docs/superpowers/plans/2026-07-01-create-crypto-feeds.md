# Create Crypto Feeds 3407–3419 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 12 new crypto spot `/USD` price feeds to `lazer.json`, modeled verbatim on existing feed 3329, with per-feed data from `crypto.csv`, all in `COMING_SOON` state — using final feed IDs 3407, 3408, 3410–3419 (ADI/USD remapped from 3409 to 3419 because 3409 is already an unrelated existing feed).

**Architecture:** A one-off Python generator script (lives in the scratchpad, not committed) deep-copies feed 3329's dict as a template, applies per-feed overrides from `crypto.csv`, serializes each new feed to text matching the file's 4-space feed-object indentation, and splices the blocks into the raw `lazer.json` text at **two** insertion points (after feed 3406, and after feed 3409) so that feed 3409 itself is never touched and the file stays sorted ascending by `feedId`. Raw-text insertion keeps the rest of the ~7 MB file byte-for-byte unchanged. `lazer.json` is gitignored (a local config working copy, like `after.json`), so the modified file is verified on disk but never committed — there is no committed artifact from this plan. This mirrors the prior xStocks batch (see `docs/superpowers/plans/2026-06-29-create-xstocks-feeds.md`), minus the commit step, which does not apply here.

**Tech Stack:** Python 3 stdlib only (`json`, `csv`, `copy`). Run with `python3` (no `python` on this system).

## Global Constraints

- Template = feed **3329** (`Crypto.SPCXX/USD`). Every field not explicitly overridden is copied verbatim.
- New feeds: `state` = `"COMING_SOON"`, `minChannel.rate` = `"0.200000000s"`.
- `metadata.description` = the CSV `description` column **verbatim** (trimmed) — do NOT reformat into xStock-style `<NAME> XSTOCK / US DOLLAR` wording.
- Feed 3409 already exists (`Equity.US.ECHO/USD`, unrelated) and must be **left completely untouched**. The CSV row that targets `feed_id` 3409 (`ADI/USD`) is remapped to **feedId 3419** instead.
- Copied verbatim from 3329: `allowedPublisherIds` `[59, 71, 24, 29, 65, 22, 19, 80]`, `minPublishers` 3, `expiryTime`, `exponent` -8, `isEnabledInShard`, `kind`, full `marketSchedules`, `metadata.asset_type` (crypto), `metadata.instrument_type` (spot), `metadata.quote_currency` (USD).
- Per-feed overrides: `feedId`, `symbol` = `Crypto.{TICKER}/USD`, `metadata.name` = `{TICKER}USD`, `metadata.description` = trimmed CSV `description`, `metadata.cmc_id.uintValue` = CSV `cmc_id` as a string. TICKER = CSV `name` column, text before `/USD`.
- Feeds stay sorted ascending by `feedId` in the file (two splice points, per above).
- Scratchpad dir (for the script): `/private/tmp/claude-501/-Users-mariobernardi-Documents-GitHub-integration-benchmarking/442007cb-7a22-41da-a6fe-f510a5a83253/scratchpad`
- Working dir: `/Users/mariobernardi/Documents/GitHub/integration-benchmarking`

---

### Task 1: Generator script + dry-run validation

Build the script and validate everything it would produce **without writing** to `lazer.json`. The dry run is the test: it proves the 12 blocks parse, have correct fields, feed 3409 is untouched, and the splice cleanly preserves sort order.

**Files:**

- Create: `<scratchpad>/create_crypto_feeds.py` (not committed)
- Read-only inputs: `lazer.json`, `crypto.csv`

**Interfaces:**

- Consumes: nothing (first task).
- Produces: a script invoked as `python3 <scratchpad>/create_crypto_feeds.py [--write]`. Default (no flag) = dry run: prints a validation report and exits non-zero on any failure. `--write` performs the in-place splice. Both modes build the same `new_feeds` list and both `blocks_a`/`blocks_b` text.

- [ ] **Step 1: Write the script**

Create `<scratchpad>/create_crypto_feeds.py` (substitute the absolute scratchpad path from Global Constraints):

```python
#!/usr/bin/env python3
"""One-off: add crypto spot feeds 3407-3419 to lazer.json (modeled on 3329)."""
import sys
import csv
import json
import copy

REPO = "/Users/mariobernardi/Documents/GitHub/integration-benchmarking"
CONFIG = f"{REPO}/lazer.json"
CSV_PATH = f"{REPO}/crypto.csv"
TEMPLATE_ID = 3329
TAKEN_ID = 3409  # existing unrelated feed (Equity.US.ECHO/USD); must stay untouched
REMAP = {3409: 3419}  # CSV feed_id -> actual feedId to assign
PRED_BEFORE_GAP = 3406  # insert feeds with feedId < TAKEN_ID right after this feed's block
PRED_AFTER_GAP = 3409  # insert feeds with feedId > TAKEN_ID right after this feed's block

CLOSE = "\n    },\n"  # a top-level feed object's closing brace (4-space indent)


def build_feed(template, row):
    """Deep-copy the 3329 template and apply per-feed overrides from a CSV row."""
    raw_id = int(row["feed_id"])
    feed_id = REMAP.get(raw_id, raw_id)
    ticker = row["name"].split("/")[0].strip()
    description = row["description"].strip()
    cmc_id = row["cmc_id"].strip()

    f = copy.deepcopy(template)
    f["feedId"] = feed_id
    f["symbol"] = f"Crypto.{ticker}/USD"
    f["state"] = "COMING_SOON"
    f["minChannel"] = {"rate": "0.200000000s"}
    f["metadata"]["name"] = f"{ticker}USD"
    f["metadata"]["description"] = description
    f["metadata"]["cmc_id"] = {"uintValue": cmc_id}
    return f


def feed_to_block(feed):
    """Serialize one feed to text matching the file's 4-space feed-object indent."""
    body = json.dumps(feed, indent=2)
    indented = "\n".join("    " + line for line in body.split("\n"))
    return indented + ",\n"


def main():
    write = "--write" in sys.argv[1:]

    with open(CONFIG) as fh:
        text = fh.read()
    data = json.loads(text)
    feeds = data["feeds"]

    template = next(f for f in feeds if f["feedId"] == TEMPLATE_ID)
    taken_feed = next(f for f in feeds if f["feedId"] == TAKEN_ID)
    assert taken_feed["symbol"] == "Equity.US.ECHO/USD", (
        f"expected feed {TAKEN_ID} to be the untouched Equity.US.ECHO/USD feed, "
        f"got {taken_feed['symbol']!r}"
    )
    existing_ids = {f["feedId"] for f in feeds}

    with open(CSV_PATH, encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("feed_id", "").strip()]
    assert len(rows) == 12, f"expected 12 CSV rows, got {len(rows)}"

    built = [build_feed(template, r) for r in rows]

    # Pre-flight: no target ID already exists (3409 is intentionally excluded
    # from `built`'s target set since it's remapped to 3419).
    new_ids = [f["feedId"] for f in built]
    assert len(new_ids) == len(set(new_ids)) == 12, f"duplicate feedIds: {new_ids}"
    clashes = sorted(i for i in new_ids if i in existing_ids)
    assert not clashes, f"target IDs already present: {clashes}"

    # Structural checks on the generated feeds.
    for f in built:
        assert f["state"] == "COMING_SOON"
        assert f["minChannel"] == {"rate": "0.200000000s"}
        assert f["minPublishers"] == template["minPublishers"]
        assert (f["marketSchedules"][0]["allowedPublisherIds"]
                == template["marketSchedules"][0]["allowedPublisherIds"])
        assert f["symbol"] == f"Crypto.{f['metadata']['name'][:-3]}/USD"
        assert f["metadata"]["name"].endswith("USD")
        assert f["metadata"]["instrument_type"] == "spot"
        assert f["metadata"]["asset_type"] == "crypto"
        # each block must re-parse to exactly the same object
        assert json.loads(feed_to_block(f).rstrip(",\n")) == f

    group_a = sorted((f for f in built if f["feedId"] < TAKEN_ID), key=lambda x: x["feedId"])
    group_b = sorted((f for f in built if f["feedId"] > TAKEN_ID), key=lambda x: x["feedId"])
    assert not any(f["feedId"] == TAKEN_ID for f in built)
    assert [f["feedId"] for f in group_a] == [3407, 3408]
    assert [f["feedId"] for f in group_b] == [3410, 3411, 3412, 3413, 3414, 3415,
                                               3416, 3417, 3418, 3419]

    blocks_a = "".join(feed_to_block(f) for f in group_a)
    blocks_b = "".join(feed_to_block(f) for f in group_b)

    # Locate splice points: end of feed 3406's block, and end of feed 3409's block.
    marker_a = f'"feedId": {PRED_BEFORE_GAP},'
    i_a = text.index(marker_a)
    close_a = text.index(CLOSE, i_a) + len(CLOSE)

    marker_b = f'"feedId": {PRED_AFTER_GAP},'
    i_b = text.index(marker_b)
    close_b = text.index(CLOSE, i_b) + len(CLOSE)
    assert close_a < i_b, "splice point A must come before feed 3409 in the file"

    new_text = text[:close_a] + blocks_a + text[close_a:close_b] + blocks_b + text[close_b:]

    # Whole-file must still be valid JSON and have exactly +12 feeds.
    reparsed = json.loads(new_text)
    assert len(reparsed["feeds"]) == len(feeds) + 12
    new_in_file = [x for x in reparsed["feeds"]
                   if x["feedId"] in (3407, 3408, 3410, 3411, 3412, 3413, 3414,
                                      3415, 3416, 3417, 3418, 3419)]
    assert len(new_in_file) == 12
    ids_after = [x["feedId"] for x in reparsed["feeds"]]
    assert ids_after == sorted(ids_after), "feeds no longer sorted by feedId"
    reparsed_3409 = next(x for x in reparsed["feeds"] if x["feedId"] == TAKEN_ID)
    assert reparsed_3409 == taken_feed, "feed 3409 must be byte-for-byte unchanged"

    print(f"OK: {len(built)} feeds built, feedIds={sorted(new_ids)}")
    for f in built:
        print(f"  {f['feedId']} {f['symbol']} name={f['metadata']['name']} "
              f"cmc={f['metadata']['cmc_id']['uintValue']} state={f['state']}")

    if write:
        with open(CONFIG, "w") as fh:
            fh.write(new_text)
        print("WROTE lazer.json")
    else:
        print("DRY RUN (no file written). Re-run with --write to apply.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the dry run to verify it passes**

Run: `python3 <scratchpad>/create_crypto_feeds.py`
Expected: exits 0, prints `OK: 12 feeds built, feedIds=[3407, 3408, 3410, 3411, 3412, 3413, 3414, 3415, 3416, 3417, 3418, 3419]`, one summary line per feed (in CSV row order — note `3419 Crypto.ADI/USD ...` appears third, since ADI/USD is CSV row 3), and `DRY RUN (no file written).` If any `assert` fires, fix the script and re-run before proceeding.

- [ ] **Step 3: Confirm the file is untouched**

Run: `cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking && git status --short lazer.json`
Expected: no output (dry run wrote nothing).

---

### Task 2: Apply the splice

Run the generator in write mode and verify the modified file. `lazer.json` is
gitignored (a local config working copy, like `after.json`), so this task
ends with a verified on-disk file — not a git commit.

**Files:**

- Modify: `lazer.json` (adds 12 feed blocks: 2 after feed 3406, 10 after feed 3409) — gitignored, not committed

**Interfaces:**

- Consumes: `create_crypto_feeds.py` from Task 1.
- Produces: `lazer.json` on disk with feeds 3407, 3408, 3410–3419 added.

- [ ] **Step 1: Run in write mode**

Run: `python3 <scratchpad>/create_crypto_feeds.py --write`
Expected: exits 0, prints the same `OK:` report plus `WROTE lazer.json`. (All in-script asserts run before the write, so a write means every check passed, including the feed-3409-unchanged check.)

- [ ] **Step 2: Independently verify the modified file**

Run:

```bash
cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking
python3 -c "
import json
d = json.load(open('lazer.json'))
feeds = d['feeds']
target_ids = [3407, 3408, 3410, 3411, 3412, 3413, 3414, 3415, 3416, 3417, 3418, 3419]
new = [x for x in feeds if x['feedId'] in target_ids]
assert len(new) == 12, len(new)
ids = [x['feedId'] for x in feeds]
assert ids == sorted(ids), 'not sorted'
for x in new:
    assert x['state'] == 'COMING_SOON'
    assert x['minChannel'] == {'rate': '0.200000000s'}
    assert x['minPublishers'] == 3
    assert x['marketSchedules'][0]['allowedPublisherIds'] == [59, 71, 24, 29, 65, 22, 19, 80]
    assert x['metadata']['instrument_type'] == 'spot'
    assert x['metadata']['asset_type'] == 'crypto'
    assert x['symbol'] == 'Crypto.' + x['metadata']['name'][:-3] + '/USD'
echo_feed = next(x for x in feeds if x['feedId'] == 3409)
assert echo_feed['symbol'] == 'Equity.US.ECHO/USD', 'feed 3409 was modified!'
assert echo_feed['state'] == 'COMING_SOON'
print('VERIFIED 12 feeds OK, feed 3409 untouched')
for x in sorted(new, key=lambda f: f['feedId']):
    print(x['feedId'], x['symbol'], x['metadata']['cmc_id'])
"
```

Expected: prints `VERIFIED 12 feeds OK, feed 3409 untouched` followed by 12 lines (one per new feed, ascending by feedId).

- [ ] **Step 3: Confirm the diff is additive only**

Run: `cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking && git diff --stat lazer.json`
Expected: only `lazer.json` changed, with insertions and **0 deletions** (e.g. `1 file changed, NNN insertions(+)`). If any deletions appear, the raw text outside the inserted blocks was disturbed — stop and investigate (do not commit).

- [ ] **Step 4: Spot-check the raw inserted blocks and untouched feed 3409**

Run: `cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking && grep -n '"feedId": 3407,\|"feedId": 3409,\|"feedId": 3419,' lazer.json`
Expected: all three lines found, in ascending order (3407, then 3409, then 3419), each at 6-space indent matching surrounding feeds.

- [ ] **Step 5: No git commit — `lazer.json` is a gitignored local working copy**

`lazer.json` matches the `lazer*.json` pattern in `.gitignore` (confirmed via
`git check-ignore -v lazer.json` and `git add -n lazer.json`, which errors
with "The following paths are ignored by one of your .gitignore files").
Like `after.json`, it's a local config working copy that is never committed
to git — do **not** run `git add -f` to force it in. The task's deliverable
is the modified file on disk, verified by Steps 2–4 above. Confirm the
working tree state with:

```bash
cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking
git status --short lazer.json
```

Expected: no output (the file is ignored, so it never shows as a pending
change) — this is expected and correct, not a sign the write failed. The
`--write` run's own printed report (`WROTE lazer.json`) plus the independent
verification in Step 2 are the record that the change happened.

---

## Self-Review

**Spec coverage:** every spec field-override and verbatim-copy rule is enforced by asserts in Task 1 (build + re-parse) and re-checked independently in Task 2 Step 2. Pre-flight ID-collision check, valid-JSON re-parse, +12 count, sorted-order, feed-3409-untouched check, and additive-diff check are all present. The description-verbatim rule is satisfied by `build_feed` copying `row["description"].strip()` directly with no xStock-style reformatting.

**Placeholder scan:** no TBD/TODO; all code is complete and runnable.

**Type consistency:** `build_feed`/`feed_to_block`/`main` names, the `REMAP` dict, and the `--write` flag are consistent across both tasks; the `CLOSE` splice constant and `marker_a`/`marker_b` are used exactly as defined; `TAKEN_ID` (3409) and the two predecessor constants match the spec's two-insertion-point design.
