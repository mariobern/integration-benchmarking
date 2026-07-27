# stalePriceFilter Support in edit_config.py — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--set-stale-filter` and `--clear-stale-filter` operations to `tools/edit-config/edit_config.py` so the session-level `stalePriceFilter` object can be created, retuned, and removed in bulk from a feed-ID list such as `jp_kr.csv`.

**Architecture:** Follows the existing edit-config op pipeline unchanged: an op class in `config_ops.py` mutates a parsed feed dict and returns `Change` records; `config_editor.py` simulates the plan and replays those changes onto the raw JSON text via byte-span helpers in `config_text_surgery.py`; `config_diff.py` renders them. This is the first op that writes a nested object and the first that writes a float, so four new surgery helpers are needed. Targeting gains a CSV rule in `config_selector.py` that benefits every op.

**Tech Stack:** Python 3.12, stdlib `re`/`json`/`argparse`, PyYAML for the spec path, pytest for tests, black + prettier via pre-commit.

**Spec:** `docs/superpowers/specs/2026-07-27-stale-price-filter-edit-config-design.md`

## Global Constraints

- Config format: session-only publishers (`lazer_update.json` era). The tool already rejects old-format configs; do not change that.
- Config keys are serialized alphabetically. `stalePriceFilter` sorts after `session`, so it is always the **last** key of a session object — written with no trailing comma, and requiring a comma added to the previous field's line.
- Defaults, matching the three feeds already running the filter (2166, 3337, 3338): `movedPriceThresholdBps=0.5`, `stalenessThresholdSecs=10800`, `windowSecs=60`.
- Create-vs-patch semantics: when the session has no filter, unset knobs take the defaults; when it has one, unset knobs are left untouched.
- Validation: non-numeric or `<= 0` values are `OpError` (block apply); `stalenessThresholdSecs < windowSecs` is a `Warning` only.
- Text edits must preserve the file's existing formatting; the applier never re-serializes the whole document.
- Run `python3 -m pytest tools/edit-config/tests/ -q` before every commit, and `pre-commit run --files <changed files>` in the final task.
- Use `python3`, never `python` — the bare name does not exist on this machine.
- All commands run from the repo root, `/Users/mariobernardi/Documents/GitHub/integration-benchmarking`.

## File Structure

| File                                                       | Responsibility                                                            | Task |
| ---------------------------------------------------------- | ------------------------------------------------------------------------- | ---- |
| `tools/edit-config/edit_config_lib/config_selector.py`     | Feed-ID selector grammar; gains CSV column-1 reading                      | 1    |
| `tools/edit-config/edit_config_lib/config_text_surgery.py` | Byte-span locators + splices; gains 4 helpers                             | 2    |
| `tools/edit-config/edit_config_lib/config_ops.py`          | `SetStaleFilter`, `ClearStaleFilter`, defaults, session-resolution rename | 3    |
| `tools/edit-config/tests/fixtures/stale_sample.json`       | New fixture: one feed with a filter, one without, one partial             | 3    |
| `tools/edit-config/edit_config_lib/config_editor.py`       | Applier branches (Task 4), CLI + YAML wiring (Task 5)                     | 4, 5 |
| `tools/edit-config/edit_config_lib/config_diff.py`         | Diff rendering for the three cases                                        | 4    |
| `tools/edit-config/edit_config.py`                         | Five argparse flags                                                       | 5    |
| `docs/edit_config.md`, `CLAUDE.md`                         | Usage docs                                                                | 6    |

---

### Task 1: CSV column-1 targeting in the selector

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_selector.py:47-53`
- Test: `tools/edit-config/tests/test_config_selector.py`

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `read_selector_file(path: str | Path) -> set[int]` — unchanged signature, new behavior for `.csv` paths. Used by `--feed-ids-from` for every op.

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_selector.py`. The file already imports `parse_selector_text` and `SelectorError`; add `read_selector_file` to that import line:

```python
from edit_config_lib.config_selector import (
    parse_selector_text,
    read_selector_file,
    SelectorError,
)


class TestReadSelectorFileCsv:
    def test_csv_reads_first_column_only(self, tmp_path):
        # The shape of jp_kr.csv: feed_id, date, mode
        p = tmp_path / "jp_kr.csv"
        p.write_text(
            "1990, 2026-07-24, jp-equities\n"
            "2023, 2026-07-24, jp-equities\n"
            "2166, 2026-07-24, kr-equities\n",
            encoding="utf-8",
        )
        assert read_selector_file(p) == {1990, 2023, 2166}

    def test_csv_skips_header_row(self, tmp_path):
        p = tmp_path / "feeds.csv"
        p.write_text("feed_id,date,mode\n1990,2026-07-24,jp-equities\n", encoding="utf-8")
        assert read_selector_file(p) == {1990}

    def test_csv_supports_ranges_in_column_one(self, tmp_path):
        p = tmp_path / "feeds.csv"
        p.write_text("100-102,2026-07-24,fx\n205,2026-07-24,fx\n", encoding="utf-8")
        assert read_selector_file(p) == {100, 101, 102, 205}

    def test_csv_ignores_blank_lines_and_comments(self, tmp_path):
        p = tmp_path / "feeds.csv"
        p.write_text(
            "# jp/kr batch\n\n1990, 2026-07-24, jp-equities\n\n", encoding="utf-8"
        )
        assert read_selector_file(p) == {1990}

    def test_non_csv_path_stays_strict(self, tmp_path):
        p = tmp_path / "ids.txt"
        p.write_text("1990, 2026-07-24, jp-equities\n", encoding="utf-8")
        with pytest.raises(SelectorError):
            read_selector_file(p)

    def test_plain_id_csv_still_works(self, tmp_path):
        p = tmp_path / "ids.csv"
        p.write_text("1990\n2023\n", encoding="utf-8")
        assert read_selector_file(p) == {1990, 2023}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_selector.py -q`
Expected: FAIL — `test_csv_reads_first_column_only` raises `SelectorError: invalid token '2026-07-24'`.

- [ ] **Step 3: Implement CSV handling**

Replace `read_selector_file` in `tools/edit-config/edit_config_lib/config_selector.py` and add the helper above it:

```python
def _first_column(text: str) -> str:
    """Reduce CSV text to its first column, one selector token per line.

    The repo's benchmark CSVs carry `feed_id,date,mode` rows, so only column 1
    is a selector token. Blank lines and `#` comments are dropped, and a first
    data row whose column 1 is not a selector token is treated as a header.
    """
    out: list[str] = []
    seen_first_row = False
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        first = stripped.split(",", 1)[0].strip()
        if not first:
            continue
        if not seen_first_row and not _TOKEN_PATTERN.match(first):
            seen_first_row = True
            continue  # header row
        seen_first_row = True
        out.append(first)
    return "\n".join(out)


def read_selector_file(path: str | Path) -> set[int]:
    """Read selector content from a file path or '-' for stdin.

    A path ending in `.csv` is read as a CSV: only column 1 of each row is
    parsed, so `feed_id,date,mode` files work as targeting input directly.
    Every other path (and stdin) uses the strict `N` / `A-B` grammar.
    """
    import sys

    if str(path) == "-":
        return parse_selector_text(sys.stdin.read())
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".csv":
        text = _first_column(text)
    return parse_selector_text(text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_selector.py -q`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Run the full suite for regressions**

Run: `python3 -m pytest tools/edit-config/tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_selector.py tools/edit-config/tests/test_config_selector.py
git commit -m "feat(edit-config): read feed ids from column 1 of .csv selector files"
```

---

### Task 2: Text-surgery helpers

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_text_surgery.py:132-146` (refactor `find_metadata_block`), plus new helpers
- Test: `tools/edit-config/tests/test_config_text_surgery.py`

**Interfaces:**

- Consumes: `find_matching_close(text, open_idx)` (already in the module).
- Produces, all used by Task 4's applier:

  - `find_object_field_span(block: str, key: str) -> tuple[int, int] | None` — span of an object-valued field's `{…}`, start on `{`, end exclusive.
  - `find_number_field_span(block: str, key: str) -> tuple[int, int] | None` — span of an int **or** decimal literal.
  - `insert_field_before_close_brace(block: str, field_text: str) -> str` — inserts `field_text` (no trailing comma) as the last field.
  - `delete_object_field(block: str, key: str) -> str` — removes `"key": {…}` plus the comma preceding it.

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_text_surgery.py`, and extend the module's import block with the four new names:

```python
import json

from edit_config_lib.config_text_surgery import (
    find_object_field_span,
    find_number_field_span,
    insert_field_before_close_brace,
    delete_object_field,
)


SESSION_WITH_FILTER = """        {
          "allowedPublisherIds": [
            59,
            84
          ],
          "minPublishers": 2,
          "session": "REGULAR",
          "stalePriceFilter": {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 60
          }
        }"""

SESSION_WITHOUT_FILTER = """        {
          "allowedPublisherIds": [
            59,
            84
          ],
          "minPublishers": 2,
          "session": "REGULAR"
        }"""


class TestFindObjectFieldSpan:
    def test_locates_stale_price_filter(self):
        span = find_object_field_span(SESSION_WITH_FILTER, "stalePriceFilter")
        assert span is not None
        assert SESSION_WITH_FILTER[span[0]] == "{"
        assert SESSION_WITH_FILTER[span[1] - 1] == "}"
        assert json.loads(SESSION_WITH_FILTER[span[0] : span[1]]) == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 60,
        }

    def test_absent_field_returns_none(self):
        assert find_object_field_span(SESSION_WITHOUT_FILTER, "stalePriceFilter") is None


class TestFindNumberFieldSpan:
    def test_decimal_value_captured_whole(self):
        span = find_number_field_span(SESSION_WITH_FILTER, "movedPriceThresholdBps")
        assert span is not None
        assert SESSION_WITH_FILTER[span[0] : span[1]] == "0.5"

    def test_integer_value(self):
        span = find_number_field_span(SESSION_WITH_FILTER, "windowSecs")
        assert SESSION_WITH_FILTER[span[0] : span[1]] == "60"

    def test_replacing_decimal_keeps_json_valid(self):
        span = find_number_field_span(SESSION_WITH_FILTER, "movedPriceThresholdBps")
        out = SESSION_WITH_FILTER[: span[0]] + "2.5" + SESSION_WITH_FILTER[span[1] :]
        assert json.loads(out)["stalePriceFilter"]["movedPriceThresholdBps"] == 2.5

    def test_absent_field_returns_none(self):
        assert find_number_field_span(SESSION_WITH_FILTER, "nope") is None


class TestInsertFieldBeforeCloseBrace:
    def test_appends_as_last_field_with_comma_on_previous_line(self):
        field = '"stalePriceFilter": {\n            "windowSecs": 60\n          }'
        out = insert_field_before_close_brace(SESSION_WITHOUT_FILTER, field)
        parsed = json.loads(out)
        assert parsed["stalePriceFilter"] == {"windowSecs": 60}
        assert parsed["session"] == "REGULAR"
        assert '"session": "REGULAR",' in out

    def test_empty_object(self):
        out = insert_field_before_close_brace("{\n        }", '"a": 1')
        assert json.loads(out) == {"a": 1}


class TestDeleteObjectField:
    def test_removes_field_and_preceding_comma(self):
        out = delete_object_field(SESSION_WITH_FILTER, "stalePriceFilter")
        parsed = json.loads(out)
        assert "stalePriceFilter" not in parsed
        assert parsed["session"] == "REGULAR"
        assert parsed["minPublishers"] == 2

    def test_absent_field_is_noop(self):
        assert (
            delete_object_field(SESSION_WITHOUT_FILTER, "stalePriceFilter")
            == SESSION_WITHOUT_FILTER
        )

    def test_only_field_leaves_empty_object(self):
        block = '{\n  "stalePriceFilter": {\n    "windowSecs": 60\n  }\n}'
        assert json.loads(delete_object_field(block, "stalePriceFilter")) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_text_surgery.py -q`
Expected: FAIL at import — `ImportError: cannot import name 'find_object_field_span'`.

- [ ] **Step 3: Implement the helpers**

In `tools/edit-config/edit_config_lib/config_text_surgery.py`, replace the body of `find_metadata_block` so it delegates to a new generic locator, and add the rest. Place `find_object_field_span` immediately above `find_metadata_block`:

```python
def find_object_field_span(block: str, key: str) -> tuple[int, int] | None:
    """Locate the {…} value of an object-valued field `key` within `block`.

    Returns (start, end) where start is the opening '{' and end is one past
    the matching '}'. None if the field is absent.
    """
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{', block)
    if match is None:
        return None
    open_idx = match.end() - 1
    close_idx = find_matching_close(block, open_idx)
    if close_idx is None:
        return None
    return (open_idx, close_idx + 1)


def find_metadata_block(block: str) -> tuple[int, int] | None:
    """Locate the {…} value of the feed-level `metadata` object within
    `block` (the raw text of a single feed object).

    Returns (start, end) where start is the opening '{' and end is one
    past the matching '}'. None if the field is absent.
    """
    return find_object_field_span(block, "metadata")
```

Add `find_number_field_span` directly after the existing `find_int_field_span`:

```python
def find_number_field_span(block: str, key: str) -> tuple[int, int] | None:
    """Locate the numeric value of `"key": N` within `block`, int or decimal.

    Returns the span of the literal only. `find_int_field_span` matches just
    `-?\\d+`, so pointed at `0.5` it would return the `0` and a splice would
    corrupt the value — use this helper for any field that may be fractional.
    """
    pattern = re.compile(
        rf'"{re.escape(key)}":\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'
    )
    match = pattern.search(block)
    if match is None:
        return None
    return (match.start(1), match.end(1))
```

Add the two mutators after `insert_field_before_session`:

```python
def insert_field_before_close_brace(block: str, field_text: str) -> str:
    """Insert `field_text` as the LAST field of `block`'s outermost object.

    `field_text` must NOT carry a trailing comma — the comma is appended to the
    current last field's line instead. This is the inserter for
    `stalePriceFilter`, which sorts after `session` and so is always last in a
    session entry. Multi-line `field_text` must already carry the indentation
    of its continuation lines; only the first line is indented here.
    """
    close = block.rindex("}")
    head = block[:close]
    tail = block[close:]
    close_indent = head[head.rindex("\n") + 1 :] if "\n" in head else ""
    m = re.search(r'\n(\s*)"', block)
    indent = m.group(1) if m else close_indent + "  "
    body = head.rstrip()
    separator = "" if body.endswith("{") else ","
    return body + separator + "\n" + indent + field_text + "\n" + close_indent + tail


def delete_object_field(block: str, key: str) -> str:
    """Delete `"key": { … }` from `block`, including the comma that precedes it.

    The object-valued sibling of `delete_scalar_field`. Assumes the field is the
    LAST field of its object (true for `stalePriceFilter`), so the comma to
    remove sits before the field rather than after it. Deleting the only field
    leaves a valid empty object. Returns `block` unchanged when `key` is absent.
    """
    span = find_object_field_span(block, key)
    if span is None:
        return block
    key_match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{', block)
    start = key_match.start()
    end = span[1]
    # Walk back over the field's indentation, the newline before it, and the
    # comma that terminated the previous field.
    i = start - 1
    while i >= 0 and block[i] in " \t":
        i -= 1
    if i >= 0 and block[i] == "\n":
        i -= 1
        while i >= 0 and block[i] in " \t":
            i -= 1
    if i >= 0 and block[i] == ",":
        i -= 1
    return block[: i + 1] + block[end:]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_text_surgery.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite for regressions**

Run: `python3 -m pytest tools/edit-config/tests/ -q`
Expected: PASS — in particular the existing `find_metadata_block` tests, which now exercise the delegating implementation.

- [ ] **Step 6: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
git commit -m "feat(edit-config): text surgery helpers for object fields and decimal values"
```

---

### Task 3: `SetStaleFilter` and `ClearStaleFilter` ops

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_ops.py:121-139` (rename helper), `:168`, `:254` (call sites); append both ops at end of file
- Create: `tools/edit-config/tests/fixtures/stale_sample.json`
- Test: `tools/edit-config/tests/test_config_ops.py`

**Interfaces:**

- Consumes: `Change`, `Warning`, `OpError`, `get_session` (all in `config_ops.py`).
- Produces:
  - `DEFAULT_MOVED_PRICE_THRESHOLD_BPS = 0.5`, `DEFAULT_STALENESS_THRESHOLD_SECS = 10800`, `DEFAULT_WINDOW_SECS = 60`
  - `STALE_FILTER_KEYS = ("movedPriceThresholdBps", "stalenessThresholdSecs", "windowSecs")`
  - `SetStaleFilter(moved_price_threshold_bps: float | None = None, staleness_threshold_secs: int | None = None, window_secs: int | None = None, session: str | None = None)` with `.apply(feed) -> (list[Change], list[Warning])`
  - `ClearStaleFilter(session: str | None = None)` with the same `.apply` signature
  - `_resolve_session_names(feed, session, what="publisher lists")` — the renamed `_resolve_publisher_sessions`
- Change record contract consumed by Task 4:

  - create → `field="stalePriceFilter"`, `before=None`, `after=dict`
  - full rewrite → `field="stalePriceFilter"`, `before=dict`, `after=dict`
  - single-knob patch → `field="stalePriceFilter.<key>"`, `before=number`, `after=number`
  - clear → `field="stalePriceFilter"`, `before=dict`, `after=None`

- [ ] **Step 1: Create the fixture**

Create `tools/edit-config/tests/fixtures/stale_sample.json`. Feed 2166 mirrors production (filter equal to the defaults); 1990 has no filter; 3337 has a **partial** filter (missing `windowSecs`) to exercise the full-rewrite path; 3338 has a **complete but non-default** filter, so a bare op there proves the defaults do not overwrite existing values; 1000 has no sessions at all:

```json
{
  "featureFlags": {},
  "feeds": [
    {
      "exchangeId": 24,
      "expiryTime": "5.000000000s",
      "exponent": -5,
      "feedId": 2166,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [59, 84, 41],
          "minPublishers": 2,
          "session": "REGULAR",
          "stalePriceFilter": {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 60
          }
        }
      ],
      "metadata": { "asset_type": "equity" },
      "minPublishers": 2,
      "state": "STABLE",
      "symbol": "Equity.KR.000660/KRW"
    },
    {
      "exchangeId": 29,
      "expiryTime": "5.000000000s",
      "exponent": -5,
      "feedId": 1990,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [24, 84],
          "minPublishers": 2,
          "session": "REGULAR"
        }
      ],
      "metadata": { "asset_type": "equity" },
      "minPublishers": 2,
      "state": "COMING_SOON",
      "symbol": "Equity.JP.4506/JPY"
    },
    {
      "exchangeId": 29,
      "expiryTime": "5.000000000s",
      "exponent": -5,
      "feedId": 3337,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [24, 84],
          "minPublishers": 2,
          "session": "REGULAR",
          "stalePriceFilter": {
            "movedPriceThresholdBps": 2.0,
            "stalenessThresholdSecs": 3600
          }
        }
      ],
      "metadata": { "asset_type": "equity" },
      "minPublishers": 2,
      "state": "STABLE",
      "symbol": "Equity.JP.285A/JPY"
    },
    {
      "exchangeId": 29,
      "expiryTime": "5.000000000s",
      "exponent": -5,
      "feedId": 3338,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "allowedPublisherIds": [20, 41],
          "minPublishers": 2,
          "session": "REGULAR",
          "stalePriceFilter": {
            "movedPriceThresholdBps": 2.0,
            "stalenessThresholdSecs": 3600,
            "windowSecs": 45
          }
        }
      ],
      "metadata": { "asset_type": "equity" },
      "minPublishers": 2,
      "state": "STABLE",
      "symbol": "Equity.JP.4062/JPY"
    },
    {
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 1000,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [],
      "metadata": { "asset_type": "crypto" },
      "minPublishers": 1,
      "state": "STABLE",
      "symbol": "Crypto.BTC/USD"
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tools/edit-config/tests/test_config_ops.py`:

```python
from edit_config_lib.config_ops import (
    SetStaleFilter,
    ClearStaleFilter,
    DEFAULT_MOVED_PRICE_THRESHOLD_BPS,
    DEFAULT_STALENESS_THRESHOLD_SECS,
    DEFAULT_WINDOW_SECS,
)

STALE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stale_sample.json"


@pytest.fixture
def stale_feeds():
    return json.loads(STALE_FIXTURE_PATH.read_text(encoding="utf-8"))["feeds"]


def _regular(feed):
    return get_session(feed, "REGULAR")


class TestSetStaleFilterCreate:
    def test_creates_with_all_defaults(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1990)
        changes, warnings = SetStaleFilter().apply(feed)
        assert len(changes) == 1
        c = changes[0]
        assert c.location == "REGULAR"
        assert c.field == "stalePriceFilter"
        assert c.before is None
        assert c.after == {
            "movedPriceThresholdBps": DEFAULT_MOVED_PRICE_THRESHOLD_BPS,
            "stalenessThresholdSecs": DEFAULT_STALENESS_THRESHOLD_SECS,
            "windowSecs": DEFAULT_WINDOW_SECS,
        }
        assert _regular(feed)["stalePriceFilter"] == c.after
        assert warnings == []

    def test_creates_with_partial_override(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1990)
        changes, _ = SetStaleFilter(window_secs=120).apply(feed)
        assert changes[0].after == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 120,
        }

    def test_bps_stored_as_float(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1990)
        changes, _ = SetStaleFilter(moved_price_threshold_bps=2).apply(feed)
        value = changes[0].after["movedPriceThresholdBps"]
        assert isinstance(value, float) and value == 2.0

    def test_session_missing_on_feed_errors(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1000)  # no marketSchedules
        with pytest.raises(OpError, match="does not exist"):
            SetStaleFilter().apply(feed)


class TestSetStaleFilterPatch:
    def test_patches_only_named_key(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 2166)
        changes, _ = SetStaleFilter(window_secs=120).apply(feed)
        assert len(changes) == 1
        c = changes[0]
        assert c.field == "stalePriceFilter.windowSecs"
        assert (c.before, c.after) == (60, 120)
        assert _regular(feed)["stalePriceFilter"] == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 120,
        }

    def test_identical_values_are_noop(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 2166)
        changes, warnings = SetStaleFilter(
            moved_price_threshold_bps=0.5,
            staleness_threshold_secs=10800,
            window_secs=60,
        ).apply(feed)
        assert changes == []

    def test_bare_op_on_existing_filter_is_noop(self, stale_feeds):
        # No value flags: defaults must NOT overwrite a complete existing
        # filter, even one whose values differ from the defaults.
        feed = feed_by_id(stale_feeds, 3338)
        changes, _ = SetStaleFilter().apply(feed)
        assert changes == []
        assert _regular(feed)["stalePriceFilter"] == {
            "movedPriceThresholdBps": 2.0,
            "stalenessThresholdSecs": 3600,
            "windowSecs": 45,
        }

    def test_bare_op_completes_a_partial_filter(self, stale_feeds):
        # 3337 is missing windowSecs; a bare op fills only the gap from the
        # defaults and preserves the two values already on the feed.
        feed = feed_by_id(stale_feeds, 3337)
        changes, _ = SetStaleFilter().apply(feed)
        assert len(changes) == 1
        assert changes[0].field == "stalePriceFilter"
        assert changes[0].after == {
            "movedPriceThresholdBps": 2.0,
            "stalenessThresholdSecs": 3600,
            "windowSecs": DEFAULT_WINDOW_SECS,
        }

    def test_partial_existing_filter_is_rewritten_whole(self, stale_feeds):
        # 3337 has no windowSecs; the missing key can't be patched in place,
        # so the whole object is rewritten (defaults fill the gap).
        feed = feed_by_id(stale_feeds, 3337)
        changes, _ = SetStaleFilter(window_secs=90).apply(feed)
        assert len(changes) == 1
        c = changes[0]
        assert c.field == "stalePriceFilter"
        assert c.before == {
            "movedPriceThresholdBps": 2.0,
            "stalenessThresholdSecs": 3600,
        }
        assert c.after == {
            "movedPriceThresholdBps": 2.0,
            "stalenessThresholdSecs": 3600,
            "windowSecs": 90,
        }


class TestSetStaleFilterValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"moved_price_threshold_bps": 0},
            {"moved_price_threshold_bps": -1.0},
            {"staleness_threshold_secs": 0},
            {"window_secs": -5},
        ],
    )
    def test_non_positive_values_error(self, stale_feeds, kwargs):
        feed = feed_by_id(stale_feeds, 1990)
        with pytest.raises(OpError, match="must be > 0"):
            SetStaleFilter(**kwargs).apply(feed)

    def test_non_numeric_value_errors(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1990)
        with pytest.raises(OpError, match="must be numeric"):
            SetStaleFilter(window_secs="sixty").apply(feed)

    def test_fractional_seconds_error(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1990)
        with pytest.raises(OpError, match="whole number of seconds"):
            SetStaleFilter(window_secs=1.5).apply(feed)

    def test_staleness_below_window_warns(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1990)
        changes, warnings = SetStaleFilter(
            staleness_threshold_secs=30, window_secs=60
        ).apply(feed)
        assert len(changes) == 1
        assert len(warnings) == 1
        assert "shorter than the observation window" in warnings[0].message


class TestClearStaleFilter:
    def test_removes_filter(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 2166)
        changes, warnings = ClearStaleFilter().apply(feed)
        assert len(changes) == 1
        c = changes[0]
        assert c.field == "stalePriceFilter"
        assert c.after is None
        assert c.before["windowSecs"] == 60
        assert "stalePriceFilter" not in _regular(feed)
        assert warnings == []

    def test_missing_filter_warns_and_makes_no_change(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1990)
        changes, warnings = ClearStaleFilter().apply(feed)
        assert changes == []
        assert len(warnings) == 1
        assert "nothing to clear" in warnings[0].message


class TestStaleFilterSessionScope:
    def test_session_none_is_rejected(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 2166)
        with pytest.raises(OpError, match="session=NONE is invalid"):
            SetStaleFilter(session="NONE").apply(feed)

    def test_session_all_targets_every_session(self, stale_feeds):
        feed = feed_by_id(stale_feeds, 1990)
        changes, _ = SetStaleFilter(session="ALL").apply(feed)
        assert [c.location for c in changes] == ["REGULAR"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py -q`
Expected: FAIL at import — `ImportError: cannot import name 'SetStaleFilter'`.

- [ ] **Step 4: Rename the session-resolution helper**

In `config_ops.py`, replace `_resolve_publisher_sessions` (line 121) with a generic version, so the `NONE` error message is accurate for both publisher ops and the new filter ops:

```python
def _resolve_session_names(
    feed: dict, session: str | None, what: str = "publisher lists"
) -> list[str]:
    """Session names a session-scoped op targets.

    Publisher lists and stalePriceFilter both live ONLY in marketSchedules
    entries in the new config format, so session=NONE is invalid here. `what`
    names the field in the error message.
    """
    feed_id = feed["feedId"]
    if session is None:
        return ["REGULAR"]
    if session == "ALL":
        return [s["session"] for s in feed.get("marketSchedules", [])]
    if session == "NONE":
        raise OpError(
            f"feed {feed_id}: session=NONE is invalid — {what} live only in "
            f"marketSchedules entries in the new config format"
        )
    if session in SESSION_NAMES:
        return [session]
    raise OpError(f"unknown session value: {session!r}")
```

Update both call sites — line 168 (`AddPublisher.apply`) and line 254 (`RemovePublisher.apply`) — from `_resolve_publisher_sessions(feed, self.session)` to `_resolve_session_names(feed, self.session)`.

- [ ] **Step 5: Add the constants and the two ops**

Add the constants near the top of `config_ops.py`, under `US_EQUITY_SYMBOL_PREFIX`:

```python
# stalePriceFilter defaults — the values carried by the feeds already running
# the filter in production (2166, 3337, 3338).
DEFAULT_MOVED_PRICE_THRESHOLD_BPS = 0.5
DEFAULT_STALENESS_THRESHOLD_SECS = 10800
DEFAULT_WINDOW_SECS = 60

STALE_FILTER_KEYS: tuple[str, ...] = (
    "movedPriceThresholdBps",
    "stalenessThresholdSecs",
    "windowSecs",
)
```

Append both ops at the end of `config_ops.py`:

```python
def _stale_window_warning(
    feed_id: int, symbol: str, location: str, spf: dict
) -> list[Warning]:
    """Warn when the staleness horizon is shorter than the observation window."""
    staleness = spf.get("stalenessThresholdSecs")
    window = spf.get("windowSecs")
    if staleness is None or window is None or staleness >= window:
        return []
    return [
        Warning(
            feed_id=feed_id,
            symbol=symbol,
            message=(
                f"feed {feed_id} {location}: stalenessThresholdSecs="
                f"{staleness} < windowSecs={window} — staleness horizon "
                f"shorter than the observation window"
            ),
        )
    ]


@dataclass
class SetStaleFilter:
    """Create or patch a session entry's stalePriceFilter object.

    Values left as None take the module defaults when the filter is being
    created, and are left untouched when one already exists — so
    `--set-stale-filter --window-secs 120` retunes one knob without restating
    the other two. An existing filter missing any of the three keys is
    rewritten whole (a key that isn't in the file can't be patched in place).
    """

    moved_price_threshold_bps: float | None = None
    staleness_threshold_secs: int | None = None
    window_secs: int | None = None
    session: str | None = None

    def _requested(self) -> dict[str, Any]:
        """Validated, type-normalized {config key: value} for the knobs set."""
        raw = (
            ("movedPriceThresholdBps", self.moved_price_threshold_bps),
            ("stalenessThresholdSecs", self.staleness_threshold_secs),
            ("windowSecs", self.window_secs),
        )
        out: dict[str, Any] = {}
        for key, value in raw:
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise OpError(f"{key} must be numeric; got {value!r}")
            if value <= 0:
                raise OpError(f"{key} must be > 0; got {value}")
            if key == "movedPriceThresholdBps":
                out[key] = float(value)
            else:
                if float(value) != int(value):
                    raise OpError(
                        f"{key} must be a whole number of seconds; got {value}"
                    )
                out[key] = int(value)
        return out

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        requested = self._requested()

        for name in _resolve_session_names(feed, self.session, "stalePriceFilter"):
            sess = get_session(feed, name)
            if sess is None:
                raise OpError(
                    f"feed {feed_id}: session {name!r} does not exist on this feed"
                )
            current = sess.get("stalePriceFilter")
            complete = isinstance(current, dict) and all(
                k in current for k in STALE_FILTER_KEYS
            )

            if not complete:
                # Create, or rewrite a partial/malformed object whole. Existing
                # values win over defaults; requested values win over both.
                merged: dict[str, Any] = {
                    "movedPriceThresholdBps": DEFAULT_MOVED_PRICE_THRESHOLD_BPS,
                    "stalenessThresholdSecs": DEFAULT_STALENESS_THRESHOLD_SECS,
                    "windowSecs": DEFAULT_WINDOW_SECS,
                }
                before = dict(current) if isinstance(current, dict) else None
                if before is not None:
                    merged.update(before)
                merged.update(requested)
                if merged == before:
                    continue
                sess["stalePriceFilter"] = merged
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location=name,
                        field="stalePriceFilter",
                        before=before,
                        after=dict(merged),
                    )
                )
                warnings.extend(_stale_window_warning(feed_id, symbol, name, merged))
                continue

            touched = False
            for key in STALE_FILTER_KEYS:
                if key not in requested or current[key] == requested[key]:
                    continue
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location=name,
                        field=f"stalePriceFilter.{key}",
                        before=current[key],
                        after=requested[key],
                    )
                )
                current[key] = requested[key]
                touched = True
            if touched:
                warnings.extend(_stale_window_warning(feed_id, symbol, name, current))

        return changes, warnings


@dataclass
class ClearStaleFilter:
    """Remove the stalePriceFilter object from targeted session entries.

    The inverse of SetStaleFilter. A session with no filter is a no-op with a
    warning, mirroring how ClearRic reports "nothing to clear".
    """

    session: str | None = None

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        for name in _resolve_session_names(feed, self.session, "stalePriceFilter"):
            sess = get_session(feed, name)
            if sess is None:
                raise OpError(
                    f"feed {feed_id}: session {name!r} does not exist on this feed"
                )
            current = sess.get("stalePriceFilter")
            if not isinstance(current, dict):
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id} {name}: no stalePriceFilter — "
                            f"nothing to clear"
                        ),
                    )
                )
                continue
            del sess["stalePriceFilter"]
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location=name,
                    field="stalePriceFilter",
                    before=dict(current),
                    after=None,
                )
            )

        return changes, warnings
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite for regressions**

Run: `python3 -m pytest tools/edit-config/tests/ -q`
Expected: PASS — the helper rename must not have broken the publisher-op tests.

- [ ] **Step 8: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_ops.py tools/edit-config/tests/test_config_ops.py tools/edit-config/tests/fixtures/stale_sample.json
git commit -m "feat(edit-config): SetStaleFilter and ClearStaleFilter operations"
```

---

### Task 4: Text applier and diff rendering

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_editor.py:488-500` (imports), `:509-527` (helpers), `:589-616` (session branch of `_apply_one_change`)
- Modify: `tools/edit-config/edit_config_lib/config_diff.py:26-70`
- Test: `tools/edit-config/tests/test_config_editor.py`, `tools/edit-config/tests/test_config_diff.py`

**Interfaces:**

- Consumes: Task 2's four surgery helpers; Task 3's `Change` contract and `STALE_FILTER_KEYS`.
- Produces: `apply_changes(raw, changes)` handling `stalePriceFilter` create / rewrite / patch / delete; `render_diff` hunks for the same.

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_editor.py`:

```python
STALE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stale_sample.json"


def _stale_raw():
    return STALE_FIXTURE_PATH.read_text(encoding="utf-8")


def _session_of(raw_text, feed_id):
    feed = next(
        f for f in json.loads(raw_text)["feeds"] if f["feedId"] == feed_id
    )
    return feed["marketSchedules"][0]


class TestApplyStaleFilter:
    def test_create_inserts_object_as_last_key(self):
        raw = _stale_raw()
        feeds = json.loads(raw)["feeds"]
        feed = next(f for f in feeds if f["feedId"] == 1990)
        changes, _ = SetStaleFilter().apply(feed)
        out = apply_changes(raw, changes)
        assert _session_of(out, 1990)["stalePriceFilter"] == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 60,
        }
        # Untouched feeds stay byte-identical.
        assert '"symbol": "Equity.KR.000660/KRW"' in out

    def test_patch_rewrites_single_key(self):
        raw = _stale_raw()
        feeds = json.loads(raw)["feeds"]
        feed = next(f for f in feeds if f["feedId"] == 2166)
        changes, _ = SetStaleFilter(window_secs=120).apply(feed)
        out = apply_changes(raw, changes)
        spf = _session_of(out, 2166)["stalePriceFilter"]
        assert spf == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 120,
        }

    def test_patch_of_decimal_key_is_not_truncated(self):
        raw = _stale_raw()
        feeds = json.loads(raw)["feeds"]
        feed = next(f for f in feeds if f["feedId"] == 2166)
        changes, _ = SetStaleFilter(moved_price_threshold_bps=1.25).apply(feed)
        out = apply_changes(raw, changes)
        assert _session_of(out, 2166)["stalePriceFilter"][
            "movedPriceThresholdBps"
        ] == 1.25

    def test_whole_object_rewrite(self):
        raw = _stale_raw()
        feeds = json.loads(raw)["feeds"]
        feed = next(f for f in feeds if f["feedId"] == 3337)
        changes, _ = SetStaleFilter(window_secs=90).apply(feed)
        out = apply_changes(raw, changes)
        assert _session_of(out, 3337)["stalePriceFilter"] == {
            "movedPriceThresholdBps": 2.0,
            "stalenessThresholdSecs": 3600,
            "windowSecs": 90,
        }

    def test_clear_removes_object(self):
        raw = _stale_raw()
        feeds = json.loads(raw)["feeds"]
        feed = next(f for f in feeds if f["feedId"] == 2166)
        changes, _ = ClearStaleFilter().apply(feed)
        out = apply_changes(raw, changes)
        session = _session_of(out, 2166)
        assert "stalePriceFilter" not in session
        assert session["minPublishers"] == 2

    def test_create_then_clear_round_trips_to_valid_json(self):
        raw = _stale_raw()
        feeds = json.loads(raw)["feeds"]
        feed = next(f for f in feeds if f["feedId"] == 1990)
        created, _ = SetStaleFilter().apply(feed)
        out = apply_changes(raw, created)
        feed2 = next(f for f in json.loads(out)["feeds"] if f["feedId"] == 1990)
        cleared, _ = ClearStaleFilter().apply(feed2)
        final = apply_changes(out, cleared)
        assert json.loads(final) == json.loads(raw)
```

`test_config_editor.py` uses mid-file import blocks (see lines 470-471, 792-794) rather than one block at the top — follow that house style and put this block immediately above the appended tests:

```python
from edit_config_lib.config_editor import apply_changes
from edit_config_lib.config_ops import SetStaleFilter, ClearStaleFilter
```

`json`, `Path` and `pytest` are already imported at the top of the file.

Append to `tools/edit-config/tests/test_config_diff.py`:

```python
class TestStaleFilterDiff:
    def _change(self, **kw):
        base = dict(
            feed_id=2166,
            symbol="Equity.KR.000660/KRW",
            location="REGULAR",
            field="stalePriceFilter",
            before=None,
            after=None,
        )
        base.update(kw)
        return Change(**base)

    def test_create_hunk(self):
        c = self._change(
            after={
                "movedPriceThresholdBps": 0.5,
                "stalenessThresholdSecs": 10800,
                "windowSecs": 60,
            }
        )
        out = render_diff([c])
        assert "@@ feedId 2166 (Equity.KR.000660/KRW), session REGULAR @@" in out
        assert "-      (absent)" in out
        assert '+      "stalePriceFilter": { "movedPriceThresholdBps": 0.5, ' in out

    def test_clear_hunk(self):
        c = self._change(before={"windowSecs": 60}, after=None)
        out = render_diff([c])
        assert "+      (removed)" in out

    def test_single_key_patch_hunk(self):
        c = self._change(field="stalePriceFilter.windowSecs", before=60, after=120)
        out = render_diff([c])
        assert '-      "windowSecs": 60,' in out
        assert '+      "windowSecs": 120,' in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py -k Stale tools/edit-config/tests/test_config_diff.py -k Stale -q`
Expected: FAIL — `RuntimeError: unsupported session field 'stalePriceFilter'` from the applier, and wrong hunk text from the diff.

- [ ] **Step 3: Implement the applier branches**

In `config_editor.py`, extend the surgery import block (currently lines 488-500) with the new helpers:

```python
from edit_config_lib.config_text_surgery import (
    find_feed_block,
    find_session_block,
    find_metadata_block,
    find_publisher_array_span,
    find_int_field_span,
    find_string_field_span,
    find_ric_identifier_spans,
    find_marketschedules_end,
    find_object_field_span,
    find_number_field_span,
    insert_field_after_open_brace,
    insert_field_before_session,
    insert_field_before_close_brace,
    delete_scalar_field,
    delete_object_field,
)
```

Add `STALE_FILTER_KEYS` to the existing `from edit_config_lib.config_ops import ...` block near the top of the file (the one importing `AddPublisher`, `RemovePublisher`, …).

Add these helpers next to `_set_session_min_publishers`:

```python
def _format_stale_value(key: str, value) -> str:
    """Render one stalePriceFilter value: float for bps, int for the seconds."""
    if key == "movedPriceThresholdBps":
        return repr(float(value))
    return str(int(value))


def _render_stale_filter_object(spf: dict, indent: str) -> str:
    """Render the `{…}` of a stalePriceFilter, pretty-printed to match the file.

    `indent` is the indentation of the field's own line; keys sit two spaces
    deeper and the closing brace lines up with `indent`.
    """
    inner = indent + "  "
    body = ",\n".join(
        f'{inner}"{key}": {_format_stale_value(key, spf[key])}'
        for key in STALE_FILTER_KEYS
    )
    return "{\n" + body + "\n" + indent + "}"


def _session_field_indent(sblock: str) -> str:
    """Indentation of the fields inside a session entry's block."""
    m = re.search(r'\n(\s*)"', sblock)
    return m.group(1) if m else "  "
```

In `_apply_one_change`, extend the session-scoped chain (currently ending with the `marketSchedule` branch and an `else: raise RuntimeError`) with two new branches placed before the `else`:

```python
    elif change.field == "stalePriceFilter":
        indent = _session_field_indent(sblock)
        span = find_object_field_span(sblock, "stalePriceFilter")
        if change.after is None:
            new_sblock = delete_object_field(sblock, "stalePriceFilter")
        elif span is None:
            field = '"stalePriceFilter": ' + _render_stale_filter_object(
                change.after, indent
            )
            new_sblock = insert_field_before_close_brace(sblock, field)
        else:
            rendered = _render_stale_filter_object(change.after, indent)
            new_sblock = sblock[: span[0]] + rendered + sblock[span[1] :]
    elif change.field.startswith("stalePriceFilter."):
        key = change.field.split(".", 1)[1]
        span = find_object_field_span(sblock, "stalePriceFilter")
        if span is None:
            raise RuntimeError("stalePriceFilter object not found in session entry")
        fblock = sblock[span[0] : span[1]]
        fspan = find_number_field_span(fblock, key)
        if fspan is None:
            raise RuntimeError(f"stalePriceFilter.{key} not found in session entry")
        new_fblock = (
            fblock[: fspan[0]]
            + _format_stale_value(key, change.after)
            + fblock[fspan[1] :]
        )
        new_sblock = sblock[: span[0]] + new_fblock + sblock[span[1] :]
```

- [ ] **Step 4: Implement the diff rendering**

In `config_diff.py`, import `STALE_FILTER_KEYS` alongside `Change`, and insert this branch at the top of `_value_lines`, before the `exchangeId`/`marketSchedule` branch:

```python
    if change.field.startswith("stalePriceFilter"):
        if change.field == "stalePriceFilter":

            def _fmt(val):
                body = ", ".join(
                    f'"{k}": {val[k]}' for k in STALE_FILTER_KEYS if k in val
                )
                return f'      "stalePriceFilter": {{ {body} }},'

            if change.after is None:  # clear
                return _fmt(change.before), "      (removed)"
            if change.before is None:  # create
                return "      (absent)", _fmt(change.after)
            return _fmt(change.before), _fmt(change.after)
        key = change.field.split(".", 1)[1]
        return f'      "{key}": {change.before},', f'      "{key}": {change.after},'
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py tools/edit-config/tests/test_config_diff.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite for regressions**

Run: `python3 -m pytest tools/edit-config/tests/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/edit_config_lib/config_diff.py tools/edit-config/tests/test_config_editor.py tools/edit-config/tests/test_config_diff.py
git commit -m "feat(edit-config): apply and render stalePriceFilter changes"
```

---

### Task 5: CLI flags and YAML spec wiring

**Files:**

- Modify: `tools/edit-config/edit_config.py:123-180` (argparse)
- Modify: `tools/edit-config/edit_config_lib/config_editor.py:70-81` (`_OP_FLAGS`), `:111-113` (`_BOOL_OP_FLAGS`), `:190-256` (`build_op_from_args`), `:262-281` (spec tables), `:332-384` (spec parsing)
- Test: `tools/edit-config/tests/test_edit_config_cli.py`

**Interfaces:**

- Consumes: Task 3's op constructors, Task 4's applier.
- Produces: CLI flags `--set-stale-filter`, `--clear-stale-filter`, `--moved-price-bps`, `--staleness-secs`, `--window-secs`; YAML ops `set_stale_filter` / `clear_stale_filter` with optional keys `moved_price_threshold_bps`, `staleness_threshold_secs`, `window_secs`.

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_edit_config_cli.py`:

```python
STALE_FIXTURE = Path(__file__).parent / "fixtures" / "stale_sample.json"


@pytest.fixture
def stale_config(tmp_path):
    dst = tmp_path / "stale.json"
    shutil.copy(STALE_FIXTURE, dst)
    return dst


def _spf(path, feed_id):
    feeds = json.loads(Path(path).read_text(encoding="utf-8"))["feeds"]
    feed = next(f for f in feeds if f["feedId"] == feed_id)
    return feed["marketSchedules"][0].get("stalePriceFilter")


class TestStaleFilterCli:
    def test_dry_run_reports_change_and_writes_nothing(self, stale_config):
        before = stale_config.read_text(encoding="utf-8")
        result = run_cli(
            ["--config", str(stale_config), "--set-stale-filter", "--feed-id", "1990"]
        )
        assert result.returncode == 0
        assert "[DRY RUN]" in result.stdout
        assert "@@ feedId 1990" in result.stdout
        assert stale_config.read_text(encoding="utf-8") == before

    def test_apply_creates_filter(self, stale_config):
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--set-stale-filter",
                "--feed-id",
                "1990",
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 1990) == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 60,
        }

    def test_apply_patches_single_knob(self, stale_config):
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--set-stale-filter",
                "--window-secs",
                "120",
                "--feed-id",
                "2166",
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 2166) == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 120,
        }

    def test_apply_clear(self, stale_config):
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--clear-stale-filter",
                "--feed-id",
                "2166",
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 2166) is None

    def test_value_flag_without_set_flag_errors(self, stale_config):
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--add-publisher",
                "80",
                "--window-secs",
                "120",
                "--feed-id",
                "1990",
            ]
        )
        assert result.returncode == 1
        assert "--window-secs" in result.stdout + result.stderr

    def test_feed_ids_from_csv(self, stale_config, tmp_path):
        csv_path = tmp_path / "batch.csv"
        csv_path.write_text(
            "1990, 2026-07-24, jp-equities\n2166, 2026-07-24, kr-equities\n",
            encoding="utf-8",
        )
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--set-stale-filter",
                "--feed-ids-from",
                str(csv_path),
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 1990) is not None

    def test_yaml_spec(self, stale_config, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "version: 1\n"
            "operations:\n"
            "  - op: set_stale_filter\n"
            "    feed_id: 1990\n"
            "    session: REGULAR\n"
            "    window_secs: 90\n"
            "  - op: clear_stale_filter\n"
            "    feed_id: 2166\n"
            "    session: REGULAR\n",
            encoding="utf-8",
        )
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--from-spec",
                str(spec),
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 1990)["windowSecs"] == 90
        assert _spf(stale_config, 2166) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_edit_config_cli.py -k Stale -q`
Expected: FAIL — `error: unrecognized arguments: --set-stale-filter`.

- [ ] **Step 3: Add the argparse flags**

In `tools/edit-config/edit_config.py`, add to the mutually exclusive `op_group` (after `--remove-ric`):

```python
    op_group.add_argument(
        "--set-stale-filter",
        action="store_true",
        help=(
            "Create or patch the session-level stalePriceFilter. Values come "
            "from --moved-price-bps / --staleness-secs / --window-secs; when "
            "the session has no filter yet, omitted values use the defaults "
            "(0.5 / 10800 / 60)."
        ),
    )
    op_group.add_argument(
        "--clear-stale-filter",
        action="store_true",
        help="Remove the stalePriceFilter object from targeted sessions.",
    )
```

And add the three value flags next to `--from-csv`:

```python
    p.add_argument(
        "--moved-price-bps",
        type=float,
        help="stalePriceFilter.movedPriceThresholdBps (with --set-stale-filter).",
    )
    p.add_argument(
        "--staleness-secs",
        type=int,
        help="stalePriceFilter.stalenessThresholdSecs (with --set-stale-filter).",
    )
    p.add_argument(
        "--window-secs",
        type=int,
        help="stalePriceFilter.windowSecs (with --set-stale-filter).",
    )
```

- [ ] **Step 4: Wire the ops into `build_op_from_args`**

In `config_editor.py`, import both ops in the existing `from edit_config_lib.config_ops import (...)` block, then:

Extend `_OP_FLAGS` with `"set_stale_filter"` and `"clear_stale_filter"`, and `_BOOL_OP_FLAGS` with the same two names (both are `store_true`, so `_flag_set` must not read `False` as "selected"):

```python
_BOOL_OP_FLAGS = frozenset(
    {
        "set_ric_mapping",
        "set_ric",
        "remove_ric",
        "remove_exchange_id",
        "set_stale_filter",
        "clear_stale_filter",
    }
)
```

Directly after `name = selected[0]` in `build_op_from_args`, add the value-flag guard:

```python
    stale_value_flags = [
        flag
        for flag in ("moved_price_bps", "staleness_secs", "window_secs")
        if getattr(args, flag, None) is not None
    ]
    if stale_value_flags and name != "set_stale_filter":
        names = ", ".join("--" + f.replace("_", "-") for f in stale_value_flags)
        raise ValueError(f"{names} require --set-stale-filter")
```

Add the two dispatch branches alongside the other ops (after the `remove_ric` branch):

```python
    elif name == "set_stale_filter":
        op = SetStaleFilter(
            moved_price_threshold_bps=args.moved_price_bps,
            staleness_threshold_secs=args.staleness_secs,
            window_secs=args.window_secs,
            session=args.session,
        )
    elif name == "clear_stale_filter":
        op = ClearStaleFilter(session=args.session)
```

- [ ] **Step 5: Wire the ops into the YAML spec path**

Still in `config_editor.py`, add both ops to `_OP_REQUIRED_FIELDS` (no required fields):

```python
    "set_stale_filter": set(),
    "clear_stale_filter": set(),
```

Add an optional-fields table below `_OP_REQUIRED_FIELDS` — without it `_validate_keys` rejects the value keys as unknown:

```python
# Op fields that are allowed but not required (create/patch semantics).
_OP_OPTIONAL_FIELDS = {
    "set_stale_filter": {
        "moved_price_threshold_bps",
        "staleness_threshold_secs",
        "window_secs",
    },
}
```

Update `_validate_keys` to consult it:

```python
def _validate_keys(entry: dict, op_name: str) -> None:
    allowed = (
        {"op"}
        | _TARGETING_KEYS
        | _SCOPE_KEYS
        | _OP_REQUIRED_FIELDS[op_name]
        | _OP_OPTIONAL_FIELDS.get(op_name, set())
    )
    extras = set(entry.keys()) - allowed
    if extras:
        raise ValueError(f"unknown key(s) in op {op_name!r}: {sorted(extras)}")
```

Add the branches to `_build_op_from_yaml_entry`, before the final `raise AssertionError`:

```python
    if op_name == "set_stale_filter":
        return SetStaleFilter(
            moved_price_threshold_bps=entry.get("moved_price_threshold_bps"),
            staleness_threshold_secs=entry.get("staleness_threshold_secs"),
            window_secs=entry.get("window_secs"),
            session=session,
        )
    if op_name == "clear_stale_filter":
        return ClearStaleFilter(session=session)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_edit_config_cli.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite for regressions**

Run: `python3 -m pytest tools/edit-config/tests/ -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/edit-config/edit_config.py tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_edit_config_cli.py
git commit -m "feat(edit-config): --set-stale-filter / --clear-stale-filter CLI and spec wiring"
```

---

### Task 6: Docs and end-to-end verification on the real config

**Files:**

- Modify: `docs/edit_config.md` (new op section after the `--remove-ric` section at line 197; targeting note in `## --feed-ids-from file format` at line 290; op list at line 37)
- Modify: `CLAUDE.md` (the `tools/edit-config/edit_config.py` row of the Scripts table)

**Interfaces:**

- Consumes: everything from Tasks 1–5. Produces no code.

- [ ] **Step 1: Verify against the real config with a dry run**

```bash
python3 tools/edit-config/edit_config.py --config lazer_staleness.json \
  --set-stale-filter --feed-ids-from jp_kr.csv --session REGULAR
```

Expected: `Validation: PASS (0 errors, 0 warnings)`, `Summary: 33 changes`, and `[DRY RUN] No changes written.` The 33 comes from 36 feeds in `jp_kr.csv` minus the three (2166, 3337, 3338) that already hold exactly the default values. If the count differs, stop and diagnose before continuing.

- [ ] **Step 2: Verify an apply on a scratch copy**

Shell variables do not persist between tool calls, so each step below spells the scratch path out in full. Substitute your own session scratchpad directory if it differs.

```bash
cp lazer_staleness.json /tmp/stale_check.json
python3 tools/edit-config/edit_config.py --config /tmp/stale_check.json \
  --set-stale-filter --feed-ids-from jp_kr.csv --session REGULAR --apply --no-backup
python3 -c "import json; json.load(open('/tmp/stale_check.json')); print('valid json')"
python3 tools/config-linter/config_linter.py --config /tmp/stale_check.json
```

Expected: `Wrote 33 changes`, `valid json`, and a linter run with no new errors relative to a baseline run against `lazer_staleness.json`.

- [ ] **Step 3: Confirm the pre-existing feeds are untouched**

```bash
python3 - <<'EOF'
import json
before = {f["feedId"]: f for f in json.load(open("lazer_staleness.json"))["feeds"]}
after = {f["feedId"]: f for f in json.load(open("/tmp/stale_check.json"))["feeds"]}
for fid in (2166, 3337, 3338):
    assert before[fid] == after[fid], f"feed {fid} changed"
print("2166 / 3337 / 3338 unchanged")
changed = [fid for fid in before if before[fid] != after[fid]]
print(f"{len(changed)} feeds changed")
EOF
```

Expected: `2166 / 3337 / 3338 unchanged` and `33 feeds changed`.

- [ ] **Step 4: Verify the clear round-trip on the scratch copy**

```bash
python3 tools/edit-config/edit_config.py --config /tmp/stale_check.json \
  --clear-stale-filter --feed-ids-from jp_kr.csv --session REGULAR --apply --no-backup
python3 - <<'EOF'
import json
before = {f["feedId"]: f for f in json.load(open("lazer_staleness.json"))["feeds"]}
after = {f["feedId"]: f for f in json.load(open("/tmp/stale_check.json"))["feeds"]}
diff = [fid for fid in before if before[fid] != after[fid]]
print("feeds differing after clear:", sorted(diff))
EOF
```

Expected: `feeds differing after clear: [2166, 3337, 3338]` — the 33 created filters are gone, and the three pre-existing ones were removed by the clear (they were the only ones the clear had to act on beyond the new set). This confirms create and clear are inverses at the JSON level.

- [ ] **Step 5: Document the operations**

In `docs/edit_config.md`, add to the operations list at line 37:

```markdown
| `--set-stale-filter` | Create or patch the session-level `stalePriceFilter` |
| `--clear-stale-filter` | Remove `stalePriceFilter` from targeted sessions |
```

(Match the surrounding table's column layout exactly — check the existing rows before inserting.)

Add a section after the `--remove-ric` section (line 197):

````markdown
### `--set-stale-filter` / `--clear-stale-filter` — session staleness guard

`stalePriceFilter` lives inside a `marketSchedules` session entry and carries three
knobs:

```json
"stalePriceFilter": {
  "movedPriceThresholdBps": 0.5,
  "stalenessThresholdSecs": 10800,
  "windowSecs": 60
}
```

Values come from `--moved-price-bps`, `--staleness-secs` and `--window-secs`.

**Create** — on a session with no filter, omitted values take the defaults
`0.5 / 10800 / 60`:

```bash
python3 tools/edit-config/edit_config.py --config lazer_staleness.json \
  --set-stale-filter --feed-ids-from jp_kr.csv --session REGULAR
```

**Patch** — on a session that already has one, only the values you pass are
rewritten; the rest are left alone, so a fleet-wide retune of a single knob is one
command:

```bash
python3 tools/edit-config/edit_config.py --config lazer_staleness.json \
  --set-stale-filter --window-secs 120 --feed-ids-from jp_kr.csv --apply
```

**Clear** — the inverse:

```bash
python3 tools/edit-config/edit_config.py --config lazer_staleness.json \
  --clear-stale-filter --feed-id 2166 --apply
```

Scope follows the publisher ops: `--session` defaults to `REGULAR`, `ALL` fans out
over every session on the feed, and `NONE` is an error (the filter has no
feed-level home). Non-numeric or non-positive values are errors;
`stalenessThresholdSecs < windowSecs` is a warning.

In a YAML spec, every value key is optional and patch semantics still apply:

```yaml
version: 1
operations:
  - op: set_stale_filter
    feed_id: "1990,2023,2043-2064"
    session: REGULAR
    window_secs: 120
  - op: clear_stale_filter
    feed_id: 3337
    session: REGULAR
```
````

In the `## --feed-ids-from file format` section (line 290), add:

```markdown
A path ending in `.csv` is read as a CSV: only column 1 of each row is parsed, so the
repo's benchmark CSVs (`feed_id,date,mode` — `jp_kr.csv`, `kr.csv`, `hk_41.csv`, …)
work as targeting files directly. A first row whose column 1 is not a feed ID is
treated as a header and skipped. Every other path, and stdin (`-`), keeps the strict
`N` / `A-B` grammar.
```

- [ ] **Step 6: Update the CLAUDE.md scripts table**

In the Scripts table, extend the `tools/edit-config/edit_config.py` Purpose cell to end with `, set/clear session stalePriceFilter`. Keep the row's pipe alignment consistent with its neighbors — prettier will reflow it in the next step.

- [ ] **Step 7: Run pre-commit and the full suite**

```bash
pre-commit run --files docs/edit_config.md CLAUDE.md \
  tools/edit-config/edit_config.py \
  tools/edit-config/edit_config_lib/config_ops.py \
  tools/edit-config/edit_config_lib/config_editor.py \
  tools/edit-config/edit_config_lib/config_diff.py \
  tools/edit-config/edit_config_lib/config_selector.py \
  tools/edit-config/edit_config_lib/config_text_surgery.py \
  tools/edit-config/tests/test_config_ops.py \
  tools/edit-config/tests/test_config_editor.py \
  tools/edit-config/tests/test_config_diff.py \
  tools/edit-config/tests/test_config_selector.py \
  tools/edit-config/tests/test_config_text_surgery.py \
  tools/edit-config/tests/test_edit_config_cli.py \
  tools/edit-config/tests/fixtures/stale_sample.json
python3 -m pytest tools/edit-config/tests/ -q
```

Expected: all hooks pass (re-stage any files black or prettier reformats), full suite green.

- [ ] **Step 8: Commit**

```bash
git add docs/edit_config.md CLAUDE.md
git commit -m "docs(edit-config): document stalePriceFilter ops and CSV targeting"
```

---

## Definition of done

- [ ] `--set-stale-filter` and `--clear-stale-filter` work from the CLI and `--from-spec`
- [ ] `--feed-ids-from jp_kr.csv` parses without preprocessing
- [ ] Dry run against `lazer_staleness.json` reports 33 changes, 0 errors
- [ ] Scratch-copy apply: `json.load` succeeds, config linter passes, feeds 2166 / 3337 / 3338 unchanged
- [ ] Full `python3 -m pytest tools/edit-config/tests/` green
- [ ] `pre-commit run --files <changed files>` clean
