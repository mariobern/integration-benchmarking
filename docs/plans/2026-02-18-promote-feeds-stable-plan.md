# Promote Ready Feeds to Stable - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Promote 98 benchmark-ready US equity tickers from COMING_SOON to STABLE in after.json, setting per-ticker allowedPublisherIds and minPublishers=2.

**Architecture:** Single Python script that parses the markdown summary for ticker/publisher mappings, then performs surgical regex replacements on after.json to modify only the 3 target fields per feed while preserving the exact protobuf-JSON formatting.

**Tech Stack:** Python 3 (stdlib only: json, re, argparse, shutil, sys)

---

### Task 1: Write the markdown parser + test

**Files:**
- Create: `update_lazer_symbols.py`
- Create: `tests/test_update_lazer_symbols.py`

**Step 1: Write the failing test for markdown parsing**

```python
# tests/test_update_lazer_symbols.py
import pytest

SAMPLE_MD = """
## Full Symbol List

"Consistent Publishers" = passed the feed on **every** day.

| # | Ticker | Consistent Publishers | Count | Additional (some days) |
|---|--------|----------------------|-------|------------------------|
| 1 | **AIQ** | 19, 21, 22, 65, 71 | 5 | 12, 26, 35, 44 |
| 2 | **APP** | 22, 42, 65, 69, 71 | 5 | 12, 13, 19, 20 |
| 3 | **KIM** | 69 | 1 | 12, 13, 19, 22 |
"""

def test_parse_summary_extracts_tickers():
    from update_lazer_symbols import parse_summary_markdown
    result = parse_summary_markdown(SAMPLE_MD)
    assert len(result) == 3
    assert result["AIQ"] == [19, 21, 22, 65, 71]
    assert result["APP"] == [22, 42, 65, 69, 71]
    assert result["KIM"] == [69]

def test_parse_summary_from_file(tmp_path):
    from update_lazer_symbols import parse_summary_markdown
    md_file = tmp_path / "summary.md"
    md_file.write_text(SAMPLE_MD)
    result = parse_summary_markdown(md_file.read_text())
    assert "AIQ" in result
    assert "APP" in result

def test_parse_summary_empty_publishers():
    from update_lazer_symbols import parse_summary_markdown
    md = """
| # | Ticker | Consistent Publishers | Count | Additional |
|---|--------|----------------------|-------|------------|
| 1 | **FOO** |  | 0 | 12, 13 |
"""
    result = parse_summary_markdown(md)
    assert result["FOO"] == []
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_update_lazer_symbols.py -v -k "test_parse"`
Expected: FAIL with "ModuleNotFoundError" or "ImportError"

**Step 3: Write the markdown parser**

```python
# update_lazer_symbols.py (beginning of file)
"""
Promote ready feeds from COMING_SOON to STABLE in after.json.

Reads a markdown summary to get per-ticker publisher lists, then
surgically modifies the target JSON config.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def parse_summary_markdown(text: str) -> dict[str, list[int]]:
    """Parse the ticker/publisher table from the summary markdown.

    Returns dict mapping ticker -> sorted list of consistent publisher IDs.
    """
    result = {}
    # Match rows like: | 1 | **AIQ** | 19, 21, 22, 65, 71 | 5 | ... |
    pattern = re.compile(
        r'\|\s*\d+\s*\|\s*\*\*(\w+)\*\*\s*\|\s*([^|]*)\|\s*\d+\s*\|'
    )
    for match in pattern.finditer(text):
        ticker = match.group(1)
        pubs_str = match.group(2).strip()
        if pubs_str:
            pubs = sorted(int(p.strip()) for p in pubs_str.split(',') if p.strip())
        else:
            pubs = []
        result[ticker] = pubs
    return result
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_update_lazer_symbols.py -v -k "test_parse"`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add update_lazer_symbols.py tests/test_update_lazer_symbols.py
git commit -m "feat: add markdown parser for feed promotion script"
```

---

### Task 2: Write the JSON modifier + test

**Files:**
- Modify: `update_lazer_symbols.py`
- Modify: `tests/test_update_lazer_symbols.py`

**Step 1: Write the failing test for JSON modification**

Add to `tests/test_update_lazer_symbols.py`:

```python
SAMPLE_CONFIG = {
    "featureFlags": ["enable_ema"],
    "feeds": [
        {
            "allowedPublisherIds": [1, 2, 3],
            "feedId": 100,
            "metadata": {"name": "AIQ"},
            "minPublishers": 3,
            "state": "COMING_SOON",
            "symbol": "Equity.US.AIQ/USD"
        },
        {
            "allowedPublisherIds": [1, 2],
            "feedId": 200,
            "metadata": {"name": "STABLE_TICKER"},
            "minPublishers": 1,
            "state": "STABLE",
            "symbol": "Equity.US.STABLE_TICKER/USD"
        },
        {
            "allowedPublisherIds": [1, 2, 3, 4],
            "feedId": 300,
            "metadata": {"name": "APP"},
            "minPublishers": 3,
            "state": "COMING_SOON",
            "symbol": "Equity.US.APP/USD"
        }
    ],
    "shardId": 1
}

def test_modify_config_changes_target_feeds(tmp_path):
    from update_lazer_symbols import modify_config
    config_file = tmp_path / "after.json"
    # Write in protobuf-like format (compact arrays)
    raw = json.dumps(SAMPLE_CONFIG, indent=2)
    config_file.write_text(raw)

    ticker_pubs = {
        "AIQ": [19, 21, 22, 65, 71],
        "APP": [22, 42, 65, 69, 71],
    }
    result = modify_config(str(config_file), ticker_pubs, dry_run=False)

    # Verify changes
    with open(config_file) as f:
        data = json.load(f)

    aiq = [f for f in data["feeds"] if f["metadata"]["name"] == "AIQ"][0]
    assert aiq["state"] == "STABLE"
    assert aiq["allowedPublisherIds"] == [19, 21, 22, 65, 71]
    assert aiq["minPublishers"] == 2

    app = [f for f in data["feeds"] if f["metadata"]["name"] == "APP"][0]
    assert app["state"] == "STABLE"
    assert app["allowedPublisherIds"] == [22, 42, 65, 69, 71]
    assert app["minPublishers"] == 2

    assert result["modified"] == 2
    assert result["skipped_not_coming_soon"] == 0

def test_modify_config_skips_already_stable(tmp_path):
    from update_lazer_symbols import modify_config
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

    ticker_pubs = {"STABLE_TICKER": [10, 20]}
    result = modify_config(str(config_file), ticker_pubs, dry_run=False)

    with open(config_file) as f:
        data = json.load(f)
    stable = [f for f in data["feeds"] if f["metadata"]["name"] == "STABLE_TICKER"][0]
    assert stable["state"] == "STABLE"
    assert stable["allowedPublisherIds"] == [1, 2]  # unchanged
    assert result["modified"] == 0
    assert result["skipped_not_coming_soon"] == 1

def test_modify_config_dry_run_no_write(tmp_path):
    from update_lazer_symbols import modify_config
    config_file = tmp_path / "after.json"
    original = json.dumps(SAMPLE_CONFIG, indent=2)
    config_file.write_text(original)

    ticker_pubs = {"AIQ": [19, 22]}
    modify_config(str(config_file), ticker_pubs, dry_run=True)

    assert config_file.read_text() == original  # unchanged

def test_modify_config_creates_backup(tmp_path):
    from update_lazer_symbols import modify_config
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

    ticker_pubs = {"AIQ": [19, 22]}
    modify_config(str(config_file), ticker_pubs, dry_run=False)

    backup = tmp_path / "after.json.bak"
    assert backup.exists()

def test_modify_config_warns_missing_ticker(tmp_path):
    from update_lazer_symbols import modify_config
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

    ticker_pubs = {"NONEXISTENT": [19, 22]}
    result = modify_config(str(config_file), ticker_pubs, dry_run=False)
    assert result["not_found"] == ["NONEXISTENT"]
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_update_lazer_symbols.py -v -k "test_modify"`
Expected: FAIL with "ImportError: cannot import name 'modify_config'"

**Step 3: Write the JSON modifier using surgical regex**

Add to `update_lazer_symbols.py`:

```python
def _find_feed_block(raw: str, feed_id: int) -> tuple[int, int] | None:
    """Find the start/end positions of a feed entry by feedId in the raw JSON text."""
    pattern = rf'"feedId": {feed_id},'
    match = re.search(pattern, raw)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening { (string-aware)
    depth = 0
    start = pos - 1
    while start > 0:
        c = raw[start]
        if c == '"':
            start -= 1
            while start > 0 and raw[start] != '"':
                if start > 0 and raw[start - 1] == '\\':
                    start -= 1
                start -= 1
        elif c == '}':
            depth += 1
        elif c == '{':
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward from opening { for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(raw) and depth > 0:
        c = raw[end]
        if c == '"' and (end == 0 or raw[end - 1] != '\\'):
            in_string = not in_string
        elif not in_string:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
        end += 1

    return (start, end)


def modify_config(
    config_path: str,
    ticker_pubs: dict[str, list[int]],
    dry_run: bool = False,
) -> dict:
    """Modify after.json: promote COMING_SOON feeds to STABLE.

    Uses surgical regex replacements to preserve the original formatting.
    Returns summary dict with counts of modified/skipped/not_found.
    """
    with open(config_path) as f:
        raw = f.read()

    data = json.loads(raw)
    feeds = data["feeds"]

    # Build name -> feedId + state mapping
    feed_lookup: dict[str, dict] = {}
    for feed in feeds:
        name = feed.get("metadata", {}).get("name", "")
        if name:
            feed_lookup[name] = {
                "feedId": feed["feedId"],
                "state": feed["state"],
            }

    modified = 0
    skipped_not_coming_soon = 0
    not_found = []

    for ticker, pubs in ticker_pubs.items():
        if ticker not in feed_lookup:
            not_found.append(ticker)
            print(f"  WARNING: {ticker} not found in config")
            continue

        info = feed_lookup[ticker]
        if info["state"] != "COMING_SOON":
            skipped_not_coming_soon += 1
            print(f"  SKIP: {ticker} (state={info['state']}, not COMING_SOON)")
            continue

        bounds = _find_feed_block(raw, info["feedId"])
        if not bounds:
            not_found.append(ticker)
            print(f"  WARNING: {ticker} feedId={info['feedId']} block not found in raw text")
            continue

        start, end = bounds
        block = raw[start:end]

        # Surgical replacements
        new_block = re.sub(
            r'"state": "COMING_SOON"', '"state": "STABLE"', block
        )
        pub_str = "[ " + ", ".join(str(p) for p in sorted(pubs)) + " ]"
        new_block = re.sub(
            r'"allowedPublisherIds": \[[^\]]*\]',
            f'"allowedPublisherIds": {pub_str}',
            new_block,
        )
        new_block = re.sub(
            r'"minPublishers": \d+', '"minPublishers": 2', new_block
        )

        raw = raw[:start] + new_block + raw[end:]
        modified += 1
        print(f"  OK: {ticker} (feedId={info['feedId']}) -> STABLE, pubs={sorted(pubs)}, minPub=2")

    if not dry_run and modified > 0:
        # Create backup
        backup_path = config_path + ".bak"
        shutil.copy2(config_path, backup_path)
        with open(config_path, "w") as f:
            f.write(raw)
        print(f"\nBackup saved to {backup_path}")

    result = {
        "modified": modified,
        "skipped_not_coming_soon": skipped_not_coming_soon,
        "not_found": not_found,
    }
    return result
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_update_lazer_symbols.py -v -k "test_modify"`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add update_lazer_symbols.py tests/test_update_lazer_symbols.py
git commit -m "feat: add surgical JSON modifier for feed promotion"
```

---

### Task 3: Write the CLI + integration test

**Files:**
- Modify: `update_lazer_symbols.py`
- Modify: `tests/test_update_lazer_symbols.py`

**Step 1: Write the failing integration test**

Add to `tests/test_update_lazer_symbols.py`:

```python
import subprocess

def test_cli_dry_run(tmp_path):
    """Integration test: full CLI pipeline in dry-run mode."""
    md_file = tmp_path / "summary.md"
    md_file.write_text(SAMPLE_MD)
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

    result = subprocess.run(
        [
            sys.executable, "update_lazer_symbols.py",
            "--summary", str(md_file),
            "--config", str(config_file),
            "--dry-run",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    # File should be unchanged
    with open(config_file) as f:
        data = json.load(f)
    aiq = [f for f in data["feeds"] if f["metadata"]["name"] == "AIQ"][0]
    assert aiq["state"] == "COMING_SOON"

def test_cli_real_run(tmp_path):
    """Integration test: full CLI pipeline modifying the file."""
    md_file = tmp_path / "summary.md"
    md_file.write_text(SAMPLE_MD)
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

    result = subprocess.run(
        [
            sys.executable, "update_lazer_symbols.py",
            "--summary", str(md_file),
            "--config", str(config_file),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    with open(config_file) as f:
        data = json.load(f)
    aiq = [f for f in data["feeds"] if f["metadata"]["name"] == "AIQ"][0]
    assert aiq["state"] == "STABLE"
    assert aiq["minPublishers"] == 2
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_update_lazer_symbols.py -v -k "test_cli"`
Expected: FAIL (no CLI entry point yet)

**Step 3: Write the CLI**

Add to `update_lazer_symbols.py`:

```python
def main():
    parser = argparse.ArgumentParser(
        description="Promote ready feeds from COMING_SOON to STABLE in after.json"
    )
    parser.add_argument(
        "--summary", required=True,
        help="Path to feeds_ready summary markdown file"
    )
    parser.add_argument(
        "--config", required=True,
        help="Path to after.json config file"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print changes without writing to file"
    )
    args = parser.parse_args()

    # Parse markdown summary
    summary_path = Path(args.summary)
    if not summary_path.exists():
        print(f"ERROR: Summary file not found: {summary_path}")
        sys.exit(1)
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)

    print(f"Reading summary from {summary_path}")
    ticker_pubs = parse_summary_markdown(summary_path.read_text())
    print(f"Found {len(ticker_pubs)} tickers with publisher mappings")

    if args.dry_run:
        print("\n=== DRY RUN (no files will be modified) ===\n")
    else:
        print()

    result = modify_config(str(config_path), ticker_pubs, dry_run=args.dry_run)

    # Print summary
    print(f"\n{'='*50}")
    print(f"SUMMARY")
    print(f"{'='*50}")
    print(f"  Modified:             {result['modified']}")
    print(f"  Skipped (not coming_soon): {result['skipped_not_coming_soon']}")
    print(f"  Not found in config:  {len(result['not_found'])}")
    if result["not_found"]:
        print(f"  Missing tickers: {', '.join(result['not_found'])}")
    total = result["modified"] + result["skipped_not_coming_soon"] + len(result["not_found"])
    print(f"  Total processed:      {total}/{len(ticker_pubs)}")


if __name__ == "__main__":
    main()
```

**Step 4: Run all tests to verify they pass**

Run: `python3 -m pytest tests/test_update_lazer_symbols.py -v`
Expected: ALL PASSED (8 tests)

**Step 5: Commit**

```bash
git add update_lazer_symbols.py tests/test_update_lazer_symbols.py
git commit -m "feat: add CLI for feed promotion script"
```

---

### Task 4: Run against real data and verify

**Step 1: Dry run against real files**

```bash
python3 update_lazer_symbols.py \
  --summary feeds_ready_170226_summary.md \
  --config after.json \
  --dry-run
```

Expected output:
- 95 tickers modified (COMING_SOON -> STABLE)
- 3 tickers skipped (AIQ, APP, SHLD already STABLE)
- 0 not found

**Step 2: Verify dry run output looks correct**

Manually check that:
- Each ticker shows the correct publisher IDs from the markdown
- The 3 already-stable tickers are skipped
- No warnings or errors

**Step 3: Run for real**

```bash
python3 update_lazer_symbols.py \
  --summary feeds_ready_170226_summary.md \
  --config after.json
```

**Step 4: Verify the changes**

```bash
python3 -c "
import json
with open('after.json') as f:
    data = json.load(f)
feeds = data['feeds']
# Spot-check a few tickers
for name in ['AWK', 'VOO', 'MARA', 'KIM']:
    feed = [f for f in feeds if f.get('metadata',{}).get('name') == name][0]
    print(f\"{name}: state={feed['state']}, minPub={feed['minPublishers']}, pubs={feed['allowedPublisherIds']}\")
# Count states
states = {}
for f in feeds:
    states[f['state']] = states.get(f['state'], 0) + 1
print(f'States: {states}')
"
```

Expected:
- AWK: state=STABLE, minPub=2, pubs=[12, 19, 22, 42, 55, 65, 69, 71]
- VOO: state=STABLE, minPub=2, pubs=[13, 19, 20, 21, 22, 28, 29, 42, 52, 54, 55, 64, 65, 69, 71]
- MARA: state=STABLE, minPub=2, pubs=[22, 28, 65, 69]
- KIM: state=STABLE, minPub=2, pubs=[69]
- States should show ~771 STABLE (was 676 + 95 promoted)

**Step 5: Commit**

```bash
git add after.json
git commit -m "feat: promote 95 ready US equity feeds to STABLE with publisher allowlists"
```
