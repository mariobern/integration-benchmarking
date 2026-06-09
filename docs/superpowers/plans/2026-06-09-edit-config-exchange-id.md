# edit_config.py exchangeId add/remove Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--add-exchange-id` and `--remove-exchange-id` operations to `edit_config.py` that set/clear a feed's top-level `exchangeId` and keep each session's `marketSchedule` string consistent with the exchange (strip on add, restore on remove).

**Architecture:** Two new operation dataclasses in `config_ops.py` (capturing the resolved `exchanges[]` data at construction time, exactly like `SetRicMapping`/`SetRicFromResolver`), one new formatting-preserving text primitive (`delete_scalar_field`) plus reuse of existing insert/update primitives, applier branches in `config_editor.py` keyed on `field`, and CLI/YAML wiring that builds an `exchanges_by_id` map once from `data["exchanges"]`.

**Tech Stack:** Python 3.12, pytest, argparse, PyYAML. Tool lives in `tools/edit-config/`; tests in `tools/edit-config/tests/`. Run tests from the repo root with `python3 -m pytest`.

---

## Background for the implementer

- Read the spec: `docs/superpowers/specs/2026-06-09-edit-config-exchange-id-design.md`.
- The config is a JSON file (~5 MB) with a top-level `exchanges[]` array and a `feeds[]` array.
- An **exchange** entry: `{"exchangeId": 1, "name": "...", "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY", "sessions": [{"session": "REGULAR", "marketSchedule": "America/New_York;..."}, ...]}`.
- A **feed** may carry a top-level `"exchangeId": N`. When it does, its session entries (`marketSchedules[]`) carry **no** `marketSchedule` string — the schedule is inherited from the exchange. When it does not, each session entry carries its own `marketSchedule` string.
- The editor never mutates parsed JSON and re-serializes; it splices the **raw text** to preserve formatting. `Change` records (feed_id, symbol, location, field, before, after, index) describe edits; `config_editor.apply_changes` applies them to raw text via `config_text_surgery` helpers.
- **Change conventions:** `before is None` (and `after` set) = *insert a field that was absent*. This plan adds the mirror: `after is None` (and `before` set) = *delete the field*.

Run the full existing suite once before starting to confirm a green baseline:

```bash
cd /Users/mariobernardi/Documents/GitHub/integration-benchmarking
python3 -m pytest tools/edit-config/tests/ -q
```
Expected: all pass.

---

## File structure

- **Modify** `tools/edit-config/edit_config_lib/config_text_surgery.py` — add `delete_scalar_field`.
- **Modify** `tools/edit-config/edit_config_lib/config_ops.py` — add `ExchangeInfo`, `build_exchanges_by_id`, `asset_class_matches`, `AddExchangeId`, `RemoveExchangeId`.
- **Modify** `tools/edit-config/edit_config_lib/config_editor.py` — applier branches; `build_op_from_args`/`parse_yaml_spec` gain `exchanges_by_id`; YAML op tables.
- **Modify** `tools/edit-config/edit_config_lib/config_diff.py` — render exchangeId/marketSchedule insert & delete hunks.
- **Modify** `tools/edit-config/edit_config.py` — new CLI flags; build `exchanges_by_id` in `main()`.
- **Create** `tools/edit-config/tests/fixtures/after_with_exchanges.json` — fixture with an `exchanges[]` array.
- **Modify** test files: `test_config_text_surgery.py`, `test_config_ops.py`, `test_config_editor.py`, `test_config_diff.py`, `test_edit_config_cli.py`.
- **Modify** `docs/edit_config.md`, `CLAUDE.md`.

---

## Task 1: `delete_scalar_field` text primitive

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_text_surgery.py`
- Test: `tools/edit-config/tests/test_config_text_surgery.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_text_surgery.py`:

```python
from edit_config_lib.config_text_surgery import delete_scalar_field


class TestDeleteScalarField:
    def test_deletes_int_field_and_trailing_comma(self):
        block = '{\n  "exchangeId": 1,\n  "feedId": 922\n}'
        out = delete_scalar_field(block, "exchangeId")
        assert out == '{\n  "feedId": 922\n}'

    def test_deletes_string_field(self):
        block = (
            '{\n  "marketSchedule": "America/New_York;0930-1600",\n'
            '  "session": "REGULAR"\n}'
        )
        out = delete_scalar_field(block, "marketSchedule")
        assert out == '{\n  "session": "REGULAR"\n}'

    def test_string_value_with_escaped_quote(self):
        block = '{\n  "k": "a\\"b",\n  "session": "REGULAR"\n}'
        out = delete_scalar_field(block, "k")
        assert out == '{\n  "session": "REGULAR"\n}'

    def test_absent_key_returns_unchanged(self):
        block = '{\n  "session": "REGULAR"\n}'
        assert delete_scalar_field(block, "exchangeId") == block

    def test_only_named_key_removed(self):
        block = '{\n  "exchangeId": 1,\n  "expiryTime": "5s",\n  "feedId": 5\n}'
        out = delete_scalar_field(block, "exchangeId")
        assert '"expiryTime"' in out and '"feedId"' in out
        assert '"exchangeId"' not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_text_surgery.py::TestDeleteScalarField -v`
Expected: FAIL with `ImportError: cannot import name 'delete_scalar_field'`.

- [ ] **Step 3: Implement `delete_scalar_field`**

Append to `tools/edit-config/edit_config_lib/config_text_surgery.py`:

```python
def delete_scalar_field(block: str, key: str) -> str:
    """Delete the entire physical line of a top-level int or quoted-string
    field `"key": <value>,` from `block`, including its trailing comma.

    Matches from the newline that precedes the field's indentation through the
    trailing comma, so the field's whole line is removed and surrounding
    formatting stays intact. Assumes the field is NOT the last field in its
    object (so it carries a trailing comma) — true for the feed-level
    `exchangeId` (always followed by more feed fields) and a session's
    `marketSchedule` (always followed by `"session"`). Returns `block`
    unchanged when `key` is absent.
    """
    pattern = re.compile(
        rf'\n[ \t]*"{re.escape(key)}"\s*:\s*'
        rf'(?:"[^"\\]*(?:\\.[^"\\]*)*"|-?\d+)[ \t]*,'
    )
    m = pattern.search(block)
    if m is None:
        return block
    return block[: m.start()] + block[m.end() :]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_text_surgery.py::TestDeleteScalarField -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
git commit -m "feat(edit-config): add delete_scalar_field text primitive"
```

---

## Task 2: Exchange data helpers + test fixture

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_ops.py`
- Create: `tools/edit-config/tests/fixtures/after_with_exchanges.json`
- Test: `tools/edit-config/tests/test_config_ops.py`

- [ ] **Step 1: Create the fixture**

Create `tools/edit-config/tests/fixtures/after_with_exchanges.json` with this exact content:

```json
{
  "exchanges": [
    {
      "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
      "exchangeId": 1,
      "name": "NASDAQ Test Consolidated",
      "sessions": [
        { "session": "REGULAR", "marketSchedule": "America/New_York;0930-1600;R" },
        { "session": "PRE_MARKET", "marketSchedule": "America/New_York;0400-0930;P" },
        { "session": "POST_MARKET", "marketSchedule": "America/New_York;1600-2000;A" },
        { "session": "OVER_NIGHT", "marketSchedule": "America/New_York;2000-0400;O" }
      ]
    },
    {
      "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
      "exchangeId": 21,
      "name": "Hong Kong Test",
      "sessions": [
        { "session": "REGULAR", "marketSchedule": "Asia/Hong_Kong;0930-1600;H" }
      ]
    }
  ],
  "feeds": [
    {
      "feedId": 100,
      "symbol": "Equity.US.AAA/USD",
      "state": "COMING_SOON",
      "minPublishers": 1,
      "metadata": { "asset_type": "equity", "name": "AAA" },
      "marketSchedules": [
        {
          "allowedPublisherIds": [1, 2, 3],
          "marketSchedule": "America/New_York;0930-1600;OLD-R",
          "session": "REGULAR"
        },
        {
          "allowedPublisherIds": [1, 2],
          "marketSchedule": "America/New_York;0400-0930;OLD-P",
          "session": "PRE_MARKET"
        },
        {
          "allowedPublisherIds": [1, 2],
          "marketSchedule": "America/New_York;1600-2000;OLD-A",
          "session": "POST_MARKET"
        },
        {
          "allowedPublisherIds": [1],
          "marketSchedule": "America/New_York;2000-0400;OLD-O",
          "session": "OVER_NIGHT"
        }
      ]
    },
    {
      "exchangeId": 1,
      "feedId": 200,
      "symbol": "Equity.US.BBB/USD",
      "state": "STABLE",
      "minPublishers": 1,
      "metadata": { "asset_type": "equity", "name": "BBB" },
      "marketSchedules": [
        { "allowedPublisherIds": [1, 2, 3], "session": "REGULAR" },
        { "allowedPublisherIds": [1, 2], "session": "PRE_MARKET" },
        { "allowedPublisherIds": [1, 2], "session": "POST_MARKET" },
        { "allowedPublisherIds": [1], "session": "OVER_NIGHT" }
      ]
    },
    {
      "exchangeId": 1,
      "feedId": 300,
      "symbol": "Equity.US.CCC/USD",
      "state": "STABLE",
      "minPublishers": 1,
      "metadata": { "asset_type": "equity", "name": "CCC" },
      "marketSchedules": [
        {
          "allowedPublisherIds": [1, 2, 3],
          "marketSchedule": "America/New_York;0930-1600;STALE-R",
          "session": "REGULAR"
        },
        {
          "allowedPublisherIds": [1],
          "marketSchedule": "America/New_York;2000-0400;STALE-O",
          "session": "OVER_NIGHT"
        }
      ]
    },
    {
      "feedId": 400,
      "symbol": "Equity.US.DDD/USD",
      "state": "COMING_SOON",
      "minPublishers": 1,
      "metadata": { "asset_type": "equity", "name": "DDD" },
      "marketSchedules": [
        {
          "allowedPublisherIds": [1, 2],
          "marketSchedule": "America/New_York;0930-1600;OLD-R",
          "session": "REGULAR"
        },
        {
          "allowedPublisherIds": [1],
          "marketSchedule": "America/New_York;2000-0400;OLD-O",
          "session": "OVER_NIGHT"
        }
      ]
    },
    {
      "feedId": 500,
      "symbol": "Crypto.XYZ/USD",
      "state": "STABLE",
      "minPublishers": 1,
      "metadata": { "asset_type": "crypto", "name": "XYZ" },
      "marketSchedules": [
        {
          "allowedPublisherIds": [1, 2],
          "marketSchedule": "Etc/UTC;0000-2400;OLD-R",
          "session": "REGULAR"
        }
      ]
    }
  ]
}
```

Verify it parses:

Run: `python3 -c "import json; json.load(open('tools/edit-config/tests/fixtures/after_with_exchanges.json'))"`
Expected: no output, exit 0.

- [ ] **Step 2: Write the failing tests**

Append to `tools/edit-config/tests/test_config_ops.py`:

```python
from edit_config_lib.config_ops import (
    ExchangeInfo,
    build_exchanges_by_id,
    asset_class_matches,
)

EX_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_with_exchanges.json"


@pytest.fixture
def ex_config():
    return json.loads(EX_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def exchanges_by_id(ex_config):
    return build_exchanges_by_id(ex_config["exchanges"])


@pytest.fixture
def ex_feeds(ex_config):
    return ex_config["feeds"]


class TestExchangeHelpers:
    def test_build_maps_by_id(self, exchanges_by_id):
        assert set(exchanges_by_id) == {1, 21}
        ex1 = exchanges_by_id[1]
        assert isinstance(ex1, ExchangeInfo)
        assert ex1.name == "NASDAQ Test Consolidated"
        assert ex1.asset_class == "EXCHANGE_ASSET_CLASS_EQUITY"
        assert set(ex1.sessions) == {"REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"}
        assert ex1.sessions["REGULAR"] == "America/New_York;0930-1600;R"

    def test_build_hk_single_session(self, exchanges_by_id):
        assert set(exchanges_by_id[21].sessions) == {"REGULAR"}

    def test_empty_list_yields_empty_map(self):
        assert build_exchanges_by_id([]) == {}

    def test_asset_class_matches_equity(self):
        assert asset_class_matches("EXCHANGE_ASSET_CLASS_EQUITY", "equity") is True

    def test_asset_class_mismatch(self):
        assert asset_class_matches("EXCHANGE_ASSET_CLASS_EQUITY", "crypto") is False

    def test_asset_class_blank_does_not_flag(self):
        assert asset_class_matches("", "equity") is True
        assert asset_class_matches("EXCHANGE_ASSET_CLASS_EQUITY", "") is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py::TestExchangeHelpers -v`
Expected: FAIL with `ImportError: cannot import name 'ExchangeInfo'`.

- [ ] **Step 4: Implement the helpers**

Add to `tools/edit-config/edit_config_lib/config_ops.py` (after the `SESSION_NAMES`/`US_EQUITY_SYMBOL_PREFIX` constants near the top):

```python
@dataclass(frozen=True)
class ExchangeInfo:
    """A resolved entry from the config's top-level `exchanges[]` array.

    `sessions` maps a session name (REGULAR/PRE_MARKET/...) to its
    `marketSchedule` string — the calendar a feed inherits when it carries
    this exchange's id.
    """

    exchange_id: int
    name: str
    asset_class: str
    sessions: dict[str, str]


def build_exchanges_by_id(exchanges: list[dict]) -> dict[int, ExchangeInfo]:
    """Index the raw `exchanges[]` list by exchangeId. The array is sparse
    (some ids are not yet defined); only present ids appear in the map."""
    out: dict[int, ExchangeInfo] = {}
    for ex in exchanges:
        eid = ex.get("exchangeId")
        if eid is None:
            continue
        sessions: dict[str, str] = {}
        for s in ex.get("sessions", []):
            name = s.get("session")
            sched = s.get("marketSchedule")
            if name is not None and sched is not None:
                sessions[name] = sched
        out[eid] = ExchangeInfo(
            exchange_id=eid,
            name=ex.get("name", ""),
            asset_class=ex.get("assetClass", ""),
            sessions=sessions,
        )
    return out


def asset_class_matches(exchange_asset_class: str, feed_asset_type: str) -> bool:
    """True if the exchange's assetClass plausibly matches the feed's
    asset_type. Blanks on either side are treated as a match (nothing to
    compare -> don't warn). Comparison strips the `EXCHANGE_ASSET_CLASS_`
    prefix and lowercases, so `EXCHANGE_ASSET_CLASS_EQUITY` matches `equity`.
    """
    if not exchange_asset_class or not feed_asset_type:
        return True
    prefix = "EXCHANGE_ASSET_CLASS_"
    token = exchange_asset_class
    if token.startswith(prefix):
        token = token[len(prefix):]
    return token.lower() == feed_asset_type.lower()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py::TestExchangeHelpers -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_ops.py tools/edit-config/tests/test_config_ops.py tools/edit-config/tests/fixtures/after_with_exchanges.json
git commit -m "feat(edit-config): exchange data helpers + exchanges fixture"
```

---

## Task 3: `AddExchangeId` operation

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_ops.py`
- Test: `tools/edit-config/tests/test_config_ops.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_ops.py`:

```python
from edit_config_lib.config_ops import AddExchangeId


def _sessions_with_schedule(feed):
    return [
        s["session"] for s in feed["marketSchedules"] if "marketSchedule" in s
    ]


class TestAddExchangeId:
    def test_add_inserts_id_and_strips_all_schedule_strings(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 100)  # no exchangeId, strings on all 4 sessions
        op = AddExchangeId(exchange_id=1, exchange=exchanges_by_id[1])
        changes, warns = op.apply(feed)
        # exchangeId inserted (before=None) + 4 schedule deletions.
        id_changes = [c for c in changes if c.field == "exchangeId"]
        sched_changes = [c for c in changes if c.field == "marketSchedule"]
        assert len(id_changes) == 1
        assert id_changes[0].before is None and id_changes[0].after == 1
        assert len(sched_changes) == 4
        assert all(c.after is None for c in sched_changes)
        assert feed["exchangeId"] == 1
        assert _sessions_with_schedule(feed) == []
        assert warns == []

    def test_same_id_with_stale_strings_strips_them_no_id_change(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 300)  # exchangeId 1 already + 2 stale strings
        op = AddExchangeId(exchange_id=1, exchange=exchanges_by_id[1])
        changes, warns = op.apply(feed)
        assert [c for c in changes if c.field == "exchangeId"] == []
        assert len(changes) == 2  # both stale strings removed
        assert _sessions_with_schedule(feed) == []

    def test_same_id_already_inherited_is_noop(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 200)  # exchangeId 1, no strings
        op = AddExchangeId(exchange_id=1, exchange=exchanges_by_id[1])
        changes, warns = op.apply(feed)
        assert changes == []

    def test_reassignment_warns(self, exchanges_by_id):
        # A single-REGULAR feed already on exchange 1, reassigned to 21.
        # (Exchange 21 only defines REGULAR, so coverage holds.)
        feed = {
            "exchangeId": 1,
            "feedId": 999,
            "symbol": "Equity.HK.X/HKD",
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [{"allowedPublisherIds": [1], "session": "REGULAR"}],
        }
        op = AddExchangeId(exchange_id=21, exchange=exchanges_by_id[21])
        changes, warns = op.apply(feed)
        assert feed["exchangeId"] == 21
        assert any("reassigning exchangeId 1 -> 21" in w.message for w in warns)

    def test_session_not_covered_is_error(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 400)  # has OVER_NIGHT; exchange 21 lacks it
        op = AddExchangeId(exchange_id=21, exchange=exchanges_by_id[21])
        with pytest.raises(OpError, match="does not define session"):
            op.apply(feed)

    def test_asset_class_mismatch_warns_but_applies(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 500)  # crypto feed, REGULAR only
        op = AddExchangeId(exchange_id=1, exchange=exchanges_by_id[1])
        changes, warns = op.apply(feed)
        assert feed["exchangeId"] == 1
        assert any("does not match exchange" in w.message for w in warns)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py::TestAddExchangeId -v`
Expected: FAIL with `ImportError: cannot import name 'AddExchangeId'`.

- [ ] **Step 3: Implement `AddExchangeId`**

Add to `tools/edit-config/edit_config_lib/config_ops.py` (after the existing op classes, e.g. after `SetState`):

```python
@dataclass
class AddExchangeId:
    """Assign `exchange_id` to a feed and strip each session's now-redundant
    `marketSchedule` string (the feed inherits the exchange's calendar).

    `exchange` is the pre-resolved ExchangeInfo for `exchange_id`, captured at
    construction time (the id is fixed per invocation).
    """

    exchange_id: int
    exchange: ExchangeInfo

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        changes: list[Change] = []
        warnings: list[Warning] = []
        schedules = feed.get("marketSchedules", [])

        # 1. Session coverage (hard error): every feed session must exist on
        #    the exchange, else stripping its string leaves nothing to inherit.
        uncovered = [
            s.get("session")
            for s in schedules
            if s.get("session") not in self.exchange.sessions
        ]
        if uncovered:
            raise OpError(
                f"feed {feed_id}: exchange {self.exchange_id} "
                f"({self.exchange.name!r}) does not define session(s) "
                f"{uncovered} that this feed has — cannot inherit a schedule"
            )

        # 2. Asset-class check (warning only).
        feed_asset = feed.get("metadata", {}).get("asset_type", "")
        if not asset_class_matches(self.exchange.asset_class, feed_asset):
            warnings.append(
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f"feed {feed_id}: asset_type {feed_asset!r} does not "
                        f"match exchange {self.exchange_id} assetClass "
                        f"{self.exchange.asset_class!r}"
                    ),
                )
            )

        # 3. exchangeId field change (+ reassignment warning).
        current = feed.get("exchangeId")
        if current != self.exchange_id:
            if current is not None:
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id}: reassigning exchangeId "
                            f"{current} -> {self.exchange_id}"
                        ),
                    )
                )
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location="top_level",
                    field="exchangeId",
                    before=current,
                    after=self.exchange_id,
                )
            )
            feed["exchangeId"] = self.exchange_id

        # 4. Strip per-session marketSchedule strings (inheritance).
        for s in schedules:
            if "marketSchedule" in s:
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location=s["session"],
                        field="marketSchedule",
                        before=s["marketSchedule"],
                        after=None,
                    )
                )
                del s["marketSchedule"]

        return changes, warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py::TestAddExchangeId -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): AddExchangeId op with schedule stripping"
```

---

## Task 4: `RemoveExchangeId` operation

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_ops.py`
- Test: `tools/edit-config/tests/test_config_ops.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_ops.py`:

```python
from edit_config_lib.config_ops import RemoveExchangeId


class TestRemoveExchangeId:
    def test_removes_id_and_restores_all_schedules(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 200)  # exchangeId 1, no strings, 4 sessions
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        changes, warns = op.apply(feed)
        id_changes = [c for c in changes if c.field == "exchangeId"]
        sched_changes = [c for c in changes if c.field == "marketSchedule"]
        assert len(id_changes) == 1 and id_changes[0].after is None
        assert len(sched_changes) == 4
        # Restored strings come from the exchange definition.
        reg = get_session(feed, "REGULAR")
        assert reg["marketSchedule"] == "America/New_York;0930-1600;R"
        assert "exchangeId" not in feed
        assert warns == []

    def test_no_exchange_id_warns_noop(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 100)  # no exchangeId
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        changes, warns = op.apply(feed)
        assert changes == []
        assert any("no exchangeId to remove" in w.message for w in warns)

    def test_unknown_current_id_is_error(self, exchanges_by_id):
        feed = {
            "exchangeId": 7,  # not in {1, 21}
            "feedId": 888,
            "symbol": "Equity.US.ZZZ/USD",
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [{"allowedPublisherIds": [1], "session": "REGULAR"}],
        }
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        with pytest.raises(OpError, match="not defined in exchanges"):
            op.apply(feed)

    def test_session_not_covered_is_error(self, exchanges_by_id):
        feed = {
            "exchangeId": 21,  # HK: REGULAR only
            "feedId": 889,
            "symbol": "Equity.HK.Y/HKD",
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [
                {"allowedPublisherIds": [1], "session": "REGULAR"},
                {"allowedPublisherIds": [1], "session": "OVER_NIGHT"},
            ],
        }
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        with pytest.raises(OpError, match="cannot restore"):
            op.apply(feed)

    def test_existing_schedule_string_left_untouched(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 300)  # exchangeId 1, REGULAR+OVER_NIGHT both have stale strings
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        changes, warns = op.apply(feed)
        # id removed; both sessions already had strings -> no marketSchedule changes.
        assert [c for c in changes if c.field == "exchangeId"] == [changes[0]]
        assert [c for c in changes if c.field == "marketSchedule"] == []
        assert get_session(feed, "REGULAR")["marketSchedule"] == "America/New_York;0930-1600;STALE-R"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py::TestRemoveExchangeId -v`
Expected: FAIL with `ImportError: cannot import name 'RemoveExchangeId'`.

- [ ] **Step 3: Implement `RemoveExchangeId`**

Add to `tools/edit-config/edit_config_lib/config_ops.py` (after `AddExchangeId`):

```python
@dataclass
class RemoveExchangeId:
    """Remove a feed's `exchangeId` and restore each session's
    `marketSchedule` string from that exchange's definition.

    `exchanges_by_id` is the whole map because different feeds in a batch may
    reference different exchanges; the schedule to restore comes from the
    feed's current id.
    """

    exchanges_by_id: dict[int, ExchangeInfo]

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        warnings: list[Warning] = []

        current = feed.get("exchangeId")
        if current is None:
            warnings.append(
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=f"feed {feed_id}: no exchangeId to remove",
                )
            )
            return [], warnings

        exchange = self.exchanges_by_id.get(current)
        if exchange is None:
            raise OpError(
                f"feed {feed_id}: current exchangeId {current} is not defined "
                f"in exchanges[] — cannot restore schedules"
            )

        schedules = feed.get("marketSchedules", [])
        uncovered = [
            s.get("session")
            for s in schedules
            if s.get("session") not in exchange.sessions
        ]
        if uncovered:
            raise OpError(
                f"feed {feed_id}: exchange {current} ({exchange.name!r}) does "
                f"not define session(s) {uncovered} — cannot restore a schedule"
            )

        changes: list[Change] = [
            Change(
                feed_id=feed_id,
                symbol=symbol,
                location="top_level",
                field="exchangeId",
                before=current,
                after=None,
            )
        ]
        del feed["exchangeId"]

        for s in schedules:
            if "marketSchedule" not in s:
                sched = exchange.sessions[s["session"]]
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location=s["session"],
                        field="marketSchedule",
                        before=None,
                        after=sched,
                    )
                )
                s["marketSchedule"] = sched

        return changes, warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_ops.py::TestRemoveExchangeId -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_ops.py tools/edit-config/tests/test_config_ops.py
git commit -m "feat(edit-config): RemoveExchangeId op with schedule restore"
```

---

## Task 5: Applier support in `config_editor.py`

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_editor.py`
- Test: `tools/edit-config/tests/test_config_editor.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_editor.py`:

```python
import json as _json
from pathlib import Path as _Path

from edit_config_lib.config_ops import Change as _Change

_EX_FIXTURE = _Path(__file__).parent / "fixtures" / "after_with_exchanges.json"


def _raw_ex_fixture():
    return _EX_FIXTURE.read_text(encoding="utf-8")


def _feed_in(data, fid):
    return next(f for f in data["feeds"] if f["feedId"] == fid)


class TestApplyExchangeChanges:
    def test_insert_exchange_id(self):
        raw = _raw_ex_fixture()
        ch = _Change(
            feed_id=100, symbol="Equity.US.AAA/USD",
            location="top_level", field="exchangeId", before=None, after=1,
        )
        out = apply_changes(raw, [ch])
        data = _json.loads(out)
        assert _feed_in(data, 100)["exchangeId"] == 1

    def test_update_exchange_id(self):
        raw = _raw_ex_fixture()
        ch = _Change(
            feed_id=200, symbol="Equity.US.BBB/USD",
            location="top_level", field="exchangeId", before=1, after=21,
        )
        out = apply_changes(raw, [ch])
        assert _feed_in(_json.loads(out), 200)["exchangeId"] == 21

    def test_delete_exchange_id(self):
        raw = _raw_ex_fixture()
        ch = _Change(
            feed_id=200, symbol="Equity.US.BBB/USD",
            location="top_level", field="exchangeId", before=1, after=None,
        )
        out = apply_changes(raw, [ch])
        assert "exchangeId" not in _feed_in(_json.loads(out), 200)

    def test_delete_session_schedule(self):
        raw = _raw_ex_fixture()
        ch = _Change(
            feed_id=100, symbol="Equity.US.AAA/USD",
            location="REGULAR", field="marketSchedule",
            before="America/New_York;0930-1600;OLD-R", after=None,
        )
        out = apply_changes(raw, [ch])
        reg = next(s for s in _feed_in(_json.loads(out), 100)["marketSchedules"]
                   if s["session"] == "REGULAR")
        assert "marketSchedule" not in reg

    def test_insert_session_schedule(self):
        raw = _raw_ex_fixture()
        ch = _Change(
            feed_id=200, symbol="Equity.US.BBB/USD",
            location="REGULAR", field="marketSchedule",
            before=None, after="America/New_York;0930-1600;R",
        )
        out = apply_changes(raw, [ch])
        reg = next(s for s in _feed_in(_json.loads(out), 200)["marketSchedules"]
                   if s["session"] == "REGULAR")
        assert reg["marketSchedule"] == "America/New_York;0930-1600;R"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py::TestApplyExchangeChanges -v`
Expected: FAIL — `RuntimeError: unsupported top-level field 'exchangeId'` (and similar for the session field).

- [ ] **Step 3: Wire the applier**

In `tools/edit-config/edit_config_lib/config_editor.py`:

a) Add `import json` near the top of the file (with the other stdlib imports, e.g. above `import fnmatch`).

b) Add `delete_scalar_field` to the `from edit_config_lib.config_text_surgery import (...)` block (the one that already imports `insert_field_before_session`).

c) In `_apply_one_change`, inside the `if change.location == "top_level":` block, add an `exchangeId` branch **before** the final `raise RuntimeError(...)`:

```python
        if change.field == "exchangeId":
            if change.after is None:
                return delete_scalar_field(block, "exchangeId")
            if change.before is None:
                return insert_field_after_open_brace(
                    block, f'"exchangeId": {change.after},'
                )
            span = find_int_field_span(block, "exchangeId")
            if span is None:
                raise RuntimeError("exchangeId field not found in feed block")
            return block[: span[0]] + str(change.after) + block[span[1] :]
```

d) In `_apply_one_change`, in the session-scoped section, extend the field dispatch to handle `marketSchedule`:

```python
    if change.field == "allowedPublisherIds":
        new_sblock = _set_session_publishers(sblock, change.after)
    elif change.field == "minPublishers":
        new_sblock = _set_session_min_publishers(sblock, change.after)
    elif change.field == "marketSchedule":
        if change.after is None:
            new_sblock = delete_scalar_field(sblock, "marketSchedule")
        else:
            new_sblock = insert_field_before_session(
                sblock, f'"marketSchedule": {json.dumps(change.after)},'
            )
    else:
        raise RuntimeError(f"unsupported session field {change.field!r}")
```

(`insert_field_after_open_brace` and `find_int_field_span` are already imported in this file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py::TestApplyExchangeChanges -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): apply exchangeId + marketSchedule field changes"
```

---

## Task 6: Diff rendering for exchangeId / marketSchedule

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_diff.py`
- Test: `tools/edit-config/tests/test_config_diff.py`

The generic `else` branch in `_value_lines` would render deletes/inserts as
`"exchangeId": None,`, which is misleading. Render `after is None` as a removed
line and `before is None` as an `(absent)` insert, for both new fields.

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_diff.py`:

```python
from edit_config_lib.config_ops import Change as _C
from edit_config_lib.config_diff import render_diff as _render


class TestExchangeDiff:
    def test_insert_exchange_id(self):
        c = _C(feed_id=100, symbol="Equity.US.AAA/USD", location="top_level",
               field="exchangeId", before=None, after=1)
        out = _render([c])
        assert "(absent)" in out
        assert '+      "exchangeId": 1,' in out

    def test_delete_exchange_id(self):
        c = _C(feed_id=200, symbol="Equity.US.BBB/USD", location="top_level",
               field="exchangeId", before=1, after=None)
        out = _render([c])
        assert '-      "exchangeId": 1,' in out
        assert "(removed)" in out

    def test_delete_market_schedule(self):
        c = _C(feed_id=100, symbol="Equity.US.AAA/USD", location="REGULAR",
               field="marketSchedule", before="America/New_York;0930-1600;R",
               after=None)
        out = _render([c])
        assert '-      "marketSchedule": "America/New_York;0930-1600;R",' in out
        assert "(removed)" in out

    def test_insert_market_schedule(self):
        c = _C(feed_id=200, symbol="Equity.US.BBB/USD", location="REGULAR",
               field="marketSchedule", before=None,
               after="America/New_York;0930-1600;R")
        out = _render([c])
        assert "(absent)" in out
        assert '+      "marketSchedule": "America/New_York;0930-1600;R",' in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_diff.py::TestExchangeDiff -v`
Expected: FAIL (assertion errors — generic rendering produces `None`/`repr` output).

- [ ] **Step 3: Implement diff rendering**

In `tools/edit-config/edit_config_lib/config_diff.py`, replace the `_value_lines`
function body's lead-in so it handles the two new fields with insert/delete
semantics. Insert these two blocks at the **top** of `_value_lines`, before the
existing `if change.before is None and change.field in (...)` block:

```python
    if change.field in ("exchangeId", "marketSchedule"):
        def _fmt(val):
            if change.field == "exchangeId":
                return f'      "exchangeId": {val},'
            return f'      "marketSchedule": "{val}",'
        if change.after is None:  # delete
            return _fmt(change.before), "      (removed)"
        if change.before is None:  # insert
            return "      (absent)", _fmt(change.after)
        return _fmt(change.before), _fmt(change.after)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_diff.py::TestExchangeDiff -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_diff.py tools/edit-config/tests/test_config_diff.py
git commit -m "feat(edit-config): render exchangeId/marketSchedule diff hunks"
```

---

## Task 7: CLI wiring + `build_op_from_args`

**Files:**
- Modify: `tools/edit-config/edit_config.py`
- Modify: `tools/edit-config/edit_config_lib/config_editor.py`
- Test: `tools/edit-config/tests/test_edit_config_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

Append to `tools/edit-config/tests/test_edit_config_cli.py`:

```python
EX_FIXTURE = Path(__file__).parent / "fixtures" / "after_with_exchanges.json"


@pytest.fixture
def ex_config_copy(tmp_path):
    dst = tmp_path / "after_with_exchanges.json"
    shutil.copy(EX_FIXTURE, dst)
    return dst


def _feed(data, fid):
    return next(f for f in data["feeds"] if f["feedId"] == fid)


class TestExchangeCli:
    def test_add_exchange_id_apply(self, ex_config_copy):
        r = run_cli(["--config", str(ex_config_copy),
                     "--add-exchange-id", "1", "--feed-id", "100", "--apply"])
        assert r.returncode == 0, r.stderr
        data = json.loads(ex_config_copy.read_text())
        feed = _feed(data, 100)
        assert feed["exchangeId"] == 1
        assert all("marketSchedule" not in s for s in feed["marketSchedules"])

    def test_remove_exchange_id_apply(self, ex_config_copy):
        r = run_cli(["--config", str(ex_config_copy),
                     "--remove-exchange-id", "--feed-id", "200", "--apply"])
        assert r.returncode == 0, r.stderr
        feed = _feed(json.loads(ex_config_copy.read_text()), 200)
        assert "exchangeId" not in feed
        reg = next(s for s in feed["marketSchedules"] if s["session"] == "REGULAR")
        assert reg["marketSchedule"] == "America/New_York;0930-1600;R"

    def test_unknown_exchange_id_errors(self, ex_config_copy):
        r = run_cli(["--config", str(ex_config_copy),
                     "--add-exchange-id", "99", "--feed-id", "100"])
        assert r.returncode == 1
        assert "not defined in exchanges" in (r.stdout + r.stderr)

    def test_session_not_covered_blocks_apply(self, ex_config_copy):
        # feed 400 has OVER_NIGHT; exchange 21 (HK) lacks it.
        r = run_cli(["--config", str(ex_config_copy),
                     "--add-exchange-id", "21", "--feed-id", "400", "--apply"])
        assert r.returncode == 1
        assert "does not define session" in (r.stdout + r.stderr)
        # nothing written
        feed = _feed(json.loads(ex_config_copy.read_text()), 400)
        assert "exchangeId" not in feed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_edit_config_cli.py::TestExchangeCli -v`
Expected: FAIL (argparse rejects unknown `--add-exchange-id`).

- [ ] **Step 3: Add the CLI flags**

In `tools/edit-config/edit_config.py`, inside `_build_parser`, add to the
mutually-exclusive `op_group` (next to `--set-state`):

```python
    op_group.add_argument("--add-exchange-id", type=int, dest="add_exchange_id")
    op_group.add_argument(
        "--remove-exchange-id", action="store_true", dest="remove_exchange_id"
    )
```

- [ ] **Step 4: Build the exchange map and pass it through `main()`**

In `tools/edit-config/edit_config.py`, add the import at the top:

```python
from edit_config_lib.config_ops import build_exchanges_by_id  # noqa: E402
```

In `main()`, right after `feeds = data["feeds"]`, build the map:

```python
    exchanges_by_id = build_exchanges_by_id(data.get("exchanges", []))
```

Then change the two op-build call sites to pass it:

```python
    if args.from_spec:
        plan = parse_yaml_spec(args.from_spec, exchanges_by_id)
        print(f"Parsing {args.from_spec}... {len(plan)} operations.")
    else:
        try:
            plan = build_op_from_args(args, exchanges_by_id)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
```

- [ ] **Step 5: Wire the ops in `build_op_from_args`**

In `tools/edit-config/edit_config_lib/config_editor.py`:

a) Extend the imports from `config_ops` to include the new names:

```python
from edit_config_lib.config_ops import (
    AddPublisher,
    RemovePublisher,
    SetMinPublishers,
    BumpMinPublishers,
    SetState,
    SetRicMapping,
    SetRicFromResolver,
    ResolvedRic,
    AddExchangeId,
    RemoveExchangeId,
    ExchangeInfo,
)
```

b) Add the two op names to `_OP_FLAGS`:

```python
_OP_FLAGS = (
    "add_publisher",
    "remove_publisher",
    "set_min_publishers",
    "bump_min_publishers",
    "set_state",
    "set_ric_mapping",
    "set_ric",
    "add_exchange_id",
    "remove_exchange_id",
)
```

c) Add `remove_exchange_id` to the store_true set:

```python
_BOOL_OP_FLAGS = frozenset({"set_ric_mapping", "set_ric", "remove_exchange_id"})
```

d) Change the `build_op_from_args` signature to accept the map:

```python
def build_op_from_args(
    args, exchanges_by_id: dict[int, ExchangeInfo] | None = None
) -> list[PlannedOp]:
```

and at the top of the function body add:

```python
    exchanges_by_id = exchanges_by_id or {}
```

e) Add two `elif` branches in the op chain after `elif name == "set_state":`:

```python
    elif name == "add_exchange_id":
        exchange = exchanges_by_id.get(args.add_exchange_id)
        if exchange is None:
            raise ValueError(
                f"--add-exchange-id {args.add_exchange_id}: exchange not "
                f"defined in exchanges[] (known ids: {sorted(exchanges_by_id)})"
            )
        op = AddExchangeId(exchange_id=args.add_exchange_id, exchange=exchange)
    elif name == "remove_exchange_id":
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
```

(These sit inside the block that runs after `filters = _build_filters_from_args(args)`, so both ops reuse standard targeting. They precede the final `else: raise AssertionError(...)`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_edit_config_cli.py::TestExchangeCli -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full suite (catch signature regressions)**

Run: `python3 -m pytest tools/edit-config/tests/ -q`
Expected: all pass (existing `build_op_from_args(args)` calls still work via the default param).

- [ ] **Step 8: Commit**

```bash
git add tools/edit-config/edit_config.py tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_edit_config_cli.py
git commit -m "feat(edit-config): --add-exchange-id / --remove-exchange-id CLI"
```

---

## Task 8: YAML spec support

**Files:**
- Modify: `tools/edit-config/edit_config_lib/config_editor.py`
- Test: `tools/edit-config/tests/test_config_editor.py`

- [ ] **Step 1: Write the failing tests**

Append to `tools/edit-config/tests/test_config_editor.py`:

```python
from edit_config_lib.config_ops import (
    build_exchanges_by_id as _build_ex,
    AddExchangeId as _AddEx,
    RemoveExchangeId as _RemEx,
)


def _ex_map():
    data = _json.loads(_EX_FIXTURE.read_text(encoding="utf-8"))
    return _build_ex(data["exchanges"])


class TestYamlExchangeOps:
    def test_add_exchange_id_from_yaml(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "version: 1\n"
            "operations:\n"
            "  - op: add_exchange_id\n"
            "    exchange_id: 1\n"
            "    feed_id: 100\n"
        )
        plan = parse_yaml_spec(str(spec), _ex_map())
        assert len(plan) == 1
        assert isinstance(plan[0].op, _AddEx)
        assert plan[0].op.exchange_id == 1

    def test_remove_exchange_id_from_yaml(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "version: 1\n"
            "operations:\n"
            "  - op: remove_exchange_id\n"
            "    feed_id: 200\n"
        )
        plan = parse_yaml_spec(str(spec), _ex_map())
        assert isinstance(plan[0].op, _RemEx)

    def test_unknown_exchange_id_from_yaml_raises(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "version: 1\n"
            "operations:\n"
            "  - op: add_exchange_id\n"
            "    exchange_id: 99\n"
            "    feed_id: 100\n"
        )
        with pytest.raises(ValueError, match="not defined in exchanges"):
            parse_yaml_spec(str(spec), _ex_map())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py::TestYamlExchangeOps -v`
Expected: FAIL — `parse_yaml_spec()` takes 1 positional arg / `unknown op 'add_exchange_id'`.

- [ ] **Step 3: Implement YAML support**

In `tools/edit-config/edit_config_lib/config_editor.py`:

a) Add the two ops to `_OP_REQUIRED_FIELDS`:

```python
_OP_REQUIRED_FIELDS = {
    "add_publisher": {"publisher_id"},
    "remove_publisher": {"publisher_id"},
    "set_min_publishers": {"value"},
    "bump_min_publishers": {"delta"},
    "set_state": {"value"},
    "set_ric_mapping": {"from_csv"},
    "add_exchange_id": {"exchange_id"},
    "remove_exchange_id": set(),
}
```

b) Change `_build_op_from_yaml_entry` to accept the map and handle the new ops.
Signature:

```python
def _build_op_from_yaml_entry(entry: dict, exchanges_by_id: dict):
```

Add these branches before the final `raise AssertionError`:

```python
    if op_name == "add_exchange_id":
        eid = entry["exchange_id"]
        exchange = exchanges_by_id.get(eid)
        if exchange is None:
            raise ValueError(
                f"add_exchange_id: exchange {eid} not defined in exchanges[] "
                f"(known ids: {sorted(exchanges_by_id)})"
            )
        return AddExchangeId(exchange_id=eid, exchange=exchange)
    if op_name == "remove_exchange_id":
        return RemoveExchangeId(exchanges_by_id=exchanges_by_id)
```

c) Change `parse_yaml_spec` to accept and thread the map:

```python
def parse_yaml_spec(path: str, exchanges_by_id: dict | None = None) -> list[PlannedOp]:
```

At the top of its body add `exchanges_by_id = exchanges_by_id or {}`, and update
the call inside the loop to `op = _build_op_from_yaml_entry(entry, exchanges_by_id)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_config_editor.py::TestYamlExchangeOps -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tools/edit-config/tests/ -q`
Expected: all pass (existing `parse_yaml_spec(str(...))` calls still work via the default param).

- [ ] **Step 6: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat(edit-config): YAML spec support for exchange ops"
```

---

## Task 9: End-to-end round-trip test

**Files:**
- Test: `tools/edit-config/tests/test_edit_config_cli.py`

Proves add-then-remove restores the per-session schedules and that the anomaly
feed (exchangeId + stale strings) is cleaned up.

- [ ] **Step 1: Write the round-trip tests**

Append to `class TestExchangeCli` in `tools/edit-config/tests/test_edit_config_cli.py`:

```python
    def test_add_then_remove_round_trips_schedules(self, ex_config_copy):
        # Add exchange 1 to feed 100 (strips its 4 OLD-* strings).
        r1 = run_cli(["--config", str(ex_config_copy),
                      "--add-exchange-id", "1", "--feed-id", "100", "--apply"])
        assert r1.returncode == 0, r1.stderr
        # Remove it again (restores strings from exchange 1's definition).
        r2 = run_cli(["--config", str(ex_config_copy),
                      "--remove-exchange-id", "--feed-id", "100", "--apply"])
        assert r2.returncode == 0, r2.stderr
        feed = _feed(json.loads(ex_config_copy.read_text()), 100)
        assert "exchangeId" not in feed
        by_session = {s["session"]: s.get("marketSchedule") for s in feed["marketSchedules"]}
        # Restored values come from exchange 1, not the original OLD-* strings.
        assert by_session["REGULAR"] == "America/New_York;0930-1600;R"
        assert by_session["OVER_NIGHT"] == "America/New_York;2000-0400;O"

    def test_add_cleans_up_anomaly_feed(self, ex_config_copy):
        # Feed 300 already has exchangeId 1 AND two stale strings.
        r = run_cli(["--config", str(ex_config_copy),
                     "--add-exchange-id", "1", "--feed-id", "300", "--apply"])
        assert r.returncode == 0, r.stderr
        feed = _feed(json.loads(ex_config_copy.read_text()), 300)
        assert feed["exchangeId"] == 1
        assert all("marketSchedule" not in s for s in feed["marketSchedules"])
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python3 -m pytest tools/edit-config/tests/test_edit_config_cli.py::TestExchangeCli -v`
Expected: PASS (6 tests total in the class now).

- [ ] **Step 3: Commit**

```bash
git add tools/edit-config/tests/test_edit_config_cli.py
git commit -m "test(edit-config): exchange add/remove round-trip + anomaly cleanup"
```

---

## Task 10: Documentation

**Files:**
- Modify: `docs/edit_config.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `docs/edit_config.md` operations table**

In `docs/edit_config.md`, add two rows to the Operations table (after the
`--set-state` row):

```markdown
| `--add-exchange-id N`                       | Assign exchange `N` and strip inherited `marketSchedule` strings |
| `--remove-exchange-id`                      | Remove `exchangeId` and restore `marketSchedule` strings from the exchange |
```

- [ ] **Step 2: Add an "Exchange inheritance" section to `docs/edit_config.md`**

Add this section near the end of `docs/edit_config.md` (before any trailing
"Examples"/"Notes" section, or at the end if none):

```markdown
## Exchange inheritance

A feed may carry a top-level `exchangeId` that points into the config's
top-level `exchanges[]` array. When it does, the feed **inherits** that
exchange's trading calendar: its session entries omit their own
`marketSchedule` string.

- `--add-exchange-id N` sets the feed's `exchangeId` to `N` and removes the
  now-redundant `marketSchedule` string from every session entry. If the feed
  already has a different `exchangeId`, the op reassigns it and warns.
- `--remove-exchange-id` clears the `exchangeId` and restores each session's
  `marketSchedule` string by copying it from the exchange definition.

Validation:

- Adding an `exchangeId` not present in `exchanges[]` is an error. The array is
  sparse; ids the team has not yet defined simply error until they are added.
- If the feed has a session the exchange does not define (e.g. an `OVER_NIGHT`
  session against an exchange that only defines `REGULAR`), both add and remove
  error — there would be no schedule to inherit or restore for that session.
- An exchange whose `assetClass` does not match the feed's `metadata.asset_type`
  produces a warning, not an error.

These ops target whole feeds (use `--feed-id`, `--symbol-pattern`, etc.). Like
the other edit ops, they skip `INACTIVE` feeds — reactivate with `--set-state`
first. They are also available in YAML specs as `add_exchange_id`
(`exchange_id:` required) and `remove_exchange_id`.
```

- [ ] **Step 3: Update `CLAUDE.md`**

In `CLAUDE.md`, update the `edit_config.py` row in the Scripts table — extend its
description to mention exchange ids. Change the existing cell:

```markdown
| `tools/edit-config/edit_config.py`     | Surgical editor: add/remove publishers, set minPublishers, set state, set RIC identifiers, add/remove exchangeId (schedule inheritance) | `python3 tools/edit-config/edit_config.py --config after.json --add-publisher 80 --feed-id 1000-1050`  | [docs/edit_config.md](docs/edit_config.md)                               |
```

Then update the "New config format (session-only publishers)" gotcha bullet at
the end of `CLAUDE.md` by appending this sentence to it:

```markdown
`edit_config.py` also manages the feed-level `exchangeId` and the per-session `marketSchedule` inheritance it implies (`--add-exchange-id` strips inherited schedule strings; `--remove-exchange-id` restores them from the top-level `exchanges[]` array).
```

- [ ] **Step 4: Run pre-commit on the docs**

Run: `pre-commit run --files docs/edit_config.md CLAUDE.md`
Expected: hooks pass (prettier may reformat the Markdown tables — re-stage if so).

- [ ] **Step 5: Commit**

```bash
git add docs/edit_config.md CLAUDE.md
git commit -m "docs(edit-config): document exchangeId add/remove inheritance"
```

---

## Final verification

- [ ] **Run the entire edit-config suite**

Run: `python3 -m pytest tools/edit-config/tests/ -q`
Expected: all pass.

- [ ] **Run pre-commit on every changed Python file**

```bash
pre-commit run --files \
  tools/edit-config/edit_config.py \
  tools/edit-config/edit_config_lib/config_ops.py \
  tools/edit-config/edit_config_lib/config_editor.py \
  tools/edit-config/edit_config_lib/config_text_surgery.py \
  tools/edit-config/edit_config_lib/config_diff.py
```
Expected: black/whitespace hooks pass (re-stage and re-commit if black reformats).

- [ ] **Smoke-test against the real config (dry run, no write)**

```bash
python3 tools/edit-config/edit_config.py --config lazer_new.json \
  --add-exchange-id 1 --feed-id 956
```
Expected: exit 0; dry-run diff shows `"exchangeId": 1` inserted and the four
`marketSchedule` strings removed; ends with `[DRY RUN] No changes written.`

```bash
python3 tools/edit-config/edit_config.py --config lazer_new.json \
  --remove-exchange-id --feed-id 922
```
Expected: exit 0; dry-run diff shows `exchangeId` removed and four
`marketSchedule` strings restored from exchange 1.

```bash
python3 tools/edit-config/edit_config.py --config lazer_new.json \
  --add-exchange-id 99 --feed-id 956
```
Expected: exit 1; `ERROR: --add-exchange-id 99: exchange not defined in exchanges[]`.

---

## Notes for the implementer

- **Why capture exchange data at construction, not in `apply()`:** the
  `exchanges[]` array lives at config top level, not in a feed; capturing it
  when building the op keeps the `op.apply(feed)` and `simulate_plan(plan, feeds)`
  interfaces unchanged (same pattern as `SetRicMapping`/`SetRicFromResolver`).
- **`after is None` means delete; `before is None` means insert.** Both
  conventions are now used by the applier and the diff renderer — keep them
  straight when adding more field types later.
- **`delete_scalar_field` assumes a trailing comma** (field is never last in its
  object). This holds for `exchangeId` (more feed fields follow) and a session's
  `marketSchedule` (`"session"` always follows). Do not reuse it for a
  potentially-last field without extending it.
- **Old-format guard:** `main()` already rejects configs with feed-level
  `allowedPublisherIds`. The exchange ops run only on new-format configs; no
  extra guard needed.
```
