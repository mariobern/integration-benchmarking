# edit_config recipes

## Add a publisher to a contiguous range

```bash
python3 tools/edit-config/edit_config.py --config after.json \
    --add-publisher 80 --feed-id 1000-1050
```

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
