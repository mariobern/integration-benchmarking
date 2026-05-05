# edit-config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tools/edit-config/`, a surgical CLI editor for `after.json` that supports add/remove publisher, set/bump `minPublishers`, and set `state` — with single-op CLI flags, batched YAML specs, mixed feed-ID selectors (singles + ranges, file/stdin input), per-session targeting for US equity feeds, dry-run-by-default execution with hunk-headed diffs, atomic writes, and post-apply config-linter integration.

**Architecture:** Pure-Python CLI under `tools/edit-config/`. The orchestrator parses CLI flags or YAML into a list of `(Op, FilterSet)` planned ops, simulates them against a deep-copied parsed dict (so inter-op effects are visible), then applies the resulting `Change` records to the raw text via surgical bracket-aware edits to preserve formatting. No imports from existing repo `update_*.py` scripts or repo-level `lib/`.

**Tech Stack:** Python 3.11+, pytest, pytest-cov, PyYAML for YAML spec parsing, stdlib `fnmatch` for symbol globs, stdlib `subprocess` for invoking `tools/config-linter/config_linter.py`, stdlib `difflib` for unified diff generation.

---

## File Structure

| Path                                                  | Purpose                                                                                                                                            |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tools/edit-config/edit_config.py`                    | CLI wrapper (~80 LOC); argparse, dispatch to `lib/config_editor`                                                                                   |
| `tools/edit-config/lib/__init__.py`                   | package marker                                                                                                                                     |
| `tools/edit-config/lib/config_selector.py`            | parse mixed singles+ranges into `set[int]` (used by CLI flag, file, YAML)                                                                          |
| `tools/edit-config/lib/config_text_surgery.py`        | bracket-depth scanner; locators for feed blocks, session blocks, and field byte-spans                                                              |
| `tools/edit-config/lib/config_ops.py`                 | `Change`, `Warning`, `OpError` records; operation classes (`AddPublisher`, `RemovePublisher`, `SetMinPublishers`, `BumpMinPublishers`, `SetState`) |
| `tools/edit-config/lib/config_diff.py`                | render `Change` list as a unified diff with custom feedId/symbol/session hunk headers; truncate at N hunks                                         |
| `tools/edit-config/lib/config_editor.py`              | orchestrator: parse CLI/YAML → `Plan`, resolve filters, simulate, apply, backup, write, run linter                                                 |
| `tools/edit-config/tests/__init__.py`                 | package marker                                                                                                                                     |
| `tools/edit-config/tests/conftest.py`                 | pytest path setup                                                                                                                                  |
| `tools/edit-config/tests/test_config_selector.py`     |                                                                                                                                                    |
| `tools/edit-config/tests/test_config_text_surgery.py` |                                                                                                                                                    |
| `tools/edit-config/tests/test_config_ops.py`          |                                                                                                                                                    |
| `tools/edit-config/tests/test_config_diff.py`         |                                                                                                                                                    |
| `tools/edit-config/tests/test_config_editor.py`       |                                                                                                                                                    |
| `tools/edit-config/tests/test_edit_config_cli.py`     |                                                                                                                                                    |
| `tools/edit-config/tests/fixtures/after_sample.json`  | ~6 feeds spanning crypto, fx, equity-4-session, COMING_SOON, INACTIVE                                                                              |
| `tools/edit-config/tests/fixtures/edits_basic.yaml`   | golden YAML spec                                                                                                                                   |
| `tools/edit-config/tests/fixtures/edits_invalid.yaml` | malformed spec for error-path tests                                                                                                                |
| `docs/edit_config.md`                                 | usage reference                                                                                                                                    |
| `docs/edit_config_examples.md`                        | recipes                                                                                                                                            |
| `CLAUDE.md` (modify)                                  | add row in the Scripts table                                                                                                                       |

> **Note:** `lib/config_selector.py` was added relative to the design spec. The selector grammar is reusable across CLI flag, file input, and YAML field, and benefits from a dedicated focused module + isolated unit tests.

---

## Task 1: Bootstrap — dependencies, package markers, pytest discovery

**Files:**

- Modify: `requirements.txt`
- Create: `tools/edit-config/lib/__init__.py`
- Create: `tools/edit-config/tests/__init__.py`
- Create: `tools/edit-config/tests/conftest.py`

- [ ] **Step 1: Add `pytest-cov` to requirements.txt**

Add a new line under the existing `pytest>=7.0.0` line:

```
pytest-cov>=4.0
```

Then install:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 2: Create lib package marker**

Create `tools/edit-config/lib/__init__.py`:

```python
"""edit-config: surgical editor for after.json."""
```

- [ ] **Step 3: Create tests package marker and conftest**

Create `tools/edit-config/tests/__init__.py` as an empty file.

Create `tools/edit-config/tests/conftest.py`:

```python
import sys
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOL_ROOT))
```

- [ ] **Step 4: Verify pytest discovery works**

```bash
pytest tools/edit-config/tests/ --collect-only -q
```

Expected: `0 tests collected` (no tests yet, no errors).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tools/edit-config/lib/__init__.py tools/edit-config/tests/__init__.py tools/edit-config/tests/conftest.py
pre-commit run --files requirements.txt tools/edit-config/lib/__init__.py tools/edit-config/tests/__init__.py tools/edit-config/tests/conftest.py
git commit -m "chore(edit-config): bootstrap package, deps, pytest discovery"
```

---

## Task 2: Build minimal `after.json` test fixture

**Files:**

- Create: `tools/edit-config/tests/fixtures/after_sample.json`

The fixture covers schema variety: top-level-only (crypto/fx), 4-session equity, COMING_SOON, INACTIVE. Used by ops tests and integration tests.

- [ ] **Step 1: Author the fixture**

Create `tools/edit-config/tests/fixtures/after_sample.json`:

```json
{
  "featureFlags": [],
  "feeds": [
    {
      "allowedPublisherIds": [1, 3, 7, 11],
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 1,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "crypto",
        "name": "BTCUSD",
        "symbol": "Crypto.BTC/USD"
      },
      "minPublishers": 3,
      "state": "STABLE",
      "symbol": "Crypto.BTC/USD"
    },
    {
      "allowedPublisherIds": [19, 22, 41, 42, 45, 54, 55, 59, 65],
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 100,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "fx",
        "name": "EURUSD",
        "symbol": "FX.EUR/USD"
      },
      "minPublishers": 3,
      "state": "STABLE",
      "symbol": "FX.EUR/USD"
    },
    {
      "allowedPublisherIds": [
        11, 12, 13, 14, 19, 20, 21, 22, 26, 29, 32, 35, 41, 42, 45, 48, 54, 55,
        57, 59, 64, 65, 69, 71, 72, 73
      ],
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 922,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [
            12, 14, 19, 20, 21, 22, 26, 29, 35, 41, 42, 45, 48, 54, 55, 59, 64,
            65, 69, 71
          ],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "minPublishers": 3,
          "session": "REGULAR"
        },
        {
          "allowedPublisherIds": [19, 20, 22, 41, 42, 45, 55, 59, 65],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "minPublishers": 2,
          "session": "PRE_MARKET"
        },
        {
          "allowedPublisherIds": [19, 22, 41, 42, 45, 54, 55, 59, 65],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "minPublishers": 2,
          "session": "POST_MARKET"
        },
        {
          "allowedPublisherIds": [32, 41, 42],
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "minPublishers": 2,
          "session": "OVER_NIGHT"
        }
      ],
      "metadata": {
        "asset_type": "equity",
        "name": "AAPL",
        "symbol": "Equity.US.AAPL/USD"
      },
      "minPublishers": 1,
      "state": "STABLE",
      "symbol": "Equity.US.AAPL/USD"
    },
    {
      "allowedPublisherIds": [22, 41, 54, 55],
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 1023,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "equity",
        "name": "SMLC",
        "symbol": "Equity.US.SMLC/USD"
      },
      "minPublishers": 2,
      "state": "STABLE",
      "symbol": "Equity.US.SMLC/USD"
    },
    {
      "allowedPublisherIds": [],
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 5000,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "crypto",
        "name": "NEWCOIN",
        "symbol": "Crypto.NEW/USD"
      },
      "minPublishers": 3,
      "state": "COMING_SOON",
      "symbol": "Crypto.NEW/USD"
    },
    {
      "allowedPublisherIds": [19, 22],
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 6000,
      "isEnabledInShard": false,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "marketSchedule": "America/New_York;C,O,O,O,O,O,C;",
          "session": "REGULAR"
        }
      ],
      "metadata": {
        "asset_type": "fx",
        "name": "OLDPAIR",
        "symbol": "FX.OLD/USD"
      },
      "minPublishers": 1,
      "state": "INACTIVE",
      "symbol": "FX.OLD/USD"
    }
  ]
}
```

- [ ] **Step 2: Verify it parses as JSON**

```bash
python3 -c "import json; print(len(json.load(open('tools/edit-config/tests/fixtures/after_sample.json'))['feeds']))"
```

Expected: `6`

- [ ] **Step 3: Commit**

```bash
git add tools/edit-config/tests/fixtures/after_sample.json
pre-commit run --files tools/edit-config/tests/fixtures/after_sample.json
git commit -m "test(edit-config): add minimal after.json fixture"
```

---

## Task 3: Feed-ID selector parser — text input

**Files:**

- Create: `tools/edit-config/lib/config_selector.py`
- Create: `tools/edit-config/tests/test_config_selector.py`

The selector grammar: tokens are `N` (single ID) or `A-B` (inclusive range). Separators: `[,\s]+`. `#` to EOL stripped. Range requires `A <= B`. Empty result is a hard error at the call site (not the parser's concern; parser returns `set()`).

- [ ] **Step 1: Write failing tests**

Create `tools/edit-config/tests/test_config_selector.py`:

```python
import pytest
from lib.config_selector import parse_selector_text, SelectorError


class TestParseSelectorText:
    def test_single_id(self):
        assert parse_selector_text("922") == {922}

    def test_comma_list(self):
        assert parse_selector_text("1,2,3") == {1, 2, 3}

    def test_inclusive_range(self):
        assert parse_selector_text("100-103") == {100, 101, 102, 103}

    def test_mixed(self):
        result = parse_selector_text("100-102,205,208,300-301")
        assert result == {100, 101, 102, 205, 208, 300, 301}

    def test_whitespace_separators(self):
        assert parse_selector_text("1 2  3\n4\t5") == {1, 2, 3, 4, 5}

    def test_mixed_separators(self):
        assert parse_selector_text("1, 2\n3,4 5") == {1, 2, 3, 4, 5}

    def test_strips_line_comments(self):
        text = "100-102  # the contig run\n205 # one off\n208"
        assert parse_selector_text(text) == {100, 101, 102, 205, 208}

    def test_blank_lines_ignored(self):
        assert parse_selector_text("\n\n100\n\n200\n") == {100, 200}

    def test_dedup(self):
        assert parse_selector_text("1,1,2,2,1") == {1, 2}

    def test_overlapping_ranges_dedup(self):
        assert parse_selector_text("100-105,103-107") == {100, 101, 102, 103, 104, 105, 106, 107}

    def test_empty_input_returns_empty_set(self):
        assert parse_selector_text("") == set()
        assert parse_selector_text("   \n  ") == set()
        assert parse_selector_text("# only comments\n# more comments") == set()

    def test_invalid_token_raises(self):
        with pytest.raises(SelectorError, match="invalid token"):
            parse_selector_text("1,abc,3")

    def test_invalid_range_descending(self):
        with pytest.raises(SelectorError, match="range bounds"):
            parse_selector_text("200-100")

    def test_invalid_negative(self):
        with pytest.raises(SelectorError, match="invalid token"):
            parse_selector_text("-5")

    def test_error_includes_position(self):
        with pytest.raises(SelectorError, match="line 2"):
            parse_selector_text("100\nbadtoken\n200")
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_selector.py -v
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'lib.config_selector'`.

- [ ] **Step 3: Implement `lib/config_selector.py`**

Create `tools/edit-config/lib/config_selector.py`:

```python
"""Parse the unified feed-ID selector grammar.

Tokens: N (single ID) or A-B (inclusive range with A <= B).
Separators: any combination of commas, whitespace, newlines.
Comments: # to end-of-line is stripped.
"""

import re
from pathlib import Path


class SelectorError(ValueError):
    """Raised on malformed selector input."""


_TOKEN_PATTERN = re.compile(r"^(\d+)(?:-(\d+))?$")


def parse_selector_text(text: str) -> set[int]:
    """Parse selector text into a set of feed IDs.

    Returns an empty set for empty input. Raises SelectorError on
    malformed tokens or descending ranges, with line number in the
    message.
    """
    result: set[int] = set()
    for line_no, line in enumerate(text.splitlines() or [text], start=1):
        comment_idx = line.find("#")
        if comment_idx >= 0:
            line = line[:comment_idx]
        for token in re.split(r"[,\s]+", line):
            if not token:
                continue
            match = _TOKEN_PATTERN.match(token)
            if not match:
                raise SelectorError(
                    f"invalid token {token!r} on line {line_no}"
                )
            lo = int(match.group(1))
            hi = int(match.group(2)) if match.group(2) is not None else lo
            if hi < lo:
                raise SelectorError(
                    f"range bounds out of order: {token!r} on line {line_no}"
                )
            result.update(range(lo, hi + 1))
    return result


def read_selector_file(path: str | Path) -> set[int]:
    """Read selector content from a file path or '-' for stdin."""
    import sys

    if str(path) == "-":
        return parse_selector_text(sys.stdin.read())
    return parse_selector_text(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_selector.py -v
```

Expected: all 16 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_selector.py tools/edit-config/tests/test_config_selector.py
pre-commit run --files tools/edit-config/lib/config_selector.py tools/edit-config/tests/test_config_selector.py
git commit -m "feat(edit-config): selector text parser with mixed singles+ranges"
```

---

## Task 4: Feed-ID selector parser — file and stdin readers

**Files:**

- Modify: `tools/edit-config/tests/test_config_selector.py`

`read_selector_file` was implemented in Task 3 but not tested. Add tests for file path and stdin paths.

- [ ] **Step 1: Add file/stdin tests**

Append to `tools/edit-config/tests/test_config_selector.py`:

```python
import io
from unittest.mock import patch


class TestReadSelectorFile:
    def test_reads_file(self, tmp_path):
        from lib.config_selector import read_selector_file

        f = tmp_path / "feeds.txt"
        f.write_text("100-102\n205\n# trailing\n208\n", encoding="utf-8")
        assert read_selector_file(f) == {100, 101, 102, 205, 208}

    def test_reads_stdin_when_dash(self):
        from lib.config_selector import read_selector_file

        with patch("sys.stdin", io.StringIO("1,2,3\n4-6\n")):
            assert read_selector_file("-") == {1, 2, 3, 4, 5, 6}

    def test_missing_file_raises(self, tmp_path):
        from lib.config_selector import read_selector_file

        with pytest.raises(FileNotFoundError):
            read_selector_file(tmp_path / "does_not_exist.txt")

    def test_invalid_token_includes_line_number(self, tmp_path):
        from lib.config_selector import read_selector_file, SelectorError

        f = tmp_path / "feeds.txt"
        f.write_text("100\nbad\n200", encoding="utf-8")
        with pytest.raises(SelectorError, match="line 2"):
            read_selector_file(f)
```

- [ ] **Step 2: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_selector.py -v
```

Expected: 20 tests pass (16 existing + 4 new).

- [ ] **Step 3: Commit**

```bash
git add tools/edit-config/tests/test_config_selector.py
pre-commit run --files tools/edit-config/tests/test_config_selector.py
git commit -m "test(edit-config): cover selector file/stdin readers"
```

---

## Task 5: Text surgery — bracket-depth scanner for balanced JSON objects

**Files:**

- Create: `tools/edit-config/lib/config_text_surgery.py`
- Create: `tools/edit-config/tests/test_config_text_surgery.py`

The scanner finds the closing `}` (or `]`) for an opening `{` (or `[`) at a given byte offset, while respecting strings and escape sequences. This primitive is used by feed-block, session-block, and array-span locators.

- [ ] **Step 1: Write failing tests**

Create `tools/edit-config/tests/test_config_text_surgery.py`:

```python
import pytest
from lib.config_text_surgery import find_matching_close


class TestFindMatchingClose:
    def test_simple_object(self):
        s = "{}"
        assert find_matching_close(s, 0) == 1

    def test_simple_array(self):
        s = "[]"
        assert find_matching_close(s, 0) == 1

    def test_nested_object(self):
        s = '{"a": {"b": 1}}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_nested_array(self):
        s = "[[1, 2], [3, 4]]"
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_close_brace(self):
        s = '{"a": "}"}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_close_bracket(self):
        s = '["]", "x"]'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_escaped_quote(self):
        s = '{"a": "he said \\"hi\\""}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_escaped_backslash_then_quote(self):
        # "abc\\" — backslash is escaped, the quote then closes the string
        s = '{"a": "abc\\\\"}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_starts_at_inner_open(self):
        s = '{"a": {"b": 1}}'
        # Inner { starts at index 6 (after '"a": ')
        assert find_matching_close(s, 6) == 13

    def test_unbalanced_returns_none(self):
        assert find_matching_close("{[}", 0) is None
        assert find_matching_close("{", 0) is None

    def test_offset_not_on_open_returns_none(self):
        assert find_matching_close('{"a": 1}', 1) is None
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_text_surgery.py -v
```

Expected: all fail with import error.

- [ ] **Step 3: Implement bracket scanner**

Create `tools/edit-config/lib/config_text_surgery.py`:

```python
"""Surgical text operations on after.json without losing formatting.

All locators operate on raw JSON text and return byte spans (start, end)
where `end` is exclusive (Python slice semantics).
"""


_OPEN_TO_CLOSE = {"{": "}", "[": "]"}


def find_matching_close(text: str, open_idx: int) -> int | None:
    """Return the index of the `}` or `]` matching the open bracket at
    `open_idx`. Respects JSON string literals and escape sequences.
    Returns None if `open_idx` is not on an open bracket or the input
    is unbalanced.
    """
    if open_idx >= len(text) or text[open_idx] not in _OPEN_TO_CLOSE:
        return None

    open_ch = text[open_idx]
    close_ch = _OPEN_TO_CLOSE[open_ch]
    depth = 0
    in_string = False
    i = open_idx
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 2  # skip the next char regardless
                continue
            if c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_text_surgery.py -v
```

Expected: 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
pre-commit run --files tools/edit-config/lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
git commit -m "feat(edit-config): bracket-depth scanner for balanced JSON spans"
```

---

## Task 6: Text surgery — locate feed block by `feedId`

**Files:**

- Modify: `tools/edit-config/lib/config_text_surgery.py`
- Modify: `tools/edit-config/tests/test_config_text_surgery.py`

`find_feed_block` returns `(start, end)` of the `{ ... }` enclosing the feed with the given `feedId`. `start` points at the opening `{`; `end` points at the index just after the matching `}`.

- [ ] **Step 1: Write failing tests**

Append to `tools/edit-config/tests/test_config_text_surgery.py`:

```python
from pathlib import Path
from lib.config_text_surgery import find_feed_block

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_sample.json"


class TestFindFeedBlock:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_finds_first_feed(self):
        bounds = find_feed_block(self.raw, 1)
        assert bounds is not None
        start, end = bounds
        block = self.raw[start:end]
        assert block.startswith("{")
        assert block.endswith("}")
        assert '"feedId": 1' in block

    def test_finds_feed_922(self):
        bounds = find_feed_block(self.raw, 922)
        assert bounds is not None
        start, end = bounds
        block = self.raw[start:end]
        assert '"feedId": 922' in block
        assert '"symbol": "Equity.US.AAPL/USD"' in block

    def test_missing_feed_returns_none(self):
        assert find_feed_block(self.raw, 99999) is None

    def test_does_not_match_substring_of_id(self):
        # feedId 100 should not be matched by a search for 10
        assert find_feed_block(self.raw, 10) is None
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_text_surgery.py::TestFindFeedBlock -v
```

Expected: all fail (function not yet defined).

- [ ] **Step 3: Implement `find_feed_block`**

Append to `tools/edit-config/lib/config_text_surgery.py`:

```python
import re


def find_feed_block(raw: str, feed_id: int) -> tuple[int, int] | None:
    """Locate the {…} of the feed with the given feedId.

    Returns (start, end) where start is the opening '{' and end is one
    past the matching '}'. None if feedId not found.
    """
    pattern = re.compile(rf'"feedId":\s*{feed_id}\s*[,\n}}]')
    match = pattern.search(raw)
    if match is None:
        return None

    # Walk backwards from the match to find the enclosing '{'.
    pos = match.start()
    depth = 0
    in_string = False
    while pos >= 0:
        c = raw[pos]
        if in_string:
            if c == '"' and (pos == 0 or raw[pos - 1] != "\\"):
                in_string = False
            pos -= 1
            continue
        if c == '"':
            in_string = True
        elif c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        pos -= 1

    if pos < 0:
        return None

    close_idx = find_matching_close(raw, pos)
    if close_idx is None:
        return None
    return (pos, close_idx + 1)
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_text_surgery.py -v
```

Expected: all tests pass (15 total).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
pre-commit run --files tools/edit-config/lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
git commit -m "feat(edit-config): locate feed block by feedId"
```

---

## Task 7: Text surgery — locate session block and field spans within a feed block

**Files:**

- Modify: `tools/edit-config/lib/config_text_surgery.py`
- Modify: `tools/edit-config/tests/test_config_text_surgery.py`

We need to find:

- `find_session_block(feed_block, session_name)` → bounds of one entry within `marketSchedules`
- `find_publisher_array_span(block)` → bounds of the `[ … ]` value of `allowedPublisherIds` (top-level OR within a session block, depending on what you pass in)
- `find_int_field_span(block, key)` → byte span of the **value** of `"key": N` (used for `minPublishers`)
- `find_string_field_span(block, key)` → byte span of the **value** including surrounding quotes (used for `state`)

All return `(start, end)` relative to the input `block`, not absolute. None if missing.

- [ ] **Step 1: Write failing tests**

Append to `test_config_text_surgery.py`:

```python
from lib.config_text_surgery import (
    find_session_block,
    find_publisher_array_span,
    find_int_field_span,
    find_string_field_span,
)


class TestFindSessionBlock:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")
        start, end = find_feed_block(self.raw, 922)
        self.feed_block = self.raw[start:end]

    def test_finds_regular(self):
        bounds = find_session_block(self.feed_block, "REGULAR")
        assert bounds is not None
        s, e = bounds
        sub = self.feed_block[s:e]
        assert '"session": "REGULAR"' in sub

    def test_finds_pre_market(self):
        bounds = find_session_block(self.feed_block, "PRE_MARKET")
        assert bounds is not None
        s, e = bounds
        assert '"session": "PRE_MARKET"' in self.feed_block[s:e]

    def test_missing_session_returns_none(self):
        # PRE_MARKET on a single-session feed
        start, end = find_feed_block(self.raw, 1)
        crypto_block = self.raw[start:end]
        assert find_session_block(crypto_block, "PRE_MARKET") is None


class TestFindPublisherArraySpan:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_top_level_array(self):
        start, end = find_feed_block(self.raw, 1)
        block = self.raw[start:end]
        bounds = find_publisher_array_span(block)
        assert bounds is not None
        s, e = bounds
        # The slice should be exactly the [ … ] value
        assert block[s] == "["
        assert block[e - 1] == "]"
        # Contents should match: [ 1, 3, 7, 11 ]
        assert "1" in block[s:e] and "11" in block[s:e]

    def test_session_array(self):
        start, end = find_feed_block(self.raw, 922)
        feed = self.raw[start:end]
        s_start, s_end = find_session_block(feed, "OVER_NIGHT")
        sess = feed[s_start:s_end]
        bounds = find_publisher_array_span(sess)
        assert bounds is not None
        s, e = bounds
        assert sess[s] == "["
        assert sess[e - 1] == "]"


class TestFindIntFieldSpan:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_top_level_min_publishers(self):
        # We want the top-level minPublishers, not a session's. Pass
        # the top-level "tail" portion of the feed (after marketSchedules).
        start, end = find_feed_block(self.raw, 922)
        feed = self.raw[start:end]
        # locate marketSchedules end and search after that
        ms_idx = feed.index('"marketSchedules":')
        ms_open = feed.index("[", ms_idx)
        ms_close = find_matching_close(feed, ms_open)
        tail = feed[ms_close + 1 :]
        bounds = find_int_field_span(tail, "minPublishers")
        assert bounds is not None
        s, e = bounds
        # The value of feed 922 top-level minPublishers is 1.
        assert tail[s:e] == "1"

    def test_session_min_publishers(self):
        start, end = find_feed_block(self.raw, 922)
        feed = self.raw[start:end]
        s_start, s_end = find_session_block(feed, "REGULAR")
        sess = feed[s_start:s_end]
        bounds = find_int_field_span(sess, "minPublishers")
        assert bounds is not None
        s, e = bounds
        assert sess[s:e] == "3"


class TestFindStringFieldSpan:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_state_field(self):
        start, end = find_feed_block(self.raw, 1)
        feed = self.raw[start:end]
        bounds = find_string_field_span(feed, "state")
        assert bounds is not None
        s, e = bounds
        # Span should include the surrounding quotes
        assert feed[s] == '"'
        assert feed[e - 1] == '"'
        assert feed[s:e] == '"STABLE"'
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_text_surgery.py -v
```

Expected: new test classes fail (functions not defined).

- [ ] **Step 3: Implement the four locators**

Append to `lib/config_text_surgery.py`:

```python
def find_session_block(feed_block: str, session_name: str) -> tuple[int, int] | None:
    """Locate the {…} of the session entry with the given name.

    `feed_block` is the raw text of a single feed object (as returned
    by find_feed_block). Returns bounds relative to `feed_block`.
    """
    pattern = re.compile(rf'"session":\s*"{re.escape(session_name)}"')
    match = pattern.search(feed_block)
    if match is None:
        return None

    pos = match.start()
    depth = 0
    in_string = False
    while pos >= 0:
        c = feed_block[pos]
        if in_string:
            if c == '"' and (pos == 0 or feed_block[pos - 1] != "\\"):
                in_string = False
            pos -= 1
            continue
        if c == '"':
            in_string = True
        elif c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        pos -= 1

    if pos < 0:
        return None
    close_idx = find_matching_close(feed_block, pos)
    if close_idx is None:
        return None
    return (pos, close_idx + 1)


def find_publisher_array_span(block: str) -> tuple[int, int] | None:
    """Locate the [ … ] value of `allowedPublisherIds` within `block`.

    Returns (start, end) where start points at `[` and end is one past
    the closing `]`. None if the field is absent.
    """
    match = re.search(r'"allowedPublisherIds":\s*\[', block)
    if match is None:
        return None
    open_idx = match.end() - 1  # position of '['
    close_idx = find_matching_close(block, open_idx)
    if close_idx is None:
        return None
    return (open_idx, close_idx + 1)


def find_int_field_span(block: str, key: str) -> tuple[int, int] | None:
    """Locate the integer value of `"key": N` within `block`.

    Returns the byte span of the digit characters only (no surrounding
    whitespace, no comma). None if missing.
    """
    pattern = re.compile(rf'"{re.escape(key)}":\s*(-?\d+)')
    match = pattern.search(block)
    if match is None:
        return None
    return (match.start(1), match.end(1))


def find_string_field_span(block: str, key: str) -> tuple[int, int] | None:
    """Locate the quoted string value of `"key": "..."` within `block`.

    Returns the byte span INCLUDING the surrounding double quotes.
    None if missing.
    """
    pattern = re.compile(rf'"{re.escape(key)}":\s*("[^"\\]*(?:\\.[^"\\]*)*")')
    match = pattern.search(block)
    if match is None:
        return None
    return (match.start(1), match.end(1))
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_text_surgery.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
pre-commit run --files tools/edit-config/lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
git commit -m "feat(edit-config): session block + field span locators"
```

---

## Task 8: Operations — shared records and helper utilities

**Files:**

- Create: `tools/edit-config/lib/config_ops.py`
- Create: `tools/edit-config/tests/test_config_ops.py`

Operation classes consume a parsed feed dict (from `json.loads`), mutate the parsed structure in place, and emit `Change` records describing the location and new value. The orchestrator later applies the changes to raw text via `config_text_surgery`. This task lays down the shared types and a small helper for "is this an equity feed with sessions."

- [ ] **Step 1: Write failing tests**

Create `tools/edit-config/tests/test_config_ops.py`:

```python
import json
from pathlib import Path

import pytest

from lib.config_ops import (
    Change,
    Warning,
    OpError,
    has_session_publishers,
    get_session,
    SESSION_NAMES,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_sample.json"


@pytest.fixture
def feeds():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["feeds"]


def feed_by_id(feeds, fid):
    for f in feeds:
        if f["feedId"] == fid:
            return f
    raise AssertionError(f"feed {fid} not in fixture")


class TestSharedRecords:
    def test_change_is_frozen_dataclass(self):
        c = Change(
            feed_id=1, symbol="Crypto.BTC/USD", location="top_level",
            field="allowedPublisherIds", before=[1, 2], after=[1, 2, 3],
        )
        with pytest.raises(Exception):
            c.feed_id = 2  # type: ignore[misc]

    def test_warning_record(self):
        w = Warning(feed_id=1, symbol="X", message="hi")
        assert w.message == "hi"

    def test_op_error_is_exception(self):
        with pytest.raises(OpError):
            raise OpError("boom")


class TestSessionHelpers:
    def test_session_names_constant(self):
        assert set(SESSION_NAMES) == {"REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"}

    def test_has_session_publishers_true_for_equity_4_session(self, feeds):
        assert has_session_publishers(feed_by_id(feeds, 922)) is True

    def test_has_session_publishers_false_for_crypto(self, feeds):
        assert has_session_publishers(feed_by_id(feeds, 1)) is False

    def test_has_session_publishers_false_for_single_session_equity(self, feeds):
        # SMLC has only REGULAR with no per-session allowedPublisherIds
        assert has_session_publishers(feed_by_id(feeds, 1023)) is False

    def test_get_session_returns_dict(self, feeds):
        sess = get_session(feed_by_id(feeds, 922), "PRE_MARKET")
        assert sess is not None
        assert sess["session"] == "PRE_MARKET"

    def test_get_session_missing_returns_none(self, feeds):
        assert get_session(feed_by_id(feeds, 1), "PRE_MARKET") is None
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_ops.py -v
```

Expected: all fail with import errors.

- [ ] **Step 3: Implement shared types and helpers**

Create `tools/edit-config/lib/config_ops.py`:

```python
"""Operation classes for surgical edits to after.json.

Each Op takes a parsed feed dict and mutates it in place, returning a
list of Change records describing what was modified and a list of
Warning records for soft guardrails. Errors raise OpError.

Changes describe (feed_id, location, field, before, after) tuples.
The orchestrator applies them to the raw JSON text using config_text_surgery.
"""

from dataclasses import dataclass
from typing import Any


SESSION_NAMES: tuple[str, ...] = ("REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT")


@dataclass(frozen=True)
class Change:
    """One atomic edit to a feed."""

    feed_id: int
    symbol: str
    location: str  # "top_level" or one of SESSION_NAMES
    field: str  # "allowedPublisherIds", "minPublishers", "state"
    before: Any
    after: Any


@dataclass(frozen=True)
class Warning:
    feed_id: int
    symbol: str
    message: str


class OpError(Exception):
    """Raised by ops on validation errors that should block apply."""


def has_session_publishers(feed: dict) -> bool:
    """True if any marketSchedule entry has an `allowedPublisherIds` field."""
    return any(
        "allowedPublisherIds" in s for s in feed.get("marketSchedules", [])
    )


def get_session(feed: dict, session_name: str) -> dict | None:
    """Return the session entry with the given name, or None."""
    for s in feed.get("marketSchedules", []):
        if s.get("session") == session_name:
            return s
    return None
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_ops.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
pre-commit run --files tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): shared op records and session helpers"
```

---

## Task 9: Operation — `AddPublisher`

**Files:**

- Modify: `tools/edit-config/lib/config_ops.py`
- Modify: `tools/edit-config/tests/test_config_ops.py`

Per spec: default scope = `top-level + REGULAR` (equities) or `top-level only` (non-equities). Explicit `session` scopes: `REGULAR`, `PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT`, `ALL`, `NONE`. NOOP if already present everywhere targeted. Lists deduped + sorted ascending.

- [ ] **Step 1: Write failing tests**

Append to `test_config_ops.py`:

```python
from lib.config_ops import AddPublisher


class TestAddPublisher:
    def test_default_on_non_equity_adds_top_level(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto, no per-session lists
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        assert feed["allowedPublisherIds"] == [1, 3, 7, 11, 80]
        assert len(changes) == 1
        assert changes[0].location == "top_level"
        assert changes[0].field == "allowedPublisherIds"
        assert changes[0].before == [1, 3, 7, 11]
        assert changes[0].after == [1, 3, 7, 11, 80]
        assert warns == []

    def test_default_on_equity_adds_top_level_and_regular(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        assert 80 in feed["allowedPublisherIds"]
        regular = get_session(feed, "REGULAR")
        assert 80 in regular["allowedPublisherIds"]
        # PRE_MARKET should NOT be touched
        pre = get_session(feed, "PRE_MARKET")
        assert 80 not in pre["allowedPublisherIds"]
        locs = sorted(c.location for c in changes)
        assert locs == ["REGULAR", "top_level"]

    def test_explicit_pre_market_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="PRE_MARKET")
        changes, warns = op.apply(feed)
        assert 80 in feed["allowedPublisherIds"]
        assert 80 in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        # REGULAR not touched
        regular = get_session(feed, "REGULAR")
        assert 80 not in regular["allowedPublisherIds"]

    def test_session_all(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="ALL")
        changes, _ = op.apply(feed)
        for sname in SESSION_NAMES:
            sess = get_session(feed, sname)
            assert 80 in sess["allowedPublisherIds"]
        assert 80 in feed["allowedPublisherIds"]
        assert len(changes) == 5  # 4 sessions + top_level

    def test_session_none_only_top_level(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="NONE")
        changes, _ = op.apply(feed)
        assert 80 in feed["allowedPublisherIds"]
        for sname in SESSION_NAMES:
            sess = get_session(feed, sname)
            assert 80 not in sess["allowedPublisherIds"]
        assert len(changes) == 1
        assert changes[0].location == "top_level"

    def test_explicit_session_on_non_equity_raises(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto, no PRE_MARKET
        op = AddPublisher(publisher_id=80, session="PRE_MARKET")
        with pytest.raises(OpError, match="session.*does not exist"):
            op.apply(feed)

    def test_session_all_on_non_equity_raises(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = AddPublisher(publisher_id=80, session="ALL")
        with pytest.raises(OpError, match="no per-session"):
            op.apply(feed)

    def test_noop_when_already_present(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = AddPublisher(publisher_id=3)  # 3 already in [1, 3, 7, 11]
        changes, _ = op.apply(feed)
        assert changes == []

    def test_lists_deduped_and_sorted(self, feeds):
        feed = feed_by_id(feeds, 1)
        feed["allowedPublisherIds"] = [11, 1, 7, 3]  # not sorted
        op = AddPublisher(publisher_id=5)
        op.apply(feed)
        assert feed["allowedPublisherIds"] == [1, 3, 5, 7, 11]

    def test_empty_list_initial(self, feeds):
        feed = feed_by_id(feeds, 5000)  # COMING_SOON, empty list
        op = AddPublisher(publisher_id=80)
        changes, _ = op.apply(feed)
        assert feed["allowedPublisherIds"] == [80]
        assert len(changes) == 1
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_ops.py::TestAddPublisher -v
```

Expected: all fail with `ImportError: cannot import name 'AddPublisher'`.

- [ ] **Step 3: Implement `AddPublisher`**

Append to `lib/config_ops.py`:

```python
def _add_publisher_to_list(target: list[int], pub_id: int) -> tuple[list[int], list[int]] | None:
    """Helper: dedupe + sort + add. Returns (before, after) or None if NOOP."""
    before = list(target)
    if pub_id in before:
        merged = sorted(set(before))
        if merged == before:
            return None  # already present and sorted -> NOOP
        target[:] = merged
        return (before, merged)
    merged = sorted(set(before) | {pub_id})
    target[:] = merged
    return (before, merged)


@dataclass
class AddPublisher:
    publisher_id: int
    session: str | None = None  # None|REGULAR|PRE_MARKET|POST_MARKET|OVER_NIGHT|ALL|NONE

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        # Determine which lists to touch.
        targets: list[tuple[str, list[int]]] = []  # (location, list ref)

        if self.session is None:
            # Default scope
            targets.append(("top_level", feed.setdefault("allowedPublisherIds", [])))
            if has_session_publishers(feed):
                regular = get_session(feed, "REGULAR")
                if regular is not None and "allowedPublisherIds" in regular:
                    targets.append(("REGULAR", regular["allowedPublisherIds"]))
        elif self.session == "NONE":
            targets.append(("top_level", feed.setdefault("allowedPublisherIds", [])))
        elif self.session == "ALL":
            if not has_session_publishers(feed):
                raise OpError(
                    f"feed {feed_id}: session=ALL requires per-session publisher lists; "
                    f"feed has no per-session lists"
                )
            targets.append(("top_level", feed.setdefault("allowedPublisherIds", [])))
            for name in SESSION_NAMES:
                sess = get_session(feed, name)
                if sess is not None and "allowedPublisherIds" in sess:
                    targets.append((name, sess["allowedPublisherIds"]))
        elif self.session in SESSION_NAMES:
            sess = get_session(feed, self.session)
            if sess is None or "allowedPublisherIds" not in sess:
                raise OpError(
                    f"feed {feed_id}: session {self.session!r} does not exist on this feed"
                )
            targets.append(("top_level", feed.setdefault("allowedPublisherIds", [])))
            targets.append((self.session, sess["allowedPublisherIds"]))
        else:
            raise OpError(f"unknown session value: {self.session!r}")

        for location, ref in targets:
            result = _add_publisher_to_list(ref, self.publisher_id)
            if result is None:
                continue
            before, after = result
            changes.append(Change(
                feed_id=feed_id, symbol=symbol, location=location,
                field="allowedPublisherIds", before=before, after=after,
            ))

        return changes, warnings
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_ops.py -v
```

Expected: all (existing + 10 new) tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
pre-commit run --files tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): AddPublisher op with all session scopes"
```

---

## Task 10: Operation — `RemovePublisher`

**Files:**

- Modify: `tools/edit-config/lib/config_ops.py`
- Modify: `tools/edit-config/tests/test_config_ops.py`

Per spec: default = remove from EVERYWHERE in this feed (top-level + every session list). Explicit session removes from that one. `ALL` = every session, top-level untouched. `NONE` = top-level only (with consistency warning). NOOP if absent everywhere targeted. Warning if any list ends with `len <= minPublishers`.

- [ ] **Step 1: Write failing tests**

Append to `test_config_ops.py`:

```python
from lib.config_ops import RemovePublisher


class TestRemovePublisher:
    def test_default_removes_everywhere_on_equity(self, feeds):
        feed = feed_by_id(feeds, 922)
        # publisher 22 is in top-level + REGULAR + PRE_MARKET + POST_MARKET
        op = RemovePublisher(publisher_id=22)
        changes, _ = op.apply(feed)
        assert 22 not in feed["allowedPublisherIds"]
        for name in SESSION_NAMES:
            sess = get_session(feed, name)
            if sess and "allowedPublisherIds" in sess:
                assert 22 not in sess["allowedPublisherIds"]
        # 4 changes: top_level + REGULAR + PRE_MARKET + POST_MARKET
        # (OVER_NIGHT didn't have 22)
        assert len(changes) == 4

    def test_default_on_non_equity_removes_top_level(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = RemovePublisher(publisher_id=3)
        changes, _ = op.apply(feed)
        assert 3 not in feed["allowedPublisherIds"]
        assert len(changes) == 1

    def test_explicit_session_removes_only_that_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert 22 in feed["allowedPublisherIds"]  # top-level untouched
        assert 22 not in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert 22 in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert len(changes) == 1
        assert changes[0].location == "PRE_MARKET"

    def test_session_all_leaves_top_level(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="ALL")
        changes, _ = op.apply(feed)
        assert 22 in feed["allowedPublisherIds"]
        for name in SESSION_NAMES:
            sess = get_session(feed, name)
            if sess and "allowedPublisherIds" in sess:
                assert 22 not in sess["allowedPublisherIds"]
        assert all(c.location != "top_level" for c in changes)

    def test_session_none_warns_about_consistency(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="NONE")
        changes, warns = op.apply(feed)
        assert 22 not in feed["allowedPublisherIds"]
        # 22 still in REGULAR session -> consistency warning
        assert any("still in session" in w.message for w in warns)

    def test_noop_when_absent(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = RemovePublisher(publisher_id=999)
        changes, _ = op.apply(feed)
        assert changes == []

    def test_warns_when_at_or_below_min_publishers(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has [32, 41, 42] with minPublishers=2.
        # Remove 32 -> [41, 42] with min=2 -> at-floor warning.
        op = RemovePublisher(publisher_id=32, session="OVER_NIGHT")
        changes, warns = op.apply(feed)
        assert any("OVER_NIGHT" in w.message and "headroom" in w.message.lower()
                   for w in warns)

    def test_warns_for_top_level_at_floor(self, feeds):
        feed = feed_by_id(feeds, 6000)
        # top-level [19, 22], minPublishers=1. Remove 19 -> [22], min=1 -> warn
        op = RemovePublisher(publisher_id=19)
        changes, warns = op.apply(feed)
        assert any("top_level" in w.message or "headroom" in w.message.lower()
                   for w in warns)
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_ops.py::TestRemovePublisher -v
```

Expected: failures (RemovePublisher not defined).

- [ ] **Step 3: Implement `RemovePublisher`**

Append to `lib/config_ops.py`:

```python
def _remove_from_list(target: list[int], pub_id: int) -> tuple[list[int], list[int]] | None:
    before = list(target)
    if pub_id not in before:
        return None
    target[:] = [p for p in before if p != pub_id]
    return (before, list(target))


def _check_at_floor(
    feed_id: int, symbol: str, location: str, allowed: list[int], min_pub: int | None,
) -> Warning | None:
    if min_pub is None:
        return None
    if len(allowed) <= min_pub:
        return Warning(
            feed_id=feed_id, symbol=symbol,
            message=(
                f"feed {feed_id} {location}: after op, "
                f"{len(allowed)} publishers with minPublishers={min_pub} — "
                f"no headroom"
            ),
        )
    return None


@dataclass
class RemovePublisher:
    publisher_id: int
    session: str | None = None

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        targets: list[tuple[str, list[int], int | None]] = []  # location, list, min

        if self.session is None:
            # Default: remove from everywhere (top-level + every session).
            targets.append(("top_level", feed.get("allowedPublisherIds", []), feed.get("minPublishers")))
            for name in SESSION_NAMES:
                sess = get_session(feed, name)
                if sess and "allowedPublisherIds" in sess:
                    targets.append((name, sess["allowedPublisherIds"], sess.get("minPublishers")))
        elif self.session == "NONE":
            targets.append(("top_level", feed.get("allowedPublisherIds", []), feed.get("minPublishers")))
        elif self.session == "ALL":
            for name in SESSION_NAMES:
                sess = get_session(feed, name)
                if sess and "allowedPublisherIds" in sess:
                    targets.append((name, sess["allowedPublisherIds"], sess.get("minPublishers")))
        elif self.session in SESSION_NAMES:
            sess = get_session(feed, self.session)
            if sess is None or "allowedPublisherIds" not in sess:
                raise OpError(
                    f"feed {feed_id}: session {self.session!r} does not exist on this feed"
                )
            targets.append((self.session, sess["allowedPublisherIds"], sess.get("minPublishers")))
        else:
            raise OpError(f"unknown session value: {self.session!r}")

        for location, ref, min_pub in targets:
            result = _remove_from_list(ref, self.publisher_id)
            if result is None:
                continue
            before, after = result
            changes.append(Change(
                feed_id=feed_id, symbol=symbol, location=location,
                field="allowedPublisherIds", before=before, after=after,
            ))
            warn = _check_at_floor(feed_id, symbol, location, after, min_pub)
            if warn is not None:
                warnings.append(warn)

        # session=NONE: warn if publisher still in any session list
        if self.session == "NONE":
            for name in SESSION_NAMES:
                sess = get_session(feed, name)
                if sess and self.publisher_id in sess.get("allowedPublisherIds", []):
                    warnings.append(Warning(
                        feed_id=feed_id, symbol=symbol,
                        message=(
                            f"feed {feed_id}: publisher {self.publisher_id} "
                            f"still in session {name} but not in top-level roster"
                        ),
                    ))
                    break

        return changes, warnings
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_ops.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
pre-commit run --files tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): RemovePublisher op with at-floor warnings"
```

---

## Task 11: Operation — `SetMinPublishers`

**Files:**

- Modify: `tools/edit-config/lib/config_ops.py`
- Modify: `tools/edit-config/tests/test_config_ops.py`

Per spec: default scope mirrors `AddPublisher` (top-level for non-equity; top-level + REGULAR for equity). Hard error if `value > len(allowed)`. Warning if `value >= len(allowed)` (zero headroom). Warning if `value == 1` on a STABLE feed.

- [ ] **Step 1: Write failing tests**

Append to `test_config_ops.py`:

```python
from lib.config_ops import SetMinPublishers


class TestSetMinPublishers:
    def test_default_on_non_equity_writes_top_level(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=2)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2
        assert len(changes) == 1
        assert changes[0].location == "top_level"
        assert changes[0].field == "minPublishers"
        assert changes[0].after == 2

    def test_default_on_equity_writes_top_and_regular(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=4)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert get_session(feed, "REGULAR")["minPublishers"] == 4
        assert get_session(feed, "PRE_MARKET")["minPublishers"] == 2  # untouched
        locs = sorted(c.location for c in changes)
        assert locs == ["REGULAR", "top_level"]

    def test_explicit_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=3, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert get_session(feed, "PRE_MARKET")["minPublishers"] == 3
        assert feed["minPublishers"] == 1  # untouched
        assert len(changes) == 1
        assert changes[0].location == "PRE_MARKET"

    def test_hard_error_when_value_exceeds_count(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has 3 publishers, set min=5 -> unsatisfiable
        op = SetMinPublishers(value=5, session="OVER_NIGHT")
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_warning_at_floor(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has 3 publishers, set min=3 -> at-floor warning
        op = SetMinPublishers(value=3, session="OVER_NIGHT")
        changes, warns = op.apply(feed)
        assert any("headroom" in w.message.lower() for w in warns)

    def test_warning_when_one_on_stable(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=1)
        changes, warns = op.apply(feed)
        assert any("STABLE" in w.message and "1" in w.message for w in warns)

    def test_noop_when_unchanged(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=3)  # already 3
        changes, _ = op.apply(feed)
        assert changes == []

    def test_session_none_only_top_level(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=4, session="NONE")
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert get_session(feed, "REGULAR")["minPublishers"] == 3  # untouched
        assert len(changes) == 1
        assert changes[0].location == "top_level"
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_ops.py::TestSetMinPublishers -v
```

Expected: import error.

- [ ] **Step 3: Implement `SetMinPublishers`**

Append to `lib/config_ops.py`:

```python
def _resolve_min_pub_targets(
    feed: dict, session: str | None,
) -> list[tuple[str, dict, str]]:
    """Return list of (location, container, key) tuples.

    `container` is the dict that holds the field; `key` is "minPublishers".
    Used by SetMinPublishers and BumpMinPublishers.
    """
    feed_id = feed["feedId"]
    targets: list[tuple[str, dict, str]] = []

    if session is None:
        targets.append(("top_level", feed, "minPublishers"))
        if has_session_publishers(feed):
            regular = get_session(feed, "REGULAR")
            if regular is not None:
                targets.append(("REGULAR", regular, "minPublishers"))
    elif session == "NONE":
        targets.append(("top_level", feed, "minPublishers"))
    elif session == "ALL":
        if not has_session_publishers(feed):
            raise OpError(
                f"feed {feed_id}: session=ALL requires per-session lists"
            )
        targets.append(("top_level", feed, "minPublishers"))
        for name in SESSION_NAMES:
            sess = get_session(feed, name)
            if sess and "allowedPublisherIds" in sess:
                targets.append((name, sess, "minPublishers"))
    elif session in SESSION_NAMES:
        sess = get_session(feed, session)
        if sess is None or "allowedPublisherIds" not in sess:
            raise OpError(
                f"feed {feed_id}: session {session!r} does not exist on this feed"
            )
        targets.append((session, sess, "minPublishers"))
    else:
        raise OpError(f"unknown session value: {session!r}")

    return targets


def _list_for_target(feed: dict, location: str) -> list[int]:
    if location == "top_level":
        return feed.get("allowedPublisherIds", [])
    sess = get_session(feed, location)
    return sess.get("allowedPublisherIds", []) if sess else []


@dataclass
class SetMinPublishers:
    value: int
    session: str | None = None

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        state = feed.get("state", "")

        if self.value < 1:
            raise OpError(f"minPublishers must be >= 1; got {self.value}")

        targets = _resolve_min_pub_targets(feed, self.session)

        for location, container, key in targets:
            allowed = _list_for_target(feed, location)
            if self.value > len(allowed):
                raise OpError(
                    f"feed {feed_id} {location}: minPublishers={self.value} "
                    f"exceeds publisher count {len(allowed)} — unsatisfiable"
                )
            old = container.get(key)
            if old == self.value:
                continue
            container[key] = self.value
            changes.append(Change(
                feed_id=feed_id, symbol=symbol, location=location,
                field="minPublishers", before=old, after=self.value,
            ))
            if self.value >= len(allowed):
                warnings.append(Warning(
                    feed_id=feed_id, symbol=symbol,
                    message=(
                        f"feed {feed_id} {location}: minPublishers={self.value} "
                        f"with {len(allowed)} publishers — no headroom"
                    ),
                ))
            if self.value == 1 and state == "STABLE":
                warnings.append(Warning(
                    feed_id=feed_id, symbol=symbol,
                    message=(
                        f"feed {feed_id} {location}: minPublishers=1 on STABLE feed"
                    ),
                ))

        return changes, warnings
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_ops.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
pre-commit run --files tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): SetMinPublishers op"
```

---

## Task 12: Operation — `BumpMinPublishers`

**Files:**

- Modify: `tools/edit-config/lib/config_ops.py`
- Modify: `tools/edit-config/tests/test_config_ops.py`

Per spec: same defaults and warnings as `SetMinPublishers`. Adds a signed `delta`. Result clamped at floor of 1.

- [ ] **Step 1: Write failing tests**

Append to `test_config_ops.py`:

```python
from lib.config_ops import BumpMinPublishers


class TestBumpMinPublishers:
    def test_bump_up(self, feeds):
        feed = feed_by_id(feeds, 1)  # min=3
        op = BumpMinPublishers(delta=+1)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert changes[0].before == 3 and changes[0].after == 4

    def test_bump_down(self, feeds):
        feed = feed_by_id(feeds, 1)  # min=3
        op = BumpMinPublishers(delta=-1)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2

    def test_clamped_at_one(self, feeds):
        feed = feed_by_id(feeds, 6000)  # min=1
        op = BumpMinPublishers(delta=-5)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 1
        assert changes == []  # NOOP since value didn't change

    def test_zero_delta_is_noop(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = BumpMinPublishers(delta=0)
        changes, _ = op.apply(feed)
        assert changes == []

    def test_hard_error_when_exceeding_count(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT min=2, count=3. Bump +2 -> 4 -> exceeds.
        op = BumpMinPublishers(delta=+2, session="OVER_NIGHT")
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_ops.py::TestBumpMinPublishers -v
```

- [ ] **Step 3: Implement `BumpMinPublishers`**

Append to `lib/config_ops.py`:

```python
@dataclass
class BumpMinPublishers:
    delta: int
    session: str | None = None

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        state = feed.get("state", "")

        targets = _resolve_min_pub_targets(feed, self.session)

        for location, container, key in targets:
            allowed = _list_for_target(feed, location)
            old = container.get(key, 0)
            new = max(1, old + self.delta)
            if new > len(allowed):
                raise OpError(
                    f"feed {feed_id} {location}: bumped minPublishers={new} "
                    f"exceeds publisher count {len(allowed)} — unsatisfiable"
                )
            if new == old:
                continue
            container[key] = new
            changes.append(Change(
                feed_id=feed_id, symbol=symbol, location=location,
                field="minPublishers", before=old, after=new,
            ))
            if new >= len(allowed):
                warnings.append(Warning(
                    feed_id=feed_id, symbol=symbol,
                    message=(
                        f"feed {feed_id} {location}: minPublishers={new} "
                        f"with {len(allowed)} publishers — no headroom"
                    ),
                ))
            if new == 1 and state == "STABLE":
                warnings.append(Warning(
                    feed_id=feed_id, symbol=symbol,
                    message=(
                        f"feed {feed_id} {location}: minPublishers=1 on STABLE feed"
                    ),
                ))

        return changes, warnings
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_ops.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
pre-commit run --files tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): BumpMinPublishers op"
```

---

## Task 13: Operation — `SetState` with regression warnings

**Files:**

- Modify: `tools/edit-config/lib/config_ops.py`
- Modify: `tools/edit-config/tests/test_config_ops.py`

Per spec: state is top-level only. Soft guardrails (warn, don't block): `STABLE→COMING_SOON`, `STABLE→INACTIVE`, `INACTIVE→STABLE`. NOOP if already at target.

- [ ] **Step 1: Write failing tests**

Append to `test_config_ops.py`:

```python
from lib.config_ops import SetState


VALID_STATES = ("STABLE", "COMING_SOON", "INACTIVE")


class TestSetState:
    def test_promote_coming_soon_to_stable(self, feeds):
        feed = feed_by_id(feeds, 5000)
        op = SetState(value="STABLE")
        changes, warns = op.apply(feed)
        assert feed["state"] == "STABLE"
        assert len(changes) == 1
        assert changes[0].field == "state"
        assert changes[0].before == "COMING_SOON" and changes[0].after == "STABLE"
        # COMING_SOON -> STABLE is the natural progression; no warning
        assert warns == []

    def test_regression_stable_to_coming_soon_warns(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetState(value="COMING_SOON")
        changes, warns = op.apply(feed)
        assert feed["state"] == "COMING_SOON"
        assert any("regression" in w.message.lower() for w in warns)

    def test_deactivation_warns(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetState(value="INACTIVE")
        changes, warns = op.apply(feed)
        assert feed["state"] == "INACTIVE"
        assert any("deactivat" in w.message.lower() for w in warns)

    def test_reactivation_warns(self, feeds):
        feed = feed_by_id(feeds, 6000)  # INACTIVE
        op = SetState(value="STABLE")
        changes, warns = op.apply(feed)
        assert feed["state"] == "STABLE"
        assert any("reactivat" in w.message.lower() for w in warns)

    def test_noop_when_already_target(self, feeds):
        feed = feed_by_id(feeds, 1)  # STABLE
        op = SetState(value="STABLE")
        changes, _ = op.apply(feed)
        assert changes == []

    def test_invalid_state_raises(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetState(value="DELETED")
        with pytest.raises(OpError, match="invalid state"):
            op.apply(feed)
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_ops.py::TestSetState -v
```

- [ ] **Step 3: Implement `SetState`**

Append to `lib/config_ops.py`:

```python
VALID_STATES = ("STABLE", "COMING_SOON", "INACTIVE")

_STATE_WARNINGS = {
    ("STABLE", "COMING_SOON"): "regression: STABLE feed downgraded to COMING_SOON",
    ("STABLE", "INACTIVE"): "deactivation of live STABLE feed",
    ("INACTIVE", "STABLE"): "reactivation of INACTIVE feed — verify intent",
}


@dataclass
class SetState:
    value: str

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        if self.value not in VALID_STATES:
            raise OpError(
                f"invalid state {self.value!r}; must be one of {VALID_STATES}"
            )

        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        old = feed.get("state")

        if old == self.value:
            return [], []

        feed["state"] = self.value
        changes = [Change(
            feed_id=feed_id, symbol=symbol, location="top_level",
            field="state", before=old, after=self.value,
        )]
        warnings: list[Warning] = []
        msg = _STATE_WARNINGS.get((old, self.value))
        if msg:
            warnings.append(Warning(
                feed_id=feed_id, symbol=symbol,
                message=f"feed {feed_id}: {msg}",
            ))
        return changes, warnings
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_ops.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
pre-commit run --files tools/edit-config/lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): SetState op with soft regression guardrails"
```

---

## Task 14: Diff renderer with custom hunk headers and truncation

**Files:**

- Create: `tools/edit-config/lib/config_diff.py`
- Create: `tools/edit-config/tests/test_config_diff.py`

Renders a list of `Change` records as a unified diff. Each change becomes one hunk with a custom header `@@ feedId 922 (Equity.US.AAPL/USD), session PRE_MARKET @@`, followed by the before/after line. Truncates at `max_hunks` (default 40) with a "(N more changed lines; rerun with --show-full-diff)" footer.

- [ ] **Step 1: Write failing tests**

Create `tools/edit-config/tests/test_config_diff.py`:

```python
import pytest

from lib.config_ops import Change
from lib.config_diff import render_diff


class TestRenderDiff:
    def test_publisher_change_renders(self):
        change = Change(
            feed_id=1000, symbol="X", location="top_level",
            field="allowedPublisherIds", before=[1, 3, 14], after=[1, 3, 14, 80],
        )
        out = render_diff([change])
        assert "@@ feedId 1000 (X) @@" in out
        assert "-" in out and "+" in out
        assert "[ 1, 3, 14 ]" in out
        assert "[ 1, 3, 14, 80 ]" in out

    def test_session_hunk_header_includes_session(self):
        change = Change(
            feed_id=922, symbol="Equity.US.AAPL/USD", location="PRE_MARKET",
            field="allowedPublisherIds", before=[1, 2, 3], after=[1, 2],
        )
        out = render_diff([change])
        assert "session PRE_MARKET" in out

    def test_int_field_renders_as_value(self):
        change = Change(
            feed_id=1, symbol="Crypto.BTC/USD", location="top_level",
            field="minPublishers", before=3, after=4,
        )
        out = render_diff([change])
        assert "minPublishers" in out
        assert '"minPublishers": 3' in out
        assert '"minPublishers": 4' in out

    def test_state_field_renders_quoted(self):
        change = Change(
            feed_id=1, symbol="X", location="top_level",
            field="state", before="STABLE", after="COMING_SOON",
        )
        out = render_diff([change])
        assert '"state": "STABLE"' in out
        assert '"state": "COMING_SOON"' in out

    def test_truncation(self):
        changes = [
            Change(
                feed_id=i, symbol=f"f{i}", location="top_level",
                field="minPublishers", before=2, after=3,
            )
            for i in range(50)
        ]
        out = render_diff(changes, max_hunks=10)
        # Only 10 hunks rendered + footer
        assert out.count("@@ feedId") == 10
        assert "40 more" in out

    def test_no_truncation_when_under_limit(self):
        changes = [
            Change(
                feed_id=i, symbol=f"f{i}", location="top_level",
                field="minPublishers", before=2, after=3,
            )
            for i in range(5)
        ]
        out = render_diff(changes, max_hunks=10)
        assert out.count("@@ feedId") == 5
        assert "more" not in out

    def test_show_full_diff_disables_truncation(self):
        changes = [
            Change(
                feed_id=i, symbol=f"f{i}", location="top_level",
                field="minPublishers", before=2, after=3,
            )
            for i in range(50)
        ]
        out = render_diff(changes, max_hunks=10, show_full=True)
        assert out.count("@@ feedId") == 50

    def test_empty_changes(self):
        out = render_diff([])
        assert out.strip() == "(no changes)"
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_diff.py -v
```

Expected: all fail.

- [ ] **Step 3: Implement `render_diff`**

Create `tools/edit-config/lib/config_diff.py`:

```python
"""Render a list of Change records as a unified-style diff.

Each Change becomes one hunk with a custom header that names the
feedId, symbol, and (optionally) session — far more useful than raw
line numbers in a 3 MB file.
"""

from lib.config_ops import Change


def _format_publisher_list(ids: list[int]) -> str:
    return "[ " + ", ".join(str(i) for i in ids) + " ]" if ids else "[ ]"


def _hunk_header(change: Change) -> str:
    base = f"@@ feedId {change.feed_id} ({change.symbol})"
    if change.location != "top_level":
        base += f", session {change.location}"
    return base + " @@"


def _value_lines(change: Change) -> tuple[str, str]:
    """Return (before_line, after_line) formatted as JSON-ish text."""
    if change.field == "allowedPublisherIds":
        b = f'      "allowedPublisherIds": {_format_publisher_list(change.before)},'
        a = f'      "allowedPublisherIds": {_format_publisher_list(change.after)},'
    elif change.field == "minPublishers":
        b = f'      "minPublishers": {change.before},'
        a = f'      "minPublishers": {change.after},'
    elif change.field == "state":
        b = f'      "state": "{change.before}",'
        a = f'      "state": "{change.after}",'
    else:
        b = f'      "{change.field}": {change.before!r},'
        a = f'      "{change.field}": {change.after!r},'
    return b, a


def render_diff(
    changes: list[Change], max_hunks: int = 40, show_full: bool = False,
) -> str:
    """Render changes as a unified diff with custom hunk headers."""
    if not changes:
        return "(no changes)\n"

    lines: list[str] = ["--- after.json", "+++ after.json (proposed)"]
    rendered = changes if show_full else changes[:max_hunks]
    for change in rendered:
        lines.append(_hunk_header(change))
        b, a = _value_lines(change)
        lines.append(f"-{b}")
        lines.append(f"+{a}")

    if not show_full and len(changes) > max_hunks:
        remaining = len(changes) - max_hunks
        lines.append(f"... ({remaining} more changed lines; rerun with --show-full-diff)")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_diff.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_diff.py tools/edit-config/tests/test_config_diff.py
pre-commit run --files tools/edit-config/lib/config_diff.py tools/edit-config/tests/test_config_diff.py
git commit -m "feat(edit-config): diff renderer with feedId/symbol hunk headers"
```

---

## Task 15: Filter resolution — match feeds against `FilterSet`

**Files:**

- Modify: `tools/edit-config/lib/config_editor.py` (create)
- Create: `tools/edit-config/tests/test_config_editor.py`

Implements `FilterSet` dataclass and `resolve_targets(filters, feeds) -> list[dict]`. AND-combined filters; ≥1 filter required. Symbol pattern uses `fnmatch`. State filter accepts list. Hard error on zero match (raised by orchestrator, not here — `resolve_targets` returns the list as-is).

- [ ] **Step 1: Write failing tests**

Create `tools/edit-config/tests/test_config_editor.py`:

```python
import json
from pathlib import Path

import pytest

from lib.config_editor import FilterSet, resolve_targets


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_sample.json"


@pytest.fixture
def feeds():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["feeds"]


class TestFilterSet:
    def test_at_least_one_filter_required(self):
        with pytest.raises(ValueError, match="at least one"):
            FilterSet().validate()

    def test_feed_ids_alone_valid(self):
        FilterSet(feed_ids={1, 2}).validate()  # no raise

    def test_state_alone_valid(self):
        FilterSet(states={"STABLE"}).validate()


class TestResolveTargets:
    def test_by_feed_id(self, feeds):
        f = FilterSet(feed_ids={1})
        result = resolve_targets(f, feeds)
        assert [x["feedId"] for x in result] == [1]

    def test_by_feed_id_set(self, feeds):
        f = FilterSet(feed_ids={1, 100, 922})
        result = resolve_targets(f, feeds)
        assert sorted(x["feedId"] for x in result) == [1, 100, 922]

    def test_by_state_single(self, feeds):
        f = FilterSet(states={"INACTIVE"})
        result = resolve_targets(f, feeds)
        assert [x["feedId"] for x in result] == [6000]

    def test_by_state_list(self, feeds):
        f = FilterSet(states={"STABLE", "COMING_SOON"})
        result = resolve_targets(f, feeds)
        ids = sorted(x["feedId"] for x in result)
        assert ids == [1, 100, 922, 1023, 5000]

    def test_by_asset_class(self, feeds):
        f = FilterSet(asset_class="fx")
        result = resolve_targets(f, feeds)
        assert sorted(x["feedId"] for x in result) == [100, 6000]

    def test_by_symbol_pattern(self, feeds):
        f = FilterSet(symbol_pattern="Equity.US.*")
        result = resolve_targets(f, feeds)
        assert sorted(x["feedId"] for x in result) == [922, 1023]

    def test_and_combination(self, feeds):
        f = FilterSet(asset_class="equity", states={"STABLE"})
        result = resolve_targets(f, feeds)
        assert sorted(x["feedId"] for x in result) == [922, 1023]

    def test_empty_match_returns_empty(self, feeds):
        f = FilterSet(feed_ids={99999})
        assert resolve_targets(f, feeds) == []

    def test_feed_id_intersected_with_state(self, feeds):
        # feed 922 is STABLE; 5000 is COMING_SOON. Filter for both IDs but
        # only STABLE state -> should only get 922.
        f = FilterSet(feed_ids={922, 5000}, states={"STABLE"})
        result = resolve_targets(f, feeds)
        assert [x["feedId"] for x in result] == [922]
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

Expected: import error.

- [ ] **Step 3: Implement `FilterSet` and `resolve_targets`**

Create `tools/edit-config/lib/config_editor.py`:

```python
"""Orchestrator: parse spec, resolve targets, simulate, apply."""

import fnmatch
from dataclasses import dataclass, field


@dataclass
class FilterSet:
    feed_ids: set[int] | None = None
    symbol_pattern: str | None = None
    asset_class: str | None = None
    states: set[str] | None = None  # plural — supports YAML list

    def validate(self) -> None:
        if not any((self.feed_ids, self.symbol_pattern, self.asset_class, self.states)):
            raise ValueError(
                "at least one targeting filter is required "
                "(feed_id/feed-ids-from, symbol_pattern, asset_class, or state)"
            )

    def matches(self, feed: dict) -> bool:
        if self.feed_ids is not None and feed["feedId"] not in self.feed_ids:
            return False
        if self.symbol_pattern is not None:
            symbol = feed.get("symbol", "")
            if not fnmatch.fnmatchcase(symbol, self.symbol_pattern):
                return False
        if self.asset_class is not None:
            asset = feed.get("metadata", {}).get("asset_type", "")
            if asset != self.asset_class:
                return False
        if self.states is not None and feed.get("state") not in self.states:
            return False
        return True


def resolve_targets(filters: FilterSet, feeds: list[dict]) -> list[dict]:
    """Return the subset of feeds matching all filters (AND)."""
    return [f for f in feeds if filters.matches(f)]
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
pre-commit run --files tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): FilterSet and target resolution"
```

---

## Task 16: CLI argparse → single `PlannedOp`

**Files:**

- Modify: `tools/edit-config/lib/config_editor.py`
- Modify: `tools/edit-config/tests/test_config_editor.py`

Single-op invocation: exactly one of `--add-publisher`, `--remove-publisher`, `--set-min-publishers`, `--bump-min-publishers`, `--set-state` (or `--from-spec`, handled in next task). At least one targeting flag. Optional `--session`.

- [ ] **Step 1: Write failing tests**

Append to `test_config_editor.py`:

```python
import argparse

from lib.config_editor import PlannedOp, build_op_from_args
from lib.config_ops import (
    AddPublisher, RemovePublisher, SetMinPublishers, BumpMinPublishers, SetState,
)


def make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        add_publisher=None, remove_publisher=None,
        set_min_publishers=None, bump_min_publishers=None,
        set_state=None, from_spec=None,
        feed_id=None, feed_ids_from=None,
        symbol_pattern=None, asset_class=None, state=None,
        session=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestBuildOpFromArgs:
    def test_add_publisher(self):
        args = make_args(add_publisher=80, feed_id="100-105", session="REGULAR")
        ops = build_op_from_args(args)
        assert len(ops) == 1
        op, filters = ops[0].op, ops[0].filters
        assert isinstance(op, AddPublisher)
        assert op.publisher_id == 80
        assert op.session == "REGULAR"
        assert filters.feed_ids == {100, 101, 102, 103, 104, 105}

    def test_remove_publisher_default_session(self):
        args = make_args(remove_publisher=22, feed_id="922")
        ops = build_op_from_args(args)
        assert isinstance(ops[0].op, RemovePublisher)
        assert ops[0].op.session is None

    def test_set_min_publishers(self):
        args = make_args(set_min_publishers=3, feed_id="922", session="REGULAR")
        ops = build_op_from_args(args)
        assert isinstance(ops[0].op, SetMinPublishers)
        assert ops[0].op.value == 3

    def test_bump_min_publishers_signed(self):
        args = make_args(bump_min_publishers="+1", feed_id="922")
        ops = build_op_from_args(args)
        assert isinstance(ops[0].op, BumpMinPublishers)
        assert ops[0].op.delta == 1

        args2 = make_args(bump_min_publishers="-2", feed_id="922")
        ops2 = build_op_from_args(args2)
        assert ops2[0].op.delta == -2

    def test_set_state(self):
        args = make_args(set_state="COMING_SOON", feed_id="500,501")
        ops = build_op_from_args(args)
        assert isinstance(ops[0].op, SetState)
        assert ops[0].op.value == "COMING_SOON"

    def test_no_op_flag_raises(self):
        args = make_args(feed_id="1")
        with pytest.raises(ValueError, match="no operation"):
            build_op_from_args(args)

    def test_multiple_op_flags_raises(self):
        args = make_args(add_publisher=1, remove_publisher=2, feed_id="1")
        with pytest.raises(ValueError, match="exactly one"):
            build_op_from_args(args)

    def test_no_targeting_raises(self):
        args = make_args(add_publisher=80)
        with pytest.raises(ValueError, match="at least one"):
            build_op_from_args(args)

    def test_state_filter_value(self):
        args = make_args(add_publisher=80, asset_class="equity", state="STABLE")
        ops = build_op_from_args(args)
        assert ops[0].filters.states == {"STABLE"}

    def test_feed_id_with_ranges(self):
        args = make_args(add_publisher=80, feed_id="100-200,205,208,3530-3540")
        ops = build_op_from_args(args)
        ids = ops[0].filters.feed_ids
        assert 100 in ids and 200 in ids and 205 in ids and 3540 in ids
        assert 201 not in ids and 209 not in ids

    def test_feed_ids_from_file(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("1,2,3\n100-102", encoding="utf-8")
        args = make_args(add_publisher=80, feed_ids_from=str(f))
        ops = build_op_from_args(args)
        assert ops[0].filters.feed_ids == {1, 2, 3, 100, 101, 102}

    def test_feed_id_and_feed_ids_from_unioned(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("100", encoding="utf-8")
        args = make_args(add_publisher=80, feed_id="1,2", feed_ids_from=str(f))
        ops = build_op_from_args(args)
        assert ops[0].filters.feed_ids == {1, 2, 100}
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

- [ ] **Step 3: Implement `PlannedOp` and `build_op_from_args`**

Append to `lib/config_editor.py`:

```python
from typing import Any

from lib.config_ops import (
    AddPublisher, RemovePublisher, SetMinPublishers, BumpMinPublishers, SetState,
)
from lib.config_selector import parse_selector_text, read_selector_file


@dataclass
class PlannedOp:
    op: Any  # one of the operation classes
    filters: FilterSet


_OP_FLAGS = (
    "add_publisher", "remove_publisher", "set_min_publishers",
    "bump_min_publishers", "set_state",
)


def _build_filters_from_args(args) -> FilterSet:
    feed_ids: set[int] | None = None
    if args.feed_id:
        feed_ids = parse_selector_text(args.feed_id)
    if args.feed_ids_from:
        from_file = read_selector_file(args.feed_ids_from)
        feed_ids = (feed_ids or set()) | from_file
    states = {args.state} if args.state else None
    f = FilterSet(
        feed_ids=feed_ids,
        symbol_pattern=args.symbol_pattern,
        asset_class=args.asset_class,
        states=states,
    )
    f.validate()
    return f


def _parse_signed_int(s: str) -> int:
    if not s:
        raise ValueError(f"empty bump value")
    if s[0] not in "+-" and not s.isdigit():
        raise ValueError(f"bump must be signed integer (+1 / -2); got {s!r}")
    return int(s)


def build_op_from_args(args) -> list[PlannedOp]:
    """Build a single-element PlannedOp list from argparse Namespace.

    Raises ValueError on missing/multiple operation flags, missing
    targeting, etc.
    """
    selected = [name for name in _OP_FLAGS if getattr(args, name) is not None]
    if not selected:
        raise ValueError("no operation specified (use one of --add-publisher, "
                         "--remove-publisher, --set-min-publishers, "
                         "--bump-min-publishers, --set-state)")
    if len(selected) > 1:
        raise ValueError(f"exactly one operation flag allowed; got {selected}")

    name = selected[0]
    filters = _build_filters_from_args(args)

    if name == "add_publisher":
        op = AddPublisher(publisher_id=args.add_publisher, session=args.session)
    elif name == "remove_publisher":
        op = RemovePublisher(publisher_id=args.remove_publisher, session=args.session)
    elif name == "set_min_publishers":
        op = SetMinPublishers(value=args.set_min_publishers, session=args.session)
    elif name == "bump_min_publishers":
        delta = _parse_signed_int(args.bump_min_publishers)
        op = BumpMinPublishers(delta=delta, session=args.session)
    elif name == "set_state":
        op = SetState(value=args.set_state)
    else:
        raise AssertionError(f"unhandled op {name}")

    return [PlannedOp(op=op, filters=filters)]
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
pre-commit run --files tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): build PlannedOp from CLI flags"
```

---

## Task 17: YAML spec parser → list of `PlannedOp`

**Files:**

- Modify: `tools/edit-config/lib/config_editor.py`
- Modify: `tools/edit-config/tests/test_config_editor.py`
- Create: `tools/edit-config/tests/fixtures/edits_basic.yaml`
- Create: `tools/edit-config/tests/fixtures/edits_invalid.yaml`

Parse YAML; build a list of `PlannedOp`. Reject unknown keys per op. Range strings `"A-B"` allowed in `feed_id` lists. Required fields per op type.

- [ ] **Step 1: Author fixture YAML files**

Create `tools/edit-config/tests/fixtures/edits_basic.yaml`:

```yaml
version: 1
operations:
  - op: add_publisher
    publisher_id: 80
    feed_id: "100-105"

  - op: remove_publisher
    publisher_id: 22
    feed_id: 922
    session: PRE_MARKET

  - op: set_min_publishers
    value: 3
    asset_class: equity
    state: STABLE
    session: REGULAR

  - op: bump_min_publishers
    delta: 1
    feed_id: [1023]

  - op: set_state
    value: COMING_SOON
    feed_id: [1, 100]

  - op: add_publisher
    publisher_id: 90
    feed_id: [1, "100-101", 5000]
    session: NONE
```

Create `tools/edit-config/tests/fixtures/edits_invalid.yaml`:

```yaml
version: 1
operations:
  - op: add_publisher
    publisher_id: 80
    feed_id: 1
    session: REGULAR
    bogus_key: hello # unknown key -> reject
```

- [ ] **Step 2: Write failing tests**

Append to `test_config_editor.py`:

```python
from lib.config_editor import parse_yaml_spec


YAML_BASIC = Path(__file__).parent / "fixtures" / "edits_basic.yaml"
YAML_INVALID = Path(__file__).parent / "fixtures" / "edits_invalid.yaml"


class TestParseYamlSpec:
    def test_parses_all_op_types(self):
        ops = parse_yaml_spec(str(YAML_BASIC))
        assert len(ops) == 6
        kinds = [type(p.op).__name__ for p in ops]
        assert kinds == [
            "AddPublisher", "RemovePublisher", "SetMinPublishers",
            "BumpMinPublishers", "SetState", "AddPublisher",
        ]

    def test_feed_id_range_string(self):
        ops = parse_yaml_spec(str(YAML_BASIC))
        # First op uses "100-105"
        assert ops[0].filters.feed_ids == {100, 101, 102, 103, 104, 105}

    def test_feed_id_mixed_list(self):
        ops = parse_yaml_spec(str(YAML_BASIC))
        # Last op uses [1, "100-101", 5000]
        assert ops[-1].filters.feed_ids == {1, 100, 101, 5000}

    def test_state_list_in_yaml(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n"
            "  - op: add_publisher\n"
            "    publisher_id: 1\n"
            "    feed_id: 1\n"
            "    state: [STABLE, COMING_SOON]\n",
            encoding="utf-8",
        )
        ops = parse_yaml_spec(str(spec))
        assert ops[0].filters.states == {"STABLE", "COMING_SOON"}

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match="unknown key"):
            parse_yaml_spec(str(YAML_INVALID))

    def test_missing_op_field_rejected(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n  - publisher_id: 1\n    feed_id: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing.*op"):
            parse_yaml_spec(str(spec))

    def test_unknown_op_rejected(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n  - op: drop_feed\n    feed_id: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unknown op"):
            parse_yaml_spec(str(spec))

    def test_version_above_1_fails(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "version: 2\noperations:\n"
            "  - op: add_publisher\n    publisher_id: 1\n    feed_id: 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="version"):
            parse_yaml_spec(str(spec))

    def test_no_operations_key_fails(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("foo: bar\n", encoding="utf-8")
        with pytest.raises(ValueError, match="operations"):
            parse_yaml_spec(str(spec))
```

- [ ] **Step 3: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_editor.py::TestParseYamlSpec -v
```

- [ ] **Step 4: Implement `parse_yaml_spec`**

Append to `lib/config_editor.py`:

```python
import yaml


_OP_REQUIRED_FIELDS = {
    "add_publisher": {"publisher_id"},
    "remove_publisher": {"publisher_id"},
    "set_min_publishers": {"value"},
    "bump_min_publishers": {"delta"},
    "set_state": {"value"},
}

_TARGETING_KEYS = {
    "feed_id", "symbol_pattern", "asset_class", "state",
}

_SCOPE_KEYS = {"session"}


def _parse_feed_id_field(value) -> set[int]:
    """Accept int, range-string, or list of int/range-strings."""
    if isinstance(value, int):
        return {value}
    if isinstance(value, str):
        return parse_selector_text(value)
    if isinstance(value, list):
        ids: set[int] = set()
        for item in value:
            if isinstance(item, int):
                ids.add(item)
            elif isinstance(item, str):
                ids.update(parse_selector_text(item))
            else:
                raise ValueError(
                    f"feed_id list entries must be int or range-string; got {item!r}"
                )
        return ids
    raise ValueError(f"feed_id must be int, range-string, or list; got {type(value).__name__}")


def _filters_from_yaml_entry(entry: dict) -> FilterSet:
    feed_ids: set[int] | None = None
    if "feed_id" in entry:
        feed_ids = _parse_feed_id_field(entry["feed_id"])
    states_raw = entry.get("state")
    if isinstance(states_raw, str):
        states = {states_raw}
    elif isinstance(states_raw, list):
        states = set(states_raw)
    elif states_raw is None:
        states = None
    else:
        raise ValueError(f"state must be string or list; got {type(states_raw).__name__}")
    f = FilterSet(
        feed_ids=feed_ids,
        symbol_pattern=entry.get("symbol_pattern"),
        asset_class=entry.get("asset_class"),
        states=states,
    )
    f.validate()
    return f


def _validate_keys(entry: dict, op_name: str) -> None:
    allowed = {"op"} | _TARGETING_KEYS | _SCOPE_KEYS | _OP_REQUIRED_FIELDS[op_name]
    extras = set(entry.keys()) - allowed
    if extras:
        raise ValueError(f"unknown key(s) in op {op_name!r}: {sorted(extras)}")


def _build_op_from_yaml_entry(entry: dict):
    op_name = entry["op"]
    if op_name not in _OP_REQUIRED_FIELDS:
        raise ValueError(f"unknown op {op_name!r}")
    missing = _OP_REQUIRED_FIELDS[op_name] - set(entry.keys())
    if missing:
        raise ValueError(f"op {op_name!r} missing required field(s): {sorted(missing)}")
    _validate_keys(entry, op_name)

    session = entry.get("session")

    if op_name == "add_publisher":
        return AddPublisher(publisher_id=entry["publisher_id"], session=session)
    if op_name == "remove_publisher":
        return RemovePublisher(publisher_id=entry["publisher_id"], session=session)
    if op_name == "set_min_publishers":
        return SetMinPublishers(value=entry["value"], session=session)
    if op_name == "bump_min_publishers":
        return BumpMinPublishers(delta=entry["delta"], session=session)
    if op_name == "set_state":
        return SetState(value=entry["value"])
    raise AssertionError(f"unhandled op {op_name}")


def parse_yaml_spec(path: str) -> list[PlannedOp]:
    """Load a YAML spec file and produce a list of PlannedOp."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping")
    version = data.get("version", 1)
    if not isinstance(version, int) or version > 1:
        raise ValueError(f"unsupported spec version {version!r}")
    if "operations" not in data or not isinstance(data["operations"], list):
        raise ValueError("YAML spec must contain a top-level `operations` list")

    planned: list[PlannedOp] = []
    for i, entry in enumerate(data["operations"]):
        if not isinstance(entry, dict):
            raise ValueError(f"operation #{i + 1}: must be a mapping")
        if "op" not in entry:
            raise ValueError(f"operation #{i + 1}: missing 'op' field")
        op = _build_op_from_yaml_entry(entry)
        filters = _filters_from_yaml_entry(entry)
        planned.append(PlannedOp(op=op, filters=filters))

    return planned
```

- [ ] **Step 5: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

- [ ] **Step 6: Commit**

```bash
git add tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py tools/edit-config/tests/fixtures/edits_basic.yaml tools/edit-config/tests/fixtures/edits_invalid.yaml
pre-commit run --files tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py tools/edit-config/tests/fixtures/edits_basic.yaml tools/edit-config/tests/fixtures/edits_invalid.yaml
git commit -m "feat(edit-config): YAML spec parser with strict key checking"
```

---

## Task 18: Orchestrator — simulate plan against parsed config

**Files:**

- Modify: `tools/edit-config/lib/config_editor.py`
- Modify: `tools/edit-config/tests/test_config_editor.py`

`SimulationResult` collects all changes, warnings, and errors. Simulation deep-copies the parsed config so subsequent ops see prior ops' effects. Hard error on zero match for any op.

- [ ] **Step 1: Write failing tests**

Append to `test_config_editor.py`:

```python
from copy import deepcopy

from lib.config_editor import (
    SimulationResult, simulate_plan,
)
from lib.config_ops import AddPublisher, SetState


class TestSimulatePlan:
    def test_single_op_succeeds(self, feeds):
        plan = [PlannedOp(
            op=AddPublisher(publisher_id=80),
            filters=FilterSet(feed_ids={1}),
        )]
        result = simulate_plan(plan, feeds)
        assert isinstance(result, SimulationResult)
        assert result.errors == []
        assert len(result.changes) == 1
        assert result.changes[0].after == [1, 3, 7, 11, 80]

    def test_zero_match_is_error(self, feeds):
        plan = [PlannedOp(
            op=AddPublisher(publisher_id=80),
            filters=FilterSet(feed_ids={99999}),
        )]
        result = simulate_plan(plan, feeds)
        assert result.changes == []
        assert any("zero" in e.lower() or "no feeds" in e.lower() for e in result.errors)

    def test_op_error_recorded(self, feeds):
        # Add to PRE_MARKET on a crypto feed -> OpError
        plan = [PlannedOp(
            op=AddPublisher(publisher_id=80, session="PRE_MARKET"),
            filters=FilterSet(feed_ids={1}),
        )]
        result = simulate_plan(plan, feeds)
        assert any("PRE_MARKET" in e for e in result.errors)

    def test_inter_op_visibility(self, feeds):
        # Op 1: add publisher 80 to feed 1.
        # Op 2: add publisher 80 again -> should NOOP because op 1 already added it.
        plan = [
            PlannedOp(op=AddPublisher(publisher_id=80), filters=FilterSet(feed_ids={1})),
            PlannedOp(op=AddPublisher(publisher_id=80), filters=FilterSet(feed_ids={1})),
        ]
        result = simulate_plan(plan, feeds)
        assert len(result.changes) == 1  # only op 1 produced a change

    def test_does_not_mutate_input_feeds(self, feeds):
        original = deepcopy(feeds)
        plan = [PlannedOp(
            op=AddPublisher(publisher_id=80),
            filters=FilterSet(feed_ids={1}),
        )]
        simulate_plan(plan, feeds)
        assert feeds == original  # no mutation of caller's data

    def test_warnings_collected(self, feeds):
        plan = [PlannedOp(
            op=SetState(value="INACTIVE"),
            filters=FilterSet(feed_ids={1}),
        )]
        result = simulate_plan(plan, feeds)
        assert any("deactivat" in w.message.lower() for w in result.warnings)
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_editor.py::TestSimulatePlan -v
```

- [ ] **Step 3: Implement `SimulationResult` and `simulate_plan`**

Append to `lib/config_editor.py`:

```python
from copy import deepcopy

from lib.config_ops import Change, OpError, Warning


@dataclass
class SimulationResult:
    plan: list["PlannedOp"]
    matched_counts: list[int]  # one per op
    changes: list[Change]
    warnings: list[Warning]
    errors: list[str]
    simulated_feeds: list[dict]  # working copy after all ops; useful for tests


def simulate_plan(plan: list[PlannedOp], feeds: list[dict]) -> SimulationResult:
    """Apply each op against a working copy and collect results.

    Operations are applied in spec order; later ops see earlier ops'
    effects. Errors do not stop simulation — they're collected so the
    user sees every problem in one pass.
    """
    work = deepcopy(feeds)
    all_changes: list[Change] = []
    all_warnings: list[Warning] = []
    all_errors: list[str] = []
    matched_counts: list[int] = []

    for idx, planned in enumerate(plan, start=1):
        targets = resolve_targets(planned.filters, work)
        matched_counts.append(len(targets))
        if not targets:
            all_errors.append(
                f"operation #{idx} ({type(planned.op).__name__}): "
                f"no feeds matched the filter"
            )
            continue
        for feed in targets:
            try:
                changes, warns = planned.op.apply(feed)
            except OpError as e:
                all_errors.append(f"operation #{idx} feed {feed['feedId']}: {e}")
                continue
            all_changes.extend(changes)
            all_warnings.extend(warns)

    return SimulationResult(
        plan=plan,
        matched_counts=matched_counts,
        changes=all_changes,
        warnings=all_warnings,
        errors=all_errors,
        simulated_feeds=work,
    )
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
pre-commit run --files tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): orchestrator simulate_plan with inter-op visibility"
```

---

## Task 19: Orchestrator — apply changes to raw text

**Files:**

- Modify: `tools/edit-config/lib/config_editor.py`
- Modify: `tools/edit-config/tests/test_config_editor.py`

`apply_changes(raw, changes) -> str` walks each `Change` and rewrites the raw text byte-spans using `config_text_surgery` locators. To avoid offset drift, group by feed and apply the entire feed block's edits at once: locate the feed block once, perform every change for that feed inside that local block, then splice the rewritten block back into the full text.

- [ ] **Step 1: Write failing tests**

Append to `test_config_editor.py`:

```python
from lib.config_editor import apply_changes
from lib.config_ops import Change


class TestApplyChanges:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_publisher_top_level_change(self):
        change = Change(
            feed_id=1, symbol="Crypto.BTC/USD", location="top_level",
            field="allowedPublisherIds", before=[1, 3, 7, 11], after=[1, 3, 7, 11, 80],
        )
        new_raw = apply_changes(self.raw, [change])
        # Locate the feed 1 block in the result
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 1)
        assert f["allowedPublisherIds"] == [1, 3, 7, 11, 80]

    def test_publisher_session_change(self):
        change = Change(
            feed_id=922, symbol="Equity.US.AAPL/USD", location="PRE_MARKET",
            field="allowedPublisherIds",
            before=[19, 20, 22, 41, 42, 45, 55, 59, 65],
            after=[19, 20, 41, 42, 45, 55, 59, 65],
        )
        new_raw = apply_changes(self.raw, [change])
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 922)
        pre = next(s for s in f["marketSchedules"] if s["session"] == "PRE_MARKET")
        assert pre["allowedPublisherIds"] == [19, 20, 41, 42, 45, 55, 59, 65]

    def test_min_publishers_top_level(self):
        change = Change(
            feed_id=1, symbol="Crypto.BTC/USD", location="top_level",
            field="minPublishers", before=3, after=4,
        )
        new_raw = apply_changes(self.raw, [change])
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 1)
        assert f["minPublishers"] == 4

    def test_min_publishers_session(self):
        change = Change(
            feed_id=922, symbol="Equity.US.AAPL/USD", location="OVER_NIGHT",
            field="minPublishers", before=2, after=3,
        )
        new_raw = apply_changes(self.raw, [change])
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 922)
        on = next(s for s in f["marketSchedules"] if s["session"] == "OVER_NIGHT")
        assert on["minPublishers"] == 3

    def test_state_change(self):
        change = Change(
            feed_id=5000, symbol="Crypto.NEW/USD", location="top_level",
            field="state", before="COMING_SOON", after="STABLE",
        )
        new_raw = apply_changes(self.raw, [change])
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 5000)
        assert f["state"] == "STABLE"

    def test_multiple_changes_same_feed(self):
        changes = [
            Change(feed_id=922, symbol="X", location="top_level",
                   field="allowedPublisherIds",
                   before=[11, 12, 13, 14, 19, 20, 21, 22, 26, 29, 32, 35, 41, 42, 45, 48, 54, 55, 57, 59, 64, 65, 69, 71, 72, 73],
                   after=[11, 12, 13, 14, 19, 20, 21, 22, 26, 29, 32, 35, 41, 42, 45, 48, 54, 55, 57, 59, 64, 65, 69, 71, 72, 73, 80]),
            Change(feed_id=922, symbol="X", location="REGULAR",
                   field="minPublishers", before=3, after=4),
        ]
        new_raw = apply_changes(self.raw, changes)
        new_data = json.loads(new_raw)
        f = next(x for x in new_data["feeds"] if x["feedId"] == 922)
        assert 80 in f["allowedPublisherIds"]
        regular = next(s for s in f["marketSchedules"] if s["session"] == "REGULAR")
        assert regular["minPublishers"] == 4

    def test_multiple_changes_different_feeds(self):
        changes = [
            Change(feed_id=1, symbol="X", location="top_level",
                   field="minPublishers", before=3, after=2),
            Change(feed_id=100, symbol="Y", location="top_level",
                   field="minPublishers", before=3, after=4),
        ]
        new_raw = apply_changes(self.raw, changes)
        new_data = json.loads(new_raw)
        f1 = next(x for x in new_data["feeds"] if x["feedId"] == 1)
        f100 = next(x for x in new_data["feeds"] if x["feedId"] == 100)
        assert f1["minPublishers"] == 2
        assert f100["minPublishers"] == 4

    def test_empty_changes_is_identity(self):
        assert apply_changes(self.raw, []) == self.raw
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_editor.py::TestApplyChanges -v
```

- [ ] **Step 3: Implement `apply_changes`**

Append to `lib/config_editor.py`:

```python
from collections import defaultdict

from lib.config_text_surgery import (
    find_feed_block, find_session_block,
    find_publisher_array_span, find_int_field_span, find_string_field_span,
    find_matching_close,
)


def _format_publisher_list(ids: list[int]) -> str:
    if not ids:
        return "[ ]"
    return "[ " + ", ".join(str(i) for i in ids) + " ]"


def _apply_changes_to_feed_block(block: str, changes: list[Change]) -> str:
    """Apply all changes for a single feed to its raw text block.

    Strategy: collect (start, end, replacement) tuples relative to the
    feed block, sort by descending start offset, splice them in order
    so prior splices don't shift later offsets.
    """
    edits: list[tuple[int, int, str]] = []

    # Compute marketSchedules array span up-front (used to scope top-level int
    # field lookups so we don't accidentally hit a session's minPublishers).
    ms_match = None
    ms_idx = block.find('"marketSchedules":')
    if ms_idx >= 0:
        ms_open = block.find("[", ms_idx)
        if ms_open >= 0:
            ms_close = find_matching_close(block, ms_open)
            if ms_close is not None:
                ms_match = (ms_open, ms_close + 1)

    for change in changes:
        if change.location == "top_level":
            scope_block, scope_offset = block, 0
            # For top-level int fields, scope the lookup to the tail after marketSchedules.
            if change.field == "minPublishers" and ms_match is not None:
                tail_start = ms_match[1]
                scope_block = block[tail_start:]
                scope_offset = tail_start
        else:
            sb = find_session_block(block, change.location)
            if sb is None:
                raise RuntimeError(f"session block {change.location!r} not found in feed block")
            scope_block = block[sb[0]:sb[1]]
            scope_offset = sb[0]

        if change.field == "allowedPublisherIds":
            span = find_publisher_array_span(scope_block)
            if span is None:
                raise RuntimeError(f"allowedPublisherIds not found in {change.location}")
            replacement = _format_publisher_list(change.after)
        elif change.field == "minPublishers":
            span = find_int_field_span(scope_block, "minPublishers")
            if span is None:
                raise RuntimeError(f"minPublishers not found in {change.location}")
            replacement = str(change.after)
        elif change.field == "state":
            span = find_string_field_span(scope_block, "state")
            if span is None:
                raise RuntimeError(f"state field not found in {change.location}")
            replacement = f'"{change.after}"'
        else:
            raise RuntimeError(f"unsupported field {change.field!r}")

        abs_start = scope_offset + span[0]
        abs_end = scope_offset + span[1]
        edits.append((abs_start, abs_end, replacement))

    # Apply in reverse offset order so earlier spans aren't disturbed.
    for start, end, replacement in sorted(edits, key=lambda e: -e[0]):
        block = block[:start] + replacement + block[end:]
    return block


def apply_changes(raw: str, changes: list[Change]) -> str:
    """Apply all changes to the raw JSON text, preserving formatting.

    Groups changes by feedId, locates each feed block once, applies all
    changes for that feed, then splices back. This avoids byte-offset
    drift across the larger document.
    """
    if not changes:
        return raw

    by_feed: dict[int, list[Change]] = defaultdict(list)
    for c in changes:
        by_feed[c.feed_id].append(c)

    # Apply per-feed in reverse feedId-block order so absolute offsets are stable.
    feed_bounds = {}
    for feed_id in by_feed:
        bounds = find_feed_block(raw, feed_id)
        if bounds is None:
            raise RuntimeError(f"feed {feed_id} not found in raw text")
        feed_bounds[feed_id] = bounds

    for feed_id in sorted(by_feed.keys(), key=lambda fid: -feed_bounds[fid][0]):
        start, end = feed_bounds[feed_id]
        block = raw[start:end]
        new_block = _apply_changes_to_feed_block(block, by_feed[feed_id])
        raw = raw[:start] + new_block + raw[end:]

    return raw
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
pre-commit run --files tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): apply Changes back into raw text preserving formatting"
```

---

## Task 20: Orchestrator — backup, write, lint subprocess

**Files:**

- Modify: `tools/edit-config/lib/config_editor.py`
- Modify: `tools/edit-config/tests/test_config_editor.py`

Three small functions:

- `write_with_backup(path, new_text, no_backup=False)` — writes `path.bak` (unless skipped) then `path`.
- `run_linter(config_path) -> tuple[int, str]` — invokes `tools/config-linter/config_linter.py` as a subprocess; returns (exit code, captured stdout+stderr).

- [ ] **Step 1: Write failing tests**

Append to `test_config_editor.py`:

```python
import shutil

from lib.config_editor import write_with_backup, run_linter


class TestWriteWithBackup:
    def test_writes_backup_and_new_content(self, tmp_path):
        target = tmp_path / "after.json"
        target.write_text("ORIGINAL", encoding="utf-8")
        write_with_backup(str(target), "MODIFIED")
        assert target.read_text() == "MODIFIED"
        assert (tmp_path / "after.json.bak").read_text() == "ORIGINAL"

    def test_skip_backup_flag(self, tmp_path):
        target = tmp_path / "after.json"
        target.write_text("ORIGINAL", encoding="utf-8")
        write_with_backup(str(target), "MODIFIED", no_backup=True)
        assert target.read_text() == "MODIFIED"
        assert not (tmp_path / "after.json.bak").exists()

    def test_overwrites_prior_backup(self, tmp_path):
        target = tmp_path / "after.json"
        target.write_text("ORIGINAL", encoding="utf-8")
        (tmp_path / "after.json.bak").write_text("STALE_BACKUP", encoding="utf-8")
        write_with_backup(str(target), "MODIFIED")
        assert (tmp_path / "after.json.bak").read_text() == "ORIGINAL"


class TestRunLinter:
    def test_runs_existing_linter_on_fixture(self, tmp_path):
        # Copy the fixture so we don't run on the real after.json
        src = FIXTURE_PATH
        dst = tmp_path / "after.json"
        shutil.copy(src, dst)
        rc, output = run_linter(str(dst))
        assert isinstance(rc, int)
        assert isinstance(output, str)

    def test_handles_missing_linter_gracefully(self, monkeypatch, tmp_path):
        # Point at a non-existent linter path; expect a non-zero rc and
        # a clear "not found" message rather than a crash.
        from lib import config_editor
        monkeypatch.setattr(config_editor, "_LINTER_PATH", "/does/not/exist.py")
        target = tmp_path / "after.json"
        shutil.copy(FIXTURE_PATH, target)
        rc, output = run_linter(str(target))
        assert rc != 0
        assert "linter" in output.lower() or "not found" in output.lower()
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

- [ ] **Step 3: Implement `write_with_backup` and `run_linter`**

Append to `lib/config_editor.py`:

```python
import shutil
import subprocess
from pathlib import Path


_LINTER_PATH = str(
    Path(__file__).resolve().parents[3] / "tools" / "config-linter" / "config_linter.py"
)


def write_with_backup(path: str, new_text: str, no_backup: bool = False) -> None:
    """Write `new_text` to `path`, optionally writing a `.bak` copy first."""
    target = Path(path)
    if not no_backup:
        backup = target.with_suffix(target.suffix + ".bak")
        if target.exists():
            shutil.copy2(target, backup)
    target.write_text(new_text, encoding="utf-8")


def run_linter(config_path: str) -> tuple[int, str]:
    """Run tools/config-linter on `config_path`. Returns (rc, output)."""
    if not Path(_LINTER_PATH).exists():
        return 1, f"linter script not found at {_LINTER_PATH}"
    try:
        proc = subprocess.run(
            ["python3", _LINTER_PATH, "--config", config_path],
            capture_output=True, text=True, check=False, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return 1, "linter timed out"
    return proc.returncode, proc.stdout + proc.stderr
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_config_editor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
pre-commit run --files tools/edit-config/lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): backup write and linter subprocess hook"
```

---

## Task 21: CLI entry point `edit_config.py`

**Files:**

- Create: `tools/edit-config/edit_config.py`
- Create: `tools/edit-config/tests/test_edit_config_cli.py`

The thin wrapper: parse argv, build plan (CLI → single op or YAML → list), load config, simulate, render plan + diff, optionally apply + lint. Exit codes per spec.

- [ ] **Step 1: Write failing CLI tests**

Create `tools/edit-config/tests/test_edit_config_cli.py`:

```python
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "edit-config" / "edit_config.py"
FIXTURE = Path(__file__).parent / "fixtures" / "after_sample.json"


def run_cli(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(cwd or REPO_ROOT),
    )


@pytest.fixture
def config_copy(tmp_path):
    dst = tmp_path / "after.json"
    shutil.copy(FIXTURE, dst)
    return dst


class TestCli:
    def test_dry_run_default(self, config_copy):
        result = run_cli([
            "--config", str(config_copy),
            "--add-publisher", "80",
            "--feed-id", "1",
        ])
        assert result.returncode == 0, result.stderr
        # Config should be unchanged (dry run)
        assert "[DRY RUN]" in result.stdout
        data = json.loads(config_copy.read_text())
        f = next(x for x in data["feeds"] if x["feedId"] == 1)
        assert 80 not in f["allowedPublisherIds"]

    def test_apply_writes_changes(self, config_copy):
        result = run_cli([
            "--config", str(config_copy),
            "--add-publisher", "80",
            "--feed-id", "1",
            "--apply", "--no-lint",
        ])
        assert result.returncode == 0, result.stderr
        data = json.loads(config_copy.read_text())
        f = next(x for x in data["feeds"] if x["feedId"] == 1)
        assert 80 in f["allowedPublisherIds"]

    def test_apply_writes_backup(self, config_copy):
        run_cli([
            "--config", str(config_copy),
            "--add-publisher", "80",
            "--feed-id", "1",
            "--apply", "--no-lint",
        ])
        bak = config_copy.parent / "after.json.bak"
        assert bak.exists()
        # Backup matches original fixture
        assert json.loads(bak.read_text()) == json.loads(FIXTURE.read_text())

    def test_no_backup_flag_skips_bak(self, config_copy):
        run_cli([
            "--config", str(config_copy),
            "--add-publisher", "80",
            "--feed-id", "1",
            "--apply", "--no-lint", "--no-backup",
        ])
        assert not (config_copy.parent / "after.json.bak").exists()

    def test_zero_match_exits_nonzero(self, config_copy):
        result = run_cli([
            "--config", str(config_copy),
            "--add-publisher", "80",
            "--feed-id", "99999",
        ])
        assert result.returncode != 0

    def test_warning_does_not_fail(self, config_copy):
        # State change with a regression warning should still exit 0.
        result = run_cli([
            "--config", str(config_copy),
            "--set-state", "INACTIVE",
            "--feed-id", "1",
            "--apply", "--no-lint",
        ])
        assert result.returncode == 0
        assert "WARNING" in result.stdout or "warning" in result.stdout.lower()

    def test_yaml_spec(self, config_copy, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n"
            "  - op: add_publisher\n"
            "    publisher_id: 80\n"
            "    feed_id: 1\n",
            encoding="utf-8",
        )
        result = run_cli([
            "--config", str(config_copy),
            "--from-spec", str(spec),
            "--apply", "--no-lint",
        ])
        assert result.returncode == 0, result.stderr
        data = json.loads(config_copy.read_text())
        f = next(x for x in data["feeds"] if x["feedId"] == 1)
        assert 80 in f["allowedPublisherIds"]

    def test_feed_ids_from_file(self, config_copy, tmp_path):
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text("1, 100", encoding="utf-8")
        result = run_cli([
            "--config", str(config_copy),
            "--add-publisher", "80",
            "--feed-ids-from", str(ids_file),
            "--apply", "--no-lint",
        ])
        assert result.returncode == 0, result.stderr
        data = json.loads(config_copy.read_text())
        f1 = next(x for x in data["feeds"] if x["feedId"] == 1)
        f100 = next(x for x in data["feeds"] if x["feedId"] == 100)
        assert 80 in f1["allowedPublisherIds"]
        assert 80 in f100["allowedPublisherIds"]

    def test_diff_always_prints_on_dry_run(self, config_copy):
        result = run_cli([
            "--config", str(config_copy),
            "--add-publisher", "80",
            "--feed-id", "1",
        ])
        assert "@@ feedId 1" in result.stdout
```

- [ ] **Step 2: Verify tests fail**

```bash
pytest tools/edit-config/tests/test_edit_config_cli.py -v
```

Expected: failures because `edit_config.py` doesn't exist yet.

- [ ] **Step 3: Implement `edit_config.py`**

Create `tools/edit-config/edit_config.py`:

```python
#!/usr/bin/env python3
"""edit-config: surgical editor for after.json.

See docs/edit_config.md for usage.
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure tools/edit-config is on sys.path when invoked directly.
_TOOL_ROOT = Path(__file__).resolve().parent
if str(_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOL_ROOT))

from lib.config_diff import render_diff  # noqa: E402
from lib.config_editor import (  # noqa: E402
    apply_changes,
    build_op_from_args,
    parse_yaml_spec,
    run_linter,
    simulate_plan,
    write_with_backup,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="edit_config.py",
        description="Surgical editor for after.json",
    )
    p.add_argument("--config", required=True, help="Path to after.json")

    # Operation flags (mutually exclusive)
    op_group = p.add_mutually_exclusive_group()
    op_group.add_argument("--add-publisher", type=int)
    op_group.add_argument("--remove-publisher", type=int)
    op_group.add_argument("--set-min-publishers", type=int)
    op_group.add_argument("--bump-min-publishers", type=str,
                          help="Signed integer, e.g. +1 or -2")
    op_group.add_argument("--set-state", choices=("STABLE", "COMING_SOON", "INACTIVE"))
    op_group.add_argument("--from-spec", type=str, help="YAML spec path")

    # Targeting
    p.add_argument("--feed-id", type=str,
                   help="Selector: e.g. 922 or 100-200,205,3530-3540")
    p.add_argument("--feed-ids-from", type=str,
                   help="Read selector(s) from file (use - for stdin)")
    p.add_argument("--symbol-pattern", type=str)
    p.add_argument("--asset-class", type=str)
    p.add_argument("--state", choices=("STABLE", "COMING_SOON", "INACTIVE"),
                   help="Filter (not edit)")

    # Scope
    p.add_argument("--session", choices=(
        "REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT", "ALL", "NONE",
    ))

    # Execution
    p.add_argument("--dry-run", action="store_true",
                   help="Default; explicit form for clarity")
    p.add_argument("--apply", action="store_true", help="Write changes")
    p.add_argument("--show-full-diff", action="store_true")
    p.add_argument("--no-lint", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    raw = config_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    feeds = data["feeds"]
    print(f"Reading {config_path} ({len(feeds)} feeds)...")

    # Build plan
    if args.from_spec:
        plan = parse_yaml_spec(args.from_spec)
        print(f"Parsing {args.from_spec}... {len(plan)} operations.")
    else:
        try:
            plan = build_op_from_args(args)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    # Simulate
    result = simulate_plan(plan, feeds)

    # Plan summary
    print()
    print("Plan:")
    for i, planned in enumerate(plan, start=1):
        op_type = type(planned.op).__name__
        matched = result.matched_counts[i - 1]
        print(f"  [{i}] {op_type} → {matched} feed(s) matched")

    # Errors and warnings
    print()
    if result.errors:
        print(f"Validation: FAIL ({len(result.errors)} errors, {len(result.warnings)} warnings)")
        for e in result.errors:
            print(f"  ERROR: {e}")
    else:
        print(f"Validation: PASS (0 errors, {len(result.warnings)} warnings)")
    for w in result.warnings:
        print(f"  WARNING: {w.message}")

    # Diff
    print()
    is_apply = args.apply
    print_diff = (not is_apply) or (is_apply and not result.errors)
    if print_diff:
        print("Diff:")
        print(render_diff(result.changes, show_full=args.show_full_diff))

    summary = (
        f"Summary: {len(result.changes)} changes, "
        f"{len(result.errors)} errors, {len(result.warnings)} warnings."
    )
    print(summary)

    if not is_apply:
        print("[DRY RUN] No changes written. Re-run with --apply to write.")
        return 1 if result.errors else 0

    if result.errors:
        print("Refusing to write due to errors.", file=sys.stderr)
        return 1

    if not result.changes:
        print("No changes to write.")
        return 0

    new_raw = apply_changes(raw, result.changes)
    write_with_backup(str(config_path), new_raw, no_backup=args.no_backup)
    if not args.no_backup:
        print(f"Backup written: {config_path}.bak")
    print(f"Wrote {len(result.changes)} changes to {config_path}.")

    if not args.no_lint:
        print(f"Running config-linter on {config_path}...")
        rc, out = run_linter(str(config_path))
        if out.strip():
            print(out.strip())
        if rc == 0:
            print("Lint: clean.")
        else:
            print(f"Lint: rc={rc} (informational; no rollback).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Verify tests pass**

```bash
pytest tools/edit-config/tests/test_edit_config_cli.py -v
```

Expected: all CLI tests pass.

- [ ] **Step 5: Run full suite + coverage**

```bash
pytest tools/edit-config/tests/ -v --cov=tools/edit-config --cov-report=term-missing
```

Expected: all tests pass, coverage ≥ 80% for `tools/edit-config/edit_config.py` and `tools/edit-config/lib/`.

If coverage falls below 80%, add tests for whichever uncovered branches matter (skip dead defensive paths).

- [ ] **Step 6: Commit**

```bash
git add tools/edit-config/edit_config.py tools/edit-config/tests/test_edit_config_cli.py
pre-commit run --files tools/edit-config/edit_config.py tools/edit-config/tests/test_edit_config_cli.py
git commit -m "feat(edit-config): CLI entry point + end-to-end tests"
```

---

## Task 22: User documentation

**Files:**

- Create: `docs/edit_config.md`
- Create: `docs/edit_config_examples.md`

- [ ] **Step 1: Write `docs/edit_config.md`**

Create `docs/edit_config.md` with: overview, install/run, every CLI flag, every YAML field, defaults table per op, exit codes, the `--feed-ids-from` file grammar, and a few full examples. The structure mirrors the design spec but reframed as user reference. Include:

````markdown
# edit_config.py

Surgical editor for `after.json`. Adds/removes publishers, sets/bumps `minPublishers`, sets `state` — for one feed, a list, a range, or a filtered set.

## Installation

```bash
source venv/bin/activate
pip install -r requirements.txt
```
````

## Usage

```bash
python3 tools/edit-config/edit_config.py --config after.json [OPERATION] [TARGETING] [SCOPE] [EXECUTION]
```

### Operations (exactly one per CLI invocation)

| Flag                         | Effect                                                |
| ---------------------------- | ----------------------------------------------------- | --------- | ----------------- |
| `--add-publisher INT`        | Add publisher to `allowedPublisherIds`                |
| `--remove-publisher INT`     | Remove publisher from `allowedPublisherIds`           |
| `--set-min-publishers INT`   | Set `minPublishers` to a value                        |
| `--bump-min-publishers ±INT` | Adjust `minPublishers` by signed delta (clamped at 1) |
| `--set-state STABLE          | COMING_SOON                                           | INACTIVE` | Change feed state |
| `--from-spec PATH`           | Apply a batched YAML spec (multiple ops)              |

### Targeting (≥1 required when not using `--from-spec`)

| Flag               | Form                                       |
| ------------------ | ------------------------------------------ |
| `--feed-id`        | `922` or `100-200,205,208,3530-3540`       |
| `--feed-ids-from`  | path to a text file (or `-` for stdin)     |
| `--symbol-pattern` | fnmatch glob, e.g. `Equity.US.*`           |
| `--asset-class`    | matches `metadata.asset_type`              |
| `--state`          | filter for STABLE / COMING_SOON / INACTIVE |

### Scope (publisher / minPublishers ops)

`--session {REGULAR,PRE_MARKET,POST_MARKET,OVER_NIGHT,ALL,NONE}`

Defaults: top-level + REGULAR for equity feeds with sessions; top-level only for non-equity. `NONE` = top-level only. `ALL` = top-level + all 4 sessions.

`remove_publisher` default differs: removes from EVERYWHERE in this feed.

### Execution

| Flag               | Default | Effect                              |
| ------------------ | ------- | ----------------------------------- |
| `--dry-run`        | yes     | Show plan + diff; do not write      |
| `--apply`          | no      | Required to write                   |
| `--show-full-diff` | no      | Don't truncate the diff at 40 hunks |
| `--no-lint`        | no      | Skip post-apply config-linter run   |
| `--no-backup`      | no      | Skip `.bak` write                   |

### Exit codes

- `0` — success (warnings allowed)
- `1` — validation or runtime error (no write happens)

## YAML spec format

```yaml
version: 1
operations:
  - op: add_publisher
    publisher_id: 80
    feed_id: "1000-1050"

  - op: remove_publisher
    publisher_id: 22
    feed_id: 922
    session: PRE_MARKET

  - op: set_min_publishers
    value: 3
    asset_class: equity
    state: [STABLE, COMING_SOON]
    session: REGULAR
```

Range strings in YAML must be quoted (`"1000-1050"`) — unquoted YAML parses `1000-1050` as `-50`.

## `--feed-ids-from` file format

Plain text, UTF-8. Tokens are `N` (single ID) or `A-B` (inclusive range). Tokens may be separated by commas, whitespace, or newlines. `#` to end-of-line is stripped. Blank lines ignored. Examples:

```text
# canonical one per line
100-200
205
3530
```

```text
# inline pasted from a slack message
100-200, 205, 208, 3530
```

````

- [ ] **Step 2: Write `docs/edit_config_examples.md`**

Create `docs/edit_config_examples.md`:

```markdown
# edit_config recipes

## Add a publisher to a contiguous range

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --add-publisher 80 --feed-id 1000-1050
````

## Add a publisher to a discontiguous list (paste from slack)

```bash
cat > /tmp/feeds.txt <<'EOF'
# from incident 2026-05-05
100-200
205
208
275, 299
3530
EOF
python3 tools/edit-config/edit_config.py --config after.json \
    --add-publisher 80 --feed-ids-from /tmp/feeds.txt
```

## Remove a retired publisher entirely (all sessions + top-level)

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --remove-publisher 22 --asset-class equity
```

## Add a publisher to PRE_MARKET only on a single equity

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --add-publisher 80 --feed-id 922 --session PRE_MARKET
```

## Raise minPublishers across all STABLE us-equities REGULAR by 1

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --bump-min-publishers +1 --asset-class equity --state STABLE \
    --session REGULAR
```

## Promote a list of feeds to STABLE

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --set-state STABLE --feed-id 500,501,502
```

## Deactivate a deprecated feed

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --set-state INACTIVE --feed-id 6000
```

## Apply a batched YAML spec

```yaml
# edits-2026-05-05.yaml
operations:
  - op: add_publisher
    publisher_id: 80
    feed_id: "1000-1050"
  - op: bump_min_publishers
    delta: 1
    asset_class: equity
    state: STABLE
    session: REGULAR
  - op: set_state
    value: COMING_SOON
    feed_id: [500, 501, 502]
```

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --from-spec edits-2026-05-05.yaml
# review diff, then:
python3 tools/edit-config/edit_config.py --config after.json \
    --from-spec edits-2026-05-05.yaml --apply
```

````

- [ ] **Step 3: Commit**

```bash
git add docs/edit_config.md docs/edit_config_examples.md
pre-commit run --files docs/edit_config.md docs/edit_config_examples.md
git commit -m "docs(edit-config): usage reference and recipes"
````

---

## Task 23: CLAUDE.md scripts row + final coverage gate

**Files:**

- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the scripts table row**

In `CLAUDE.md`, find the Scripts table (`| Script | Purpose | Quick Example | Docs |`). Add a row right after the `tools/config-linter/config_linter.py` row:

```markdown
| `tools/edit-config/edit_config.py` | Surgical editor: add/remove publishers, set minPublishers, set state | `python3 tools/edit-config/edit_config.py --config after.json --add-publisher 80 --feed-id 1000-1050` | [docs/edit_config.md](docs/edit_config.md) |
```

- [ ] **Step 2: Run the full test suite + coverage gate**

```bash
pytest tools/edit-config/tests/ -v \
    --cov=tools/edit-config \
    --cov-report=term-missing \
    --cov-fail-under=80
```

Expected: all tests pass, coverage line at or above 80%.

If coverage is below 80%, identify which file is under-tested (look at the Missing column) and add tests. Do **not** add tests just to game the metric — focus on real branches: alternate session scopes, error paths, edge inputs (empty list, single-element list, etc.).

- [ ] **Step 3: Final dry-run sanity check on the real `after.json`**

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --add-publisher 999 --feed-id 1
```

Expected: prints plan + diff showing publisher 999 added to feed 1's `allowedPublisherIds`. Real `after.json` is **not** modified (dry run is default).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
pre-commit run --files CLAUDE.md
git commit -m "docs(edit-config): list in CLAUDE.md scripts table"
```

- [ ] **Step 5: Update spec status**

Modify the design spec header to reflect completion:

```bash
sed -i 's/^\*\*Status:\*\* Draft (pending user review)$/**Status:** Implemented/' docs/superpowers/specs/2026-05-05-edit-config-design.md
git add docs/superpowers/specs/2026-05-05-edit-config-design.md
pre-commit run --files docs/superpowers/specs/2026-05-05-edit-config-design.md
git commit -m "docs(edit-config): mark design spec as Implemented"
```

---

## Self-Review

**Spec coverage:**

| Spec section                                                             | Implemented in task                                                     |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| Operations: `add_publisher`                                              | Task 9                                                                  |
| Operations: `remove_publisher` (default = everywhere; warn at-floor)     | Task 10                                                                 |
| Operations: `set_min_publishers` (hard error if value > count; warnings) | Task 11                                                                 |
| Operations: `bump_min_publishers` (clamped at 1)                         | Task 12                                                                 |
| Operations: `set_state` (soft regression guardrails)                     | Task 13                                                                 |
| Targeting: `--feed-id` mixed singles+ranges                              | Task 3, used in Task 16                                                 |
| Targeting: `--feed-ids-from` file/stdin                                  | Task 4 (parser), Task 16 (CLI), Task 21 (E2E)                           |
| Targeting: `--symbol-pattern`, `--asset-class`, `--state`                | Task 15                                                                 |
| Scope: `--session REGULAR/.../ALL/NONE` defaults                         | Tasks 9-13                                                              |
| YAML spec with `version`, mixed `feed_id`, list `state`                  | Task 17                                                                 |
| Atomicity: validate-all-then-apply                                       | Task 18 (simulate collects errors), Task 21 (CLI gates write on errors) |
| Inter-op visibility (deep-copy work feeds)                               | Task 18                                                                 |
| Hard error on zero target match                                          | Task 18                                                                 |
| Diff with feedId/symbol/session hunk headers; truncation                 | Task 14                                                                 |
| Diff always prints on dry-run; on apply only when no errors              | Task 21                                                                 |
| `.bak` backup; `--no-backup` skip                                        | Task 20, Task 21 (CLI)                                                  |
| Linter subprocess; informational; `--no-lint` skip                       | Task 20, Task 21 (CLI)                                                  |
| Exit codes: 0 success (warnings OK), 1 errors                            | Task 21                                                                 |
| Independence (no imports from other update\_\*.py / repo lib/)           | Verified by file paths in every task                                    |
| `tests/fixtures/after_sample.json` representative                        | Task 2                                                                  |
| Coverage ≥80%                                                            | Task 23                                                                 |
| Docs: `edit_config.md`, `edit_config_examples.md`                        | Task 22                                                                 |
| `CLAUDE.md` scripts row                                                  | Task 23                                                                 |

No gaps identified.

**Placeholder scan:** none. Every step has concrete code or commands. No "TBD"/"TODO"/"similar to Task N".

**Type consistency:** `Change` fields (`feed_id`, `symbol`, `location`, `field`, `before`, `after`) used consistently from Task 8 onward. `PlannedOp` fields (`op`, `filters`) consistent. `FilterSet` fields (`feed_ids` plural set, `states` plural set, scalar `symbol_pattern`/`asset_class`) consistent. Session-name strings (`REGULAR`, `PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT`, `ALL`, `NONE`) consistent in Tasks 9-13 and 15-16.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-05-edit-config.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for keeping main-context window clean across 23 tasks.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?
