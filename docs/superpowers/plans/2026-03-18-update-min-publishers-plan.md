# update_min_publishers Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone script that enforces minimum `minPublishers` values in after.json based on publisher count, reducing single-publisher price bias risk.

**Architecture:** Two-file design: `lib/min_publishers.py` contains all core logic (rule engine, eligibility filters, JSON surgery, CSV reporting), and `update_min_publishers.py` is a thin CLI wrapper. JSON modification uses surgical regex on the raw string (same pattern as `update_lazer_symbols.py` and `update_config_from_summary.py`).

**Tech Stack:** Python 3, argparse, json, re, csv, shutil, pytest

**Spec:** `docs/superpowers/specs/2026-03-18-update-min-publishers-design.md`

---

## File Structure

| File | Purpose |
|------|---------|
| `lib/min_publishers.py` | Core logic: rule engine, eligibility, JSON surgery, CSV report |
| `update_min_publishers.py` | CLI wrapper: argparse, delegates to `lib/min_publishers.py` |
| `tests/test_min_publishers.py` | All unit tests |

---

## Chunk 1: Core Rule Engine + Eligibility

### Task 1: Rule Engine — compute_target_min_publishers

**Files:**
- Create: `lib/min_publishers.py`
- Create: `tests/test_min_publishers.py`

- [ ] **Step 1: Write failing tests for the rule engine**

```python
# tests/test_min_publishers.py
import pytest

from lib.min_publishers import compute_target_min_publishers


class TestComputeTargetMinPublishers:
    """Rule engine: publisher count -> target minPublishers."""

    def test_below_floor_returns_none(self):
        """2-4 publishers -> no change (None)."""
        assert compute_target_min_publishers(2) is None
        assert compute_target_min_publishers(3) is None
        assert compute_target_min_publishers(4) is None

    def test_needs_attention_returns_none(self):
        """0-1 publishers -> no change (None). NEEDS_ATTENTION handled elsewhere."""
        assert compute_target_min_publishers(0) is None
        assert compute_target_min_publishers(1) is None

    def test_mid_tier_returns_2(self):
        """5-6 publishers -> minPublishers=2."""
        assert compute_target_min_publishers(5) == 2
        assert compute_target_min_publishers(6) == 2

    def test_upper_tier_returns_3(self):
        """7+ publishers -> minPublishers=3."""
        assert compute_target_min_publishers(7) == 3
        assert compute_target_min_publishers(10) == 3
        assert compute_target_min_publishers(20) == 3

    def test_custom_floor(self):
        """--min-publisher-floor changes lower boundary."""
        assert compute_target_min_publishers(3, floor=3) == 2
        assert compute_target_min_publishers(2, floor=3) is None

    def test_custom_cutoff(self):
        """--publisher-tier-cutoff changes upper boundary."""
        assert compute_target_min_publishers(5, cutoff=5) == 3
        assert compute_target_min_publishers(4, cutoff=5) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'lib.min_publishers'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/min_publishers.py
"""
Enforce minimum minPublishers values in after.json based on publisher count.

Rule engine:
  0-1 publishers  -> NEEDS_ATTENTION (no change)
  2-4 publishers  -> no change (below floor)
  5-6 publishers  -> minPublishers = 2
  7+  publishers  -> minPublishers = 3

Boundaries configurable via floor and cutoff parameters.
"""

# Default exclusion list: non-benchmarkable asset types
DEFAULT_EXCLUDED_ASSET_TYPES = frozenset(
    {
        "funding-rate",
        "crypto-redemption-rate",
        "nav",
        "custom",
        "crypto-index",
        "kalshi",
    }
)

# Extended session names that indicate extended-hours equities
_EXTENDED_SESSIONS = frozenset({"PRE_MARKET", "POST_MARKET", "OVER_NIGHT"})

# Default thresholds
DEFAULT_FLOOR = 5
DEFAULT_CUTOFF = 7


def compute_target_min_publishers(
    publisher_count: int,
    floor: int = DEFAULT_FLOOR,
    cutoff: int = DEFAULT_CUTOFF,
) -> int | None:
    """Compute target minPublishers based on publisher count.

    Returns target value, or None if no change should be made
    (publisher count below floor or needs attention).
    """
    if publisher_count < floor:
        return None
    if publisher_count < cutoff:
        return 2
    return 3
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestComputeTargetMinPublishers -v
```

Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/min_publishers.py tests/test_min_publishers.py
git commit -m "feat: add min_publishers rule engine with tests"
```

---

### Task 2: Eligibility Filters — evaluate_feeds

**Files:**
- Modify: `lib/min_publishers.py`
- Modify: `tests/test_min_publishers.py`

- [ ] **Step 1: Write failing tests for eligibility and feed evaluation**

```python
# Append to tests/test_min_publishers.py
import json

from lib.min_publishers import evaluate_feeds, FeedChange


# Minimal feed fixtures
def _make_feed(
    feed_id,
    symbol,
    asset_type,
    state,
    min_publishers,
    publisher_ids,
    sessions=None,
):
    """Build a minimal feed dict matching after.json structure."""
    feed = {
        "feedId": feed_id,
        "symbol": symbol,
        "state": state,
        "minPublishers": min_publishers,
        "allowedPublisherIds": publisher_ids,
        "metadata": {"asset_type": asset_type, "name": symbol.split(".")[-1].split("/")[0]},
        "marketSchedules": sessions
        or [{"marketSchedule": "America/New_York;O,O,O,O,O,O,O;", "session": "REGULAR"}],
    }
    return feed


def _make_extended_equity(feed_id, symbol, top_min_pub, top_pubs, regular_min_pub, regular_pubs):
    """Build an extended-hours equity feed with REGULAR + OVER_NIGHT sessions."""
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": "STABLE",
        "minPublishers": top_min_pub,
        "allowedPublisherIds": top_pubs,
        "metadata": {"asset_type": "equity", "name": symbol.split(".")[-1].split("/")[0]},
        "marketSchedules": [
            {
                "allowedPublisherIds": regular_pubs,
                "marketSchedule": "America/New_York;0930-1600,...",
                "minPublishers": regular_min_pub,
                "session": "REGULAR",
            },
            {
                "allowedPublisherIds": [32, 41],
                "marketSchedule": "America/New_York;0000-0400&2000-2400,...",
                "minPublishers": 1,
                "session": "OVER_NIGHT",
            },
        ],
    }


class TestEvaluateFeeds:
    """Feed eligibility and change computation."""

    def test_stable_equity_updated(self):
        """STABLE equity with 5 publishers and minPublishers=1 -> UPDATED to 2."""
        feeds = [_make_feed(100, "Equity.US.FOO/USD", "equity", "STABLE", 1, [10, 20, 30, 40, 50])]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 1
        assert changes[0].status == "UPDATED"
        assert changes[0].new_min_publishers == 2

    def test_stable_equity_7_publishers_updated_to_3(self):
        """STABLE equity with 7+ publishers -> UPDATED to 3."""
        feeds = [_make_feed(100, "Equity.US.FOO/USD", "equity", "STABLE", 1, list(range(10, 18)))]
        changes = evaluate_feeds(feeds)
        assert changes[0].new_min_publishers == 3

    def test_coming_soon_skipped(self):
        """COMING_SOON feeds are not processed."""
        feeds = [_make_feed(100, "Equity.US.FOO/USD", "equity", "COMING_SOON", 1, [10, 20, 30, 40, 50])]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 0

    def test_excluded_asset_type_skipped(self):
        """Feeds with excluded asset types are not processed."""
        feeds = [_make_feed(100, "FundingRate.X/Y", "funding-rate", "STABLE", 1, [10, 20, 30, 40, 50])]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 0

    def test_asset_class_allowlist(self):
        """--asset-classes overrides default exclusion."""
        feeds = [
            _make_feed(100, "FX.EUR/USD", "fx", "STABLE", 1, [10, 20, 30, 40, 50]),
            _make_feed(200, "Crypto.BTC/USD", "crypto", "STABLE", 1, [10, 20, 30, 40, 50]),
        ]
        changes = evaluate_feeds(feeds, asset_classes=["fx"])
        assert len(changes) == 1
        assert changes[0].feed_id == 100

    def test_needs_attention(self):
        """Feeds with <2 publishers get NEEDS_ATTENTION."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 1, [10])]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 1
        assert changes[0].status == "NEEDS_ATTENTION"

    def test_low_publishers_skipped(self):
        """Feeds with 2-4 publishers get SKIPPED_LOW_PUBLISHERS."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 1, [10, 20, 30])]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 1
        assert changes[0].status == "SKIPPED_LOW_PUBLISHERS"

    def test_no_downgrade(self):
        """Existing minPublishers=3 with 5 publishers stays (SKIPPED_HIGHER)."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 3, [10, 20, 30, 40, 50])]
        changes = evaluate_feeds(feeds)
        assert changes[0].status == "SKIPPED_HIGHER"

    def test_skipped_equal(self):
        """Existing minPublishers=2 with 5 publishers (SKIPPED_EQUAL)."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 2, [10, 20, 30, 40, 50])]
        changes = evaluate_feeds(feeds)
        assert changes[0].status == "SKIPPED_EQUAL"

    def test_upgrade_2_to_3(self):
        """Existing minPublishers=2 with 8 publishers -> UPDATED to 3."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 2, list(range(10, 18)))]
        changes = evaluate_feeds(feeds)
        assert changes[0].status == "UPDATED"
        assert changes[0].new_min_publishers == 3

    def test_extended_hours_excluded(self):
        """Extended-hours equities are entirely excluded."""
        feeds = [_make_extended_equity(100, "Equity.US.AAPL/USD", 1, list(range(10, 25)), 3, list(range(10, 22)))]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 0

    def test_empty_allowed_publishers(self):
        """Feed with empty allowedPublisherIds -> NEEDS_ATTENTION."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 1, [])]
        changes = evaluate_feeds(feeds)
        assert changes[0].status == "NEEDS_ATTENTION"

    def test_missing_allowed_publishers_key(self):
        """Feed with no allowedPublisherIds key -> NEEDS_ATTENTION."""
        feed = _make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 1, [])
        del feed["allowedPublisherIds"]
        changes = evaluate_feeds([feed])
        assert changes[0].status == "NEEDS_ATTENTION"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestEvaluateFeeds -v
```

Expected: FAIL — `ImportError: cannot import name 'evaluate_feeds'`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to lib/min_publishers.py
from dataclasses import dataclass


@dataclass
class FeedChange:
    """Represents the evaluation result for a single feed."""

    feed_id: int
    symbol: str
    asset_type: str
    old_min_publishers: int
    new_min_publishers: int | None
    allowed_publisher_count: int
    status: str  # UPDATED, SKIPPED_LOW_PUBLISHERS, SKIPPED_EQUAL, SKIPPED_HIGHER, NEEDS_ATTENTION


def is_extended_hours(feed: dict) -> bool:
    """Check if a feed has extended-hours sessions (PRE_MARKET/POST_MARKET/OVER_NIGHT)."""
    for schedule in feed.get("marketSchedules", []):
        if schedule.get("session") in _EXTENDED_SESSIONS:
            return True
    return False


def evaluate_feeds(
    feeds: list[dict],
    floor: int = DEFAULT_FLOOR,
    cutoff: int = DEFAULT_CUTOFF,
    asset_classes: list[str] | None = None,
    excluded_asset_types: frozenset[str] = DEFAULT_EXCLUDED_ASSET_TYPES,
) -> list[FeedChange]:
    """Evaluate all feeds and return list of FeedChange results.

    Only processes STABLE, non-extended, non-excluded feeds.
    Returns results for feeds that pass eligibility (including skips).
    """
    changes: list[FeedChange] = []

    for feed in feeds:
        # Filter: state
        if feed.get("state") != "STABLE":
            continue

        # Filter: asset type
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        if asset_classes is not None:
            if asset_type not in asset_classes:
                continue
        elif asset_type in excluded_asset_types:
            continue

        # Filter: extended-hours
        if is_extended_hours(feed):
            continue

        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        old_min = feed.get("minPublishers", 0)
        pub_ids = feed.get("allowedPublisherIds", [])
        pub_count = len(pub_ids)

        # NEEDS_ATTENTION: <2 publishers
        if pub_count < 2:
            changes.append(
                FeedChange(
                    feed_id=feed_id,
                    symbol=symbol,
                    asset_type=asset_type,
                    old_min_publishers=old_min,
                    new_min_publishers=None,
                    allowed_publisher_count=pub_count,
                    status="NEEDS_ATTENTION",
                )
            )
            continue

        target = compute_target_min_publishers(pub_count, floor=floor, cutoff=cutoff)

        # Below floor: SKIPPED_LOW_PUBLISHERS
        if target is None:
            changes.append(
                FeedChange(
                    feed_id=feed_id,
                    symbol=symbol,
                    asset_type=asset_type,
                    old_min_publishers=old_min,
                    new_min_publishers=None,
                    allowed_publisher_count=pub_count,
                    status="SKIPPED_LOW_PUBLISHERS",
                )
            )
            continue

        # No-downgrade comparison
        if old_min > target:
            status = "SKIPPED_HIGHER"
            new_min = None
        elif old_min == target:
            status = "SKIPPED_EQUAL"
            new_min = None
        else:
            status = "UPDATED"
            new_min = target

        changes.append(
            FeedChange(
                feed_id=feed_id,
                symbol=symbol,
                asset_type=asset_type,
                old_min_publishers=old_min,
                new_min_publishers=new_min,
                allowed_publisher_count=pub_count,
                status=status,
            )
        )

    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py -v
```

Expected: All tests PASS (6 from Task 1 + 13 from Task 2)

- [ ] **Step 5: Commit**

```bash
git add lib/min_publishers.py tests/test_min_publishers.py
git commit -m "feat: add feed eligibility evaluation with FeedChange dataclass"
```

---

## Chunk 2: JSON Surgery + File Modification

### Task 3: JSON Surgery — _find_feed_block + _find_market_schedules_end

**Files:**
- Modify: `lib/min_publishers.py`
- Modify: `tests/test_min_publishers.py`

The critical challenge: some feeds have `minPublishers` inside `marketSchedules[0]` AND at the top level. The regex must target only the top-level one. Strategy: find where `marketSchedules` ends, then apply regex only to the text after that point.

- [ ] **Step 1: Write failing tests for JSON surgery helpers**

```python
# Append to tests/test_min_publishers.py
from lib.min_publishers import _find_feed_block, _find_market_schedules_end


# Sample JSON for testing (formatted like real after.json)
SAMPLE_CONFIG_RAW = json.dumps(
    {
        "feeds": [
            {
                "allowedPublisherIds": [10, 20, 30, 40, 50],
                "feedId": 100,
                "marketSchedules": [
                    {
                        "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                        "session": "REGULAR",
                    }
                ],
                "metadata": {"asset_type": "equity", "name": "FOO"},
                "minPublishers": 1,
                "state": "STABLE",
                "symbol": "Equity.US.FOO/USD",
            },
            {
                "allowedPublisherIds": [10, 20, 30, 40, 50, 60, 70, 80],
                "feedId": 200,
                "marketSchedules": [
                    {
                        "allowedPublisherIds": [10, 20, 30, 40, 50, 60, 70, 80],
                        "marketSchedule": "America/New_York;0930-1600,...",
                        "minPublishers": 3,
                        "session": "REGULAR",
                    }
                ],
                "metadata": {"asset_type": "equity", "name": "BAR"},
                "minPublishers": 1,
                "state": "STABLE",
                "symbol": "Equity.US.BAR/USD",
            },
        ]
    },
    indent=2,
)


class TestFindFeedBlock:
    """Locate feed blocks in raw JSON."""

    def test_finds_feed_block(self):
        bounds = _find_feed_block(SAMPLE_CONFIG_RAW, 100)
        assert bounds is not None
        block = SAMPLE_CONFIG_RAW[bounds[0] : bounds[1]]
        assert '"feedId": 100' in block
        assert '"symbol": "Equity.US.FOO/USD"' in block

    def test_returns_none_for_missing_feed(self):
        assert _find_feed_block(SAMPLE_CONFIG_RAW, 999) is None

    def test_finds_second_feed(self):
        bounds = _find_feed_block(SAMPLE_CONFIG_RAW, 200)
        assert bounds is not None
        block = SAMPLE_CONFIG_RAW[bounds[0] : bounds[1]]
        assert '"feedId": 200' in block


class TestFindMarketSchedulesEnd:
    """Locate end of marketSchedules array within a feed block."""

    def test_simple_feed(self):
        bounds = _find_feed_block(SAMPLE_CONFIG_RAW, 100)
        block = SAMPLE_CONFIG_RAW[bounds[0] : bounds[1]]
        end_pos = _find_market_schedules_end(block)
        assert end_pos is not None
        # Everything after end_pos should contain top-level minPublishers
        after = block[end_pos:]
        assert '"minPublishers": 1' in after

    def test_dual_structure_feed(self):
        """Feed with minPublishers in both marketSchedules and top-level."""
        bounds = _find_feed_block(SAMPLE_CONFIG_RAW, 200)
        block = SAMPLE_CONFIG_RAW[bounds[0] : bounds[1]]
        end_pos = _find_market_schedules_end(block)
        assert end_pos is not None
        before = block[:end_pos]
        after = block[end_pos:]
        # Session-level minPublishers is BEFORE end_pos
        assert '"minPublishers": 3' in before
        # Top-level minPublishers is AFTER end_pos
        assert '"minPublishers": 1' in after

    def test_no_market_schedules(self):
        """Feed without marketSchedules key."""
        block = '{"feedId": 1, "minPublishers": 1, "state": "STABLE"}'
        assert _find_market_schedules_end(block) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestFindFeedBlock tests/test_min_publishers.py::TestFindMarketSchedulesEnd -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# Add to lib/min_publishers.py
import re


def _find_feed_block(raw: str, feed_id: int) -> tuple[int, int] | None:
    """Find the start/end positions of a feed entry by feedId in the raw JSON.

    Uses the same algorithm as update_config_from_summary.py and
    update_lazer_symbols.py: regex match on feedId, then bracket-depth
    scanning with string-awareness.
    """
    pattern = rf'"feedId":\s*{feed_id}\s*[,\n}}]'
    match = re.search(pattern, raw)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening {
    depth = 0
    start = pos - 1
    while start >= 0:
        c = raw[start]
        if c == '"':
            start -= 1
            while start >= 0 and raw[start] != '"':
                if raw[start] == "\\" and start > 0:
                    start -= 1
                start -= 1
        elif c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(raw) and depth > 0:
        c = raw[end]
        if c == '"' and (end == 0 or raw[end - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        end += 1

    return (start, end)


def _find_market_schedules_end(block: str) -> int | None:
    """Find the position after the closing ] of marketSchedules in a feed block.

    Returns the index immediately after the ']' that closes the
    marketSchedules array, or None if no marketSchedules key exists.
    """
    ms_match = re.search(r'"marketSchedules":\s*\[', block)
    if not ms_match:
        return None

    pos = ms_match.end()
    depth = 1
    in_string = False
    while pos < len(block) and depth > 0:
        c = block[pos]
        if c == '"' and (pos == 0 or block[pos - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
        pos += 1

    return pos  # position right after closing ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestFindFeedBlock tests/test_min_publishers.py::TestFindMarketSchedulesEnd -v
```

Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/min_publishers.py tests/test_min_publishers.py
git commit -m "feat: add JSON surgery helpers for feed block and marketSchedules detection"
```

---

### Task 4: Apply Changes — modify_config

**Files:**
- Modify: `lib/min_publishers.py`
- Modify: `tests/test_min_publishers.py`

- [ ] **Step 1: Write failing tests for modify_config**

```python
# Append to tests/test_min_publishers.py
from lib.min_publishers import modify_config


class TestModifyConfig:
    """End-to-end JSON modification."""

    def test_simple_feed_updated(self, tmp_path):
        """Non-dual feed: top-level minPublishers changed."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))

        result = modify_config(str(config_file), dry_run=False)

        data = json.loads(config_file.read_text())
        assert data["feeds"][0]["minPublishers"] == 2
        assert result["updated"] == 1

    def test_dual_structure_only_top_level_changed(self, tmp_path):
        """Feed with minPublishers in marketSchedules AND top-level:
        only top-level is changed, session-level stays at 3."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": list(range(10, 24)),
                    "feedId": 200,
                    "marketSchedules": [
                        {
                            "allowedPublisherIds": list(range(10, 24)),
                            "marketSchedule": "X",
                            "minPublishers": 3,
                            "session": "REGULAR",
                        }
                    ],
                    "metadata": {"asset_type": "equity", "name": "BAR"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.BAR/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))

        modify_config(str(config_file), dry_run=False)

        raw = config_file.read_text()
        data = json.loads(raw)
        # Top-level should be 3 now
        assert data["feeds"][0]["minPublishers"] == 3
        # Session-level should remain 3
        assert data["feeds"][0]["marketSchedules"][0]["minPublishers"] == 3

    def test_dry_run_no_write(self, tmp_path):
        """Dry run does not modify the file."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        original = json.dumps(config, indent=2)
        config_file.write_text(original)

        modify_config(str(config_file), dry_run=True)

        assert config_file.read_text() == original

    def test_backup_created(self, tmp_path):
        """Backup file is created on write."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))

        modify_config(str(config_file), dry_run=False)

        assert (tmp_path / "after.json.bak").exists()

    def test_idempotency(self, tmp_path):
        """Running twice produces no changes on the second run."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))

        # First run
        modify_config(str(config_file), dry_run=False)
        # Second run
        result = modify_config(str(config_file), dry_run=False)

        assert result["updated"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestModifyConfig -v
```

Expected: FAIL — `ImportError: cannot import name 'modify_config'`

- [ ] **Step 3: Write minimal implementation**

```python
# Add to lib/min_publishers.py
import json
import shutil


def modify_config(
    config_path: str,
    dry_run: bool = False,
    floor: int = DEFAULT_FLOOR,
    cutoff: int = DEFAULT_CUTOFF,
    asset_classes: list[str] | None = None,
    excluded_asset_types: frozenset[str] = DEFAULT_EXCLUDED_ASSET_TYPES,
) -> dict:
    """Evaluate feeds and apply minPublishers changes to config file.

    Returns summary dict with counts.
    """
    with open(config_path) as f:
        raw = f.read()

    data = json.loads(raw)
    feeds = data["feeds"]

    # Evaluate all feeds
    changes = evaluate_feeds(
        feeds,
        floor=floor,
        cutoff=cutoff,
        asset_classes=asset_classes,
        excluded_asset_types=excluded_asset_types,
    )

    # Apply UPDATED changes to raw JSON
    updates_to_apply = [c for c in changes if c.status == "UPDATED"]

    for change in updates_to_apply:
        bounds = _find_feed_block(raw, change.feed_id)
        if not bounds:
            continue

        start, end = bounds
        block = raw[start:end]

        # Find where marketSchedules ends to target top-level minPublishers
        ms_end = _find_market_schedules_end(block)
        if ms_end is not None:
            # Only apply regex to text after marketSchedules
            before = block[:ms_end]
            after = block[ms_end:]
            after = re.sub(
                r'"minPublishers": \d+',
                f'"minPublishers": {change.new_min_publishers}',
                after,
                count=1,
            )
            block = before + after
        else:
            # No marketSchedules — apply to entire block
            block = re.sub(
                r'"minPublishers": \d+',
                f'"minPublishers": {change.new_min_publishers}',
                block,
                count=1,
            )

        raw = raw[:start] + block + raw[end:]

    # Write if not dry run and there are changes
    if not dry_run and updates_to_apply:
        backup_path = config_path + ".bak"
        shutil.copy2(config_path, backup_path)
        with open(config_path, "w") as f:
            f.write(raw)

    # Build summary
    summary = {
        "updated": sum(1 for c in changes if c.status == "UPDATED"),
        "skipped_low_publishers": sum(1 for c in changes if c.status == "SKIPPED_LOW_PUBLISHERS"),
        "skipped_equal": sum(1 for c in changes if c.status == "SKIPPED_EQUAL"),
        "skipped_higher": sum(1 for c in changes if c.status == "SKIPPED_HIGHER"),
        "needs_attention": sum(1 for c in changes if c.status == "NEEDS_ATTENTION"),
        "changes": changes,
    }
    return summary
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestModifyConfig -v
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/min_publishers.py tests/test_min_publishers.py
git commit -m "feat: add modify_config with surgical regex for top-level minPublishers"
```

---

## Chunk 3: CSV Report + Console Output + CLI Wrapper

### Task 5: CSV Report — write_csv_report

**Files:**
- Modify: `lib/min_publishers.py`
- Modify: `tests/test_min_publishers.py`

- [ ] **Step 1: Write failing tests for CSV report**

```python
# Append to tests/test_min_publishers.py
import csv

from lib.min_publishers import write_csv_report


class TestWriteCsvReport:
    """CSV audit report generation."""

    def test_csv_columns(self, tmp_path):
        """CSV has correct headers."""
        changes = [
            FeedChange(100, "Equity.US.FOO/USD", "equity", 1, 2, 5, "UPDATED"),
        ]
        csv_path = tmp_path / "report.csv"
        write_csv_report(changes, str(csv_path))

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == [
                "feed_id",
                "symbol",
                "asset_type",
                "old_min_publishers",
                "new_min_publishers",
                "allowed_publisher_count",
                "status",
            ]

    def test_csv_all_statuses(self, tmp_path):
        """CSV includes all status types."""
        changes = [
            FeedChange(100, "A/USD", "equity", 1, 2, 5, "UPDATED"),
            FeedChange(200, "B/USD", "equity", 1, None, 3, "SKIPPED_LOW_PUBLISHERS"),
            FeedChange(300, "C/USD", "equity", 2, None, 5, "SKIPPED_EQUAL"),
            FeedChange(400, "D/USD", "equity", 3, None, 5, "SKIPPED_HIGHER"),
            FeedChange(500, "E/USD", "equity", 1, None, 1, "NEEDS_ATTENTION"),
        ]
        csv_path = tmp_path / "report.csv"
        write_csv_report(changes, str(csv_path))

        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 5
        statuses = [r["status"] for r in rows]
        assert "UPDATED" in statuses
        assert "SKIPPED_LOW_PUBLISHERS" in statuses
        assert "SKIPPED_EQUAL" in statuses
        assert "SKIPPED_HIGHER" in statuses
        assert "NEEDS_ATTENTION" in statuses

    def test_csv_none_new_min_publishers(self, tmp_path):
        """Skipped feeds have empty new_min_publishers in CSV."""
        changes = [
            FeedChange(100, "A/USD", "equity", 1, None, 3, "SKIPPED_LOW_PUBLISHERS"),
        ]
        csv_path = tmp_path / "report.csv"
        write_csv_report(changes, str(csv_path))

        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["new_min_publishers"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestWriteCsvReport -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# Add to lib/min_publishers.py
import csv as csv_module


def write_csv_report(changes: list[FeedChange], output_path: str) -> None:
    """Write the change report CSV."""
    fieldnames = [
        "feed_id",
        "symbol",
        "asset_type",
        "old_min_publishers",
        "new_min_publishers",
        "allowed_publisher_count",
        "status",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv_module.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for change in changes:
            writer.writerow(
                {
                    "feed_id": change.feed_id,
                    "symbol": change.symbol,
                    "asset_type": change.asset_type,
                    "old_min_publishers": change.old_min_publishers,
                    "new_min_publishers": change.new_min_publishers if change.new_min_publishers is not None else "",
                    "allowed_publisher_count": change.allowed_publisher_count,
                    "status": change.status,
                }
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestWriteCsvReport -v
```

Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/min_publishers.py tests/test_min_publishers.py
git commit -m "feat: add CSV report writer for min_publishers changes"
```

---

### Task 6: Console Output — print_summary

**Files:**
- Modify: `lib/min_publishers.py`
- Modify: `tests/test_min_publishers.py`

- [ ] **Step 1: Write failing test for console output**

```python
# Append to tests/test_min_publishers.py
from lib.min_publishers import print_summary


class TestPrintSummary:
    """Console output formatting."""

    def test_summary_output(self, capsys):
        """Verify console output format."""
        changes = [
            FeedChange(100, "A/USD", "equity", 1, 2, 5, "UPDATED"),
            FeedChange(200, "B/USD", "equity", 1, 3, 8, "UPDATED"),
            FeedChange(300, "C/USD", "equity", 2, None, 5, "SKIPPED_EQUAL"),
            FeedChange(400, "D/USD", "equity", 1, None, 3, "SKIPPED_LOW_PUBLISHERS"),
            FeedChange(500, "E/USD", "equity", 1, None, 1, "NEEDS_ATTENTION"),
        ]
        stats = {
            "stable_count": 10,
            "excluded_type_count": 2,
            "excluded_type_breakdown": {"funding-rate": 2},
            "excluded_extended_count": 3,
        }

        print_summary(changes, stats, dry_run=True)

        output = capsys.readouterr().out
        assert "STABLE feeds: 10" in output
        assert "Excluded (asset type): 2" in output
        assert "Excluded (extended-hours): 3" in output
        assert "Needs attention" in output
        assert "DRY RUN" in output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestPrintSummary -v
```

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# Add to lib/min_publishers.py
from collections import Counter


def print_summary(
    changes: list[FeedChange],
    stats: dict,
    dry_run: bool = False,
) -> None:
    """Print human-readable summary to console."""
    print("Scanning after.json...")
    print(f"  STABLE feeds: {stats['stable_count']}")

    # Excluded by type
    exc_type = stats["excluded_type_count"]
    breakdown = stats["excluded_type_breakdown"]
    if breakdown:
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(breakdown.items()))
        print(f"  Excluded (asset type): {exc_type} ({parts})")
    else:
        print(f"  Excluded (asset type): {exc_type}")

    print(f"  Excluded (extended-hours): {stats['excluded_extended_count']}")

    # Count statuses
    needs_attention = [c for c in changes if c.status == "NEEDS_ATTENTION"]
    low_pub = [c for c in changes if c.status == "SKIPPED_LOW_PUBLISHERS"]
    updated = [c for c in changes if c.status == "UPDATED"]
    skipped = [c for c in changes if c.status in ("SKIPPED_EQUAL", "SKIPPED_HIGHER")]

    print(f"  Needs attention (<2 publishers): {len(needs_attention)}")
    if needs_attention:
        for c in needs_attention:
            print(f"    - {c.symbol} (feedId={c.feed_id}, publishers={c.allowed_publisher_count})")

    print(f"  Skipped (2-4 publishers): {len(low_pub)}")
    eligible = len(updated) + len(skipped)
    print(f"  Eligible for rule evaluation: {eligible}")

    print()
    print("Changes:")

    # Group updates by transition
    transitions: Counter[str] = Counter()
    for c in updated:
        key = f"{c.old_min_publishers} -> {c.new_min_publishers}"
        transitions[key] += 1

    for transition, count in sorted(transitions.items()):
        old, new = transition.split(" -> ")
        print(f"  {count} feeds: minPublishers {transition}")

    print(f"  {len(skipped)} feeds: skipped (already >= target)")

    if dry_run:
        print()
        print("[DRY RUN] No changes written.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestPrintSummary -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/min_publishers.py tests/test_min_publishers.py
git commit -m "feat: add console summary output for min_publishers"
```

---

### Task 7: CLI Wrapper — update_min_publishers.py

**Files:**
- Create: `update_min_publishers.py`
- Modify: `tests/test_min_publishers.py`

- [ ] **Step 1: Write failing CLI integration test**

```python
# Append to tests/test_min_publishers.py
import subprocess
import sys


class TestCLI:
    """CLI integration tests."""

    def _make_config_file(self, tmp_path):
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                },
                {
                    "allowedPublisherIds": [10, 20],
                    "feedId": 200,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "funding-rate", "name": "FR"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "FundingRate.X/Y",
                },
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))
        return config_file

    def test_cli_dry_run(self, tmp_path):
        config_file = self._make_config_file(tmp_path)
        csv_path = tmp_path / "report.csv"

        result = subprocess.run(
            [
                sys.executable,
                "update_min_publishers.py",
                "--config",
                str(config_file),
                "--dry-run",
                "--output-csv",
                str(csv_path),
            ],
            capture_output=True,
            text=True,
            cwd="/home/mariobern/integration-benchmarking",
        )

        assert result.returncode == 0
        assert "DRY RUN" in result.stdout
        # File unchanged
        data = json.loads(config_file.read_text())
        assert data["feeds"][0]["minPublishers"] == 1
        # CSV created
        assert csv_path.exists()

    def test_cli_real_run(self, tmp_path):
        config_file = self._make_config_file(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                "update_min_publishers.py",
                "--config",
                str(config_file),
                "--output-csv",
                str(tmp_path / "report.csv"),
            ],
            capture_output=True,
            text=True,
            cwd="/home/mariobern/integration-benchmarking",
        )

        assert result.returncode == 0
        data = json.loads(config_file.read_text())
        assert data["feeds"][0]["minPublishers"] == 2
        # funding-rate feed untouched
        assert data["feeds"][1]["minPublishers"] == 1

    def test_cli_asset_classes_filter(self, tmp_path):
        config_file = self._make_config_file(tmp_path)

        result = subprocess.run(
            [
                sys.executable,
                "update_min_publishers.py",
                "--config",
                str(config_file),
                "--asset-classes",
                "funding-rate",
                "--output-csv",
                str(tmp_path / "report.csv"),
            ],
            capture_output=True,
            text=True,
            cwd="/home/mariobern/integration-benchmarking",
        )

        assert result.returncode == 0
        # equity feed untouched (not in allowlist)
        data = json.loads(config_file.read_text())
        assert data["feeds"][0]["minPublishers"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestCLI -v
```

Expected: FAIL — script doesn't exist

- [ ] **Step 3: Write the CLI wrapper**

```python
# update_min_publishers.py
"""
Enforce minimum minPublishers values in after.json based on publisher count.

Usage:
    python3 update_min_publishers.py --config after.json --dry-run
    python3 update_min_publishers.py --config after.json --output-csv changes.csv
    python3 update_min_publishers.py --config after.json --asset-classes fx commodity
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from lib.min_publishers import (
    DEFAULT_CUTOFF,
    DEFAULT_EXCLUDED_ASSET_TYPES,
    DEFAULT_FLOOR,
    evaluate_feeds,
    is_extended_hours,
    modify_config,
    print_summary,
    write_csv_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enforce minimum minPublishers values in after.json"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to after.json config file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to file",
    )
    parser.add_argument(
        "--output-csv",
        default="min_publishers_changes.csv",
        help="Path for the change report CSV (default: min_publishers_changes.csv)",
    )
    parser.add_argument(
        "--asset-classes",
        nargs="+",
        default=None,
        help="Explicit allowlist of asset types to process (overrides default exclusions)",
    )
    parser.add_argument(
        "--min-publisher-floor",
        type=int,
        default=DEFAULT_FLOOR,
        help=f"Minimum publisher count to start enforcing (default: {DEFAULT_FLOOR})",
    )
    parser.add_argument(
        "--publisher-tier-cutoff",
        type=int,
        default=DEFAULT_CUTOFF,
        help=f"Publisher count boundary for tier 2 vs tier 3 (default: {DEFAULT_CUTOFF})",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)

    # Load feeds for stats computation
    with open(config_path) as f:
        data = json.load(f)

    feeds = data["feeds"]
    # Compute stats for console output
    stable_feeds = [f for f in feeds if f.get("state") == "STABLE"]
    stable_count = len(stable_feeds)

    excluded_type_breakdown: Counter[str] = Counter()
    excluded_extended_count = 0
    for feed in stable_feeds:
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        if args.asset_classes is not None:
            if asset_type not in args.asset_classes:
                excluded_type_breakdown[asset_type] += 1
        elif asset_type in DEFAULT_EXCLUDED_ASSET_TYPES:
            excluded_type_breakdown[asset_type] += 1

    for feed in stable_feeds:
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        if args.asset_classes is not None:
            if asset_type not in args.asset_classes:
                continue
        elif asset_type in DEFAULT_EXCLUDED_ASSET_TYPES:
            continue
        if is_extended_hours(feed):
            excluded_extended_count += 1

    stats = {
        "stable_count": stable_count,
        "excluded_type_count": sum(excluded_type_breakdown.values()),
        "excluded_type_breakdown": dict(excluded_type_breakdown),
        "excluded_extended_count": excluded_extended_count,
    }

    # Run modify_config (handles evaluate + apply)
    result = modify_config(
        str(config_path),
        dry_run=args.dry_run,
        floor=args.min_publisher_floor,
        cutoff=args.publisher_tier_cutoff,
        asset_classes=args.asset_classes,
    )

    changes = result["changes"]

    # Print summary
    print_summary(changes, stats, dry_run=args.dry_run)

    # Write CSV report
    write_csv_report(changes, args.output_csv)
    print(f"Report: {args.output_csv}")

    if not args.dry_run and result["updated"] > 0:
        print(f"Backup: {args.config}.bak")
        print(f"Updated {result['updated']} feeds in {args.config}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py::TestCLI -v
```

Expected: All 3 tests PASS

- [ ] **Step 5: Run ALL tests**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/test_min_publishers.py -v
```

Expected: All tests PASS (6 + 13 + 6 + 5 + 3 + 1 + 3 = 37 tests)

- [ ] **Step 6: Run pre-commit hooks**

```bash
cd /home/mariobern/integration-benchmarking && pre-commit run --files update_min_publishers.py lib/min_publishers.py tests/test_min_publishers.py
```

Expected: All hooks pass (black, trailing whitespace, end-of-file fixer)

- [ ] **Step 7: Commit**

```bash
git add update_min_publishers.py lib/min_publishers.py tests/test_min_publishers.py
git commit -m "feat: add update_min_publishers CLI wrapper with full test suite"
```

---

## Chunk 4: Validation Against Real Data

### Task 8: Validate Against Real after.json

This task runs the script against the actual after.json to verify the numbers match the spec.

- [ ] **Step 1: Dry run against real after.json**

```bash
cd /home/mariobern/integration-benchmarking && python3 update_min_publishers.py --config after.json --dry-run --output-csv /tmp/min_pub_dry_run.csv
```

Expected output should match spec numbers:
- STABLE feeds: 830
- Excluded (asset type): 34
- Excluded (extended-hours): 81
- Needs attention: 0
- Skipped (2-4 publishers): 44
- 19 feeds: 1 → 2
- 32 feeds: 1 → 3
- 14 feeds: 2 → 3
- 606 feeds: skipped

- [ ] **Step 2: Inspect CSV report**

```bash
head -20 /tmp/min_pub_dry_run.csv
```

Verify CSV columns and status values are correct.

- [ ] **Step 3: Count UPDATED rows in CSV**

```bash
grep -c "UPDATED" /tmp/min_pub_dry_run.csv
```

Expected: 65

- [ ] **Step 4: Verify no regressions in existing tests**

```bash
cd /home/mariobern/integration-benchmarking && python3 -m pytest tests/ -v --timeout=60
```

Expected: All existing tests still pass

- [ ] **Step 5: Commit any fixes from validation**

Only if issues were found and fixed. Otherwise skip.
