"""YAML batch-spec parser.

Spec shape (mirrors edit-config's `version: 1` envelope):

    version: 1
    operations:
      - op: add_session
        session: OVER_NIGHT
        min_publishers: 100
        feed_id: "1000-1050,2000"
        state: COMING_SOON           # optional filter
        symbol_pattern: "Equity.US.A*"  # optional filter
        force: false                  # optional

      - op: remove_session
        session: [PRE_MARKET, POST_MARKET]   # list or comma string
        feed_id: [922, "1000-1050"]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .editor import PlanItem
from .ops import AddSession, RemoveSession
from .selector import parse_selector

_KNOWN_OPS = {"add_session", "remove_session"}
_ADD_KEYS = {
    "op",
    "session",
    "min_publishers",
    "feed_id",
    "symbol_pattern",
    "state",
    "force",
}
_REMOVE_KEYS = {"op", "session", "feed_id", "symbol_pattern", "state", "force"}


def _coerce_feed_id(value: Any) -> set[int] | None:
    if value is None:
        return None
    if isinstance(value, int):
        return {value}
    if isinstance(value, str):
        return parse_selector(value)
    if isinstance(value, list):
        ids: set[int] = set()
        for item in value:
            if isinstance(item, int):
                ids.add(item)
            elif isinstance(item, str):
                ids |= parse_selector(item)
            else:
                raise ValueError(f"feed_id list item must be int or str, got {item!r}")
        return ids
    raise ValueError(f"feed_id must be int, str, or list, got {value!r}")


def _coerce_sessions(value: Any) -> list[str]:
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    raise ValueError(f"session must be str or list, got {value!r}")


def parse_spec(path: str | Path) -> list[PlanItem]:
    """Parse a YAML spec file into a plan."""
    import yaml  # local import: avoid hard dep if YAML mode is unused

    text = Path(path).read_text(encoding="utf-8")
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict):
        raise ValueError("spec must be a YAML mapping at the top level")

    version = doc.get("version")
    if version != 1:
        raise ValueError(f"unsupported spec version: {version!r} (want 1)")

    raw_ops = doc.get("operations") or []
    if not isinstance(raw_ops, list):
        raise ValueError("`operations` must be a list")

    plan: list[PlanItem] = []
    for i, raw in enumerate(raw_ops):
        if not isinstance(raw, dict):
            raise ValueError(f"operation[{i}] must be a mapping")
        op_name = raw.get("op")
        if op_name not in _KNOWN_OPS:
            raise ValueError(
                f"operation[{i}]: unknown op {op_name!r} "
                f"(must be one of {sorted(_KNOWN_OPS)})"
            )

        if op_name == "add_session":
            unknown = set(raw) - _ADD_KEYS
            if unknown:
                raise ValueError(
                    f"operation[{i}] (add_session): unknown keys {sorted(unknown)}"
                )
        else:
            unknown = set(raw) - _REMOVE_KEYS
            if unknown:
                raise ValueError(
                    f"operation[{i}] (remove_session): unknown keys {sorted(unknown)}"
                )

        feed_ids = _coerce_feed_id(raw.get("feed_id"))
        force = bool(raw.get("force", False))
        if "session" not in raw or raw.get("session") in (None, "", []):
            raise ValueError(f"operation[{i}]: `session` is required")
        sessions = _coerce_sessions(raw["session"])
        if not sessions:
            raise ValueError(f"operation[{i}]: `session` is required")

        for session in sessions:
            if op_name == "add_session":
                op = AddSession(
                    session=session,
                    min_publishers=int(raw.get("min_publishers", 100)),
                    force=force,
                )
            else:
                op = RemoveSession(session=session, force=force)
            plan.append(
                PlanItem(
                    op=op,
                    feed_ids=feed_ids,
                    symbol_pattern=raw.get("symbol_pattern"),
                    state=raw.get("state"),
                    force_non_us=force,
                )
            )
    return plan
