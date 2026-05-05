# edit-config

Surgical editor for `after.json`: add/remove publishers, change `minPublishers`,
change `state` — across one feed, a range of feeds, or a filtered set
(by symbol pattern, asset class, or current state).

## Quick start

```bash
# CLI (single op, dry-run is the default)
python3 tools/edit-config/edit_config.py --config after.json \
    --add-publisher 80 --feed-id 1000-1050

# YAML spec (batched ops)
python3 tools/edit-config/edit_config.py --config after.json \
    --from-spec my_edits.yaml --apply
```

## Layout

| Path                                     | Purpose                                                       |
| ---------------------------------------- | ------------------------------------------------------------- |
| `edit_config.py`                         | CLI entry point (thin wrapper)                                |
| `edit_config_lib/config_selector.py`     | Feed-ID selector grammar (singles + ranges, file/stdin input) |
| `edit_config_lib/config_text_surgery.py` | Bracket-depth scanner, feed/session block locators            |
| `edit_config_lib/config_ops.py`          | Operation classes (`AddPublisher`, `RemovePublisher`, …)      |
| `edit_config_lib/config_diff.py`         | Unified diff with feedId/symbol/session hunk headers          |
| `edit_config_lib/config_editor.py`       | Spec parsing → plan → validate → apply orchestrator           |
| `tests/`                                 | pytest suite (unit, integration, CLI)                         |
| `tests/fixtures/`                        | Sample `after.json` slice and YAML specs                      |

## Docs

- Full reference: [`docs/edit_config.md`](../../docs/edit_config.md)
- Recipes: [`docs/edit_config_examples.md`](../../docs/edit_config_examples.md)
- Design spec: [`docs/superpowers/specs/2026-05-05-edit-config-design.md`](../../docs/superpowers/specs/2026-05-05-edit-config-design.md)

## Independence

This tool is fully self-contained. It does not import from `update_config_from_summary.py`,
`update_min_publishers.py`, `update_lazer_symbols.py`, or the repo-level `lib/` package.
Helpers live under `tools/edit-config/edit_config_lib/`.
