# Troubleshooting

## Setup Errors

### "externally-managed-environment" error

Your system Python is protected. Use a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

### "config.yaml not found"

Copy the sample config and add credentials:

```bash
cp config.yaml.sample config.yaml
# Edit config.yaml with your ClickHouse credentials
```

## Connection Errors

### "EOF occurred in violation of protocol"

The ClickHouse hostname is incorrect. Double-check `host` values in `config.yaml`.

### Connection timeout

The ClickHouse cluster might be cold-starting. Wait a minute and try again.

## Data Errors

### "No publisher data found"

- Verify the publisher ID is correct
- Verify the publisher was active on the specified date
- Check if the feed ID exists

### "No benchmark data found"

- Verify the feed_id exists
- Verify benchmark data exists for the date
- Verify the mode matches the feed type
- For futures: ensure benchmark data exists for the specific contract

Use `--list-asset-classes` to check which asset classes have benchmark data:

```bash
python quick_benchmark.py --csv your_file.csv --list-asset-classes
```

### "Insufficient observations (N < 100)"

Not enough data points matched between publisher and benchmark.

- Can happen during market closures or partial trading days
- Try a different date with full market hours

### "Could not extract publisher ID from filename"

For `publisher_benchmark.py`, either:

1. Rename file to `publisher_{id}_feeds.csv`
2. Use `--publisher-id` explicitly:
   ```bash
   python publisher_benchmark.py --csv my_feeds.csv --publisher-id 55
   ```

## Filtering Issues

### Empty output with no error

The publisher/feed exists but no data matches your criteria.

- Try without `--asset-class` filter
- Increase `--time-window` for `publisher_feeds.py`
- Check filters aren't too restrictive
