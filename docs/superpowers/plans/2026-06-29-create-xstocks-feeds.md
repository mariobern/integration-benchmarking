# Create xStocks Feeds 3375–3408 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 34 new xStocks spot `/USD` price feeds (feed IDs 3375–3408) to `lazer_new.json`, modeled verbatim on existing feed 3329, with per-feed data from `xstocks.csv`, all in `COMING_SOON` state.

**Architecture:** A one-off Python generator script (lives in the scratchpad, not committed) deep-copies feed 3329's dict as a template, applies per-feed overrides from `xstocks.csv`, serializes each new feed to text matching the file's 4-space feed-object indentation, and splices the 34 blocks into the raw `lazer_new.json` text immediately after feed 3374's closing brace. Raw-text insertion keeps the other 5 MB byte-for-byte unchanged. The only committed artifact is the modified `lazer_new.json`.

**Tech Stack:** Python 3 stdlib only (`json`, `csv`, `copy`). Run with `python3` (no `python` on this system).

## Global Constraints

- Template = feed **3329** (`Crypto.SPCXX/USD`), the spot `/USD` block. Every field not explicitly overridden is copied verbatim.
- New feeds: `state` = `"COMING_SOON"`, `minChannel.rate` = `"0.200000000s"`.
- Copied verbatim from 3329: `allowedPublisherIds` `[59, 71, 24, 29, 65, 22, 19, 80]`, `minPublishers` 3, `expiryTime`, `exponent` -8, `isEnabledInShard`, `kind`, full `marketSchedules`, `metadata.asset_type` (crypto), `metadata.instrument_type` (spot), `metadata.quote_currency` (USD).
- Per-feed overrides: `feedId` (CSV `feed_id`), `symbol` = `Crypto.{TICKER}/USD`, `metadata.name` = `{TICKER}USD`, `metadata.description` = trimmed CSV `description`, `metadata.cmc_id.uintValue` = CSV `cmc_id` as a string. TICKER = CSV `name` (already includes trailing `X`, e.g. `ADBEX`).
- Spot-only: no `.RR` feeds. No changes to existing feeds. Feeds stay sorted ascending by `feedId` (insert after 3374).
- Scratchpad dir (for the script): `/private/tmp/claude-501/-Users-mariobernardi-Documents-GitHub-integration-benchmarking/b7785796-ee00-422e-9c2c-964a4012abba/scratchpad`
- Working dir: `/Users/mariobernardi/Documents/GitHub/integration-benchmarking`

---

### Task 1: Generator script + dry-run validation

Build the script and validate everything it would produce **without writing** to `lazer_new.json`. The dry run is the test: it proves the 34 blocks parse, have correct fields, and splice cleanly.

**Files:**

- Create: `<scratchpad>/create_xstocks_feeds.py` (not committed)
- Read-only inputs: `lazer_new.json`, `xstocks.csv`

**Interfaces:**

- Consumes: nothing (first task).
- Produces: a script invoked as `python3 <scratchpad>/create_xstocks_feeds.py [--write]`. Default (no flag) = dry run: prints a validation report and exits non-zero on any failure. `--write` performs the in-place splice. Both modes build the same `new_feeds` list and `blocks_text`.

- [ ] **Step 1: Write the script**

Create `<scratchpad>/create_xstocks_feeds.py` (substitute the absolute scratchpad path from Global Constraints):

```python
#!/usr/bin/env python3
"""One-off: add xStocks spot feeds 3375-3408 to lazer_new.json (modeled on 3329)."""
import sys
import csv
import json
import copy

REPO = "/Users/mariobernardi/Documents/GitHub/integration-benchmarking"
CONFIG = f"{REPO}/lazer_new.json"
CSV_PATH = f"{REPO}/xstocks.csv"
TEMPLATE_ID = 3329
ID_LO, ID_HI = 3375, 3408
PREDECESSOR_ID = 3374  # insert immediately after this feed's block

CLOSE = "\n    },\n"  # a top-level feed object's closing brace (4-space indent)


def build_feed(template, row):
    """Deep-copy the 3329 template and apply per-feed overrides from a CSV row."""
    feed_id = int(row["feed_id"])
    ticker = row["name"].strip()
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
    existing_ids = {f["feedId"] for f in feeds}

    # Pre-flight: no target ID already exists.
    clashes = sorted(i for i in existing_ids if ID_LO <= i <= ID_HI)
    assert not clashes, f"target IDs already present: {clashes}"

    with open(CSV_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows = [r for r in rows if r.get("feed_id", "").strip()]

    new_feeds = [build_feed(template, r) for r in rows]

    # Structural checks on the generated feeds.
    got_ids = [f["feedId"] for f in new_feeds]
    assert got_ids == list(range(ID_LO, ID_HI + 1)), f"unexpected IDs: {got_ids}"
    for f in new_feeds:
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

    blocks_text = "".join(feed_to_block(f) for f in new_feeds)

    # Locate splice point: end of predecessor (3374) feed block.
    marker = f'"feedId": {PREDECESSOR_ID},'
    i = text.index(marker)
    close = text.index(CLOSE, i) + len(CLOSE)
    new_text = text[:close] + blocks_text + text[close:]

    # Whole-file must still be valid JSON and have exactly +34 feeds.
    reparsed = json.loads(new_text)
    assert len(reparsed["feeds"]) == len(feeds) + 34
    new_in_file = [x for x in reparsed["feeds"] if ID_LO <= x["feedId"] <= ID_HI]
    assert len(new_in_file) == 34
    # still sorted ascending
    ids_after = [x["feedId"] for x in reparsed["feeds"]]
    assert ids_after == sorted(ids_after), "feeds no longer sorted by feedId"

    print(f"OK: {len(new_feeds)} feeds built, {ID_LO}-{ID_HI}")
    for f in (new_feeds[0], new_feeds[-1]):
        print(f"  {f['feedId']} {f['symbol']} name={f['metadata']['name']} "
              f"cmc={f['metadata']['cmc_id']['uintValue']} state={f['state']}")

    if write:
        with open(CONFIG, "w") as fh:
            fh.write(new_text)
        print("WROTE lazer_new.json")
    else:
        print("DRY RUN (no file written). Re-run with --write to apply.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the dry run to verify it passes**

Run: `python3 <scratchpad>/create_xstocks_feeds.py`
Expected: exits 0, prints `OK: 34 feeds built, 3375-3408`, the first/last feed summaries (`3375 Crypto.ADBEX/USD name=ADBEXUSD cmc=40076 state=COMING_SOON` and `3408 Crypto.XLEX/USD name=XLEXUSD cmc=40080 state=COMING_SOON`), and `DRY RUN (no file written).` If any `assert` fires, fix the script and re-run before proceeding.

- [ ] **Step 3: Confirm the file is untouched**

Run: `cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking && git status --short lazer_new.json`
Expected: no output (dry run wrote nothing).

---

### Task 2: Apply the splice and commit

Run the generator in write mode, verify the modified file, and commit.

**Files:**

- Modify: `lazer_new.json` (adds 34 feed blocks after feed 3374)

**Interfaces:**

- Consumes: `create_xstocks_feeds.py` from Task 1.
- Produces: committed `lazer_new.json` with feeds 3375–3408.

- [ ] **Step 1: Run in write mode**

Run: `python3 <scratchpad>/create_xstocks_feeds.py --write`
Expected: exits 0, prints the same `OK:` report plus `WROTE lazer_new.json`. (All in-script asserts run before the write, so a write means every check passed.)

- [ ] **Step 2: Independently verify the modified file**

Run:

```bash
cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking
python3 -c "
import json
d=json.load(open('lazer_new.json'))
f=d['feeds']
new=[x for x in f if 3375<=x['feedId']<=3408]
assert len(new)==34, len(new)
ids=[x['feedId'] for x in f]
assert ids==sorted(ids), 'not sorted'
for x in new:
    assert x['state']=='COMING_SOON'
    assert x['minChannel']=={'rate':'0.200000000s'}
    assert x['minPublishers']==3
    assert x['marketSchedules'][0]['allowedPublisherIds']==[59,71,24,29,65,22,19,80]
    assert x['metadata']['instrument_type']=='spot'
    assert x['symbol']=='Crypto.'+x['metadata']['name'][:-3]+'/USD'
print('VERIFIED 34 feeds 3375-3408 OK')
print(new[0]['symbol'], new[0]['metadata']['cmc_id'], '...', new[-1]['symbol'], new[-1]['metadata']['cmc_id'])
"
```

Expected: prints `VERIFIED 34 feeds 3375-3408 OK` and the first/last symbol+cmc line.

- [ ] **Step 3: Confirm the diff is additive only**

Run: `cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking && git diff --stat lazer_new.json`
Expected: only `lazer_new.json` changed, with insertions and **0 deletions** (e.g. `1 file changed, NNN insertions(+)`). If any deletions appear, the raw text outside the inserted block was disturbed — stop and investigate (do not commit).

- [ ] **Step 4: Spot-check the raw inserted block**

Run: `cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking && grep -n '"feedId": 3375,\|"feedId": 3408,' lazer_new.json`
Expected: both lines found, 3375 before 3408, each at 6-space indent matching surrounding feeds.

- [ ] **Step 5: Commit**

```bash
cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking
git add lazer_new.json
git commit -m "feat(lazer): add xStocks COMING_SOON feeds 3375-3408

Add 34 spot /USD xStocks feeds modeled on feed 3329 (Crypto.SPCXX/USD),
with per-feed data from xstocks.csv. All COMING_SOON, minChannel rate
0.200000000s, publisher list and minPublishers copied from 3329.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(`lazer_new.json` is data, not covered by the black/prettier hooks; no pre-commit run needed for this file.)

---

## Self-Review

**Spec coverage:** every spec field-override and verbatim-copy rule is enforced by asserts in Task 1 (build + re-parse) and re-checked independently in Task 2 Step 2. Pre-flight ID-collision check, valid-JSON re-parse, +34 count, sorted-order, and additive-diff check are all present. Spot-only / no-existing-feed-changes enforced by additive-diff (0 deletions) check.

**Placeholder scan:** no TBD/TODO; all code is complete and runnable.

**Type consistency:** `build_feed`/`feed_to_block`/`main` names and the `--write` flag are consistent across both tasks; the `CLOSE` splice constant and `marker` are used exactly as defined.
