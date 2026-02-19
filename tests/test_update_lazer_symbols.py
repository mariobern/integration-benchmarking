import json
import subprocess
import sys

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

SAMPLE_CONFIG = {
    "featureFlags": ["enable_ema"],
    "feeds": [
        {
            "allowedPublisherIds": [1, 2, 3],
            "feedId": 100,
            "metadata": {"name": "AIQ"},
            "minPublishers": 3,
            "state": "COMING_SOON",
            "symbol": "Equity.US.AIQ/USD",
        },
        {
            "allowedPublisherIds": [1, 2],
            "feedId": 200,
            "metadata": {"name": "STABLE_TICKER"},
            "minPublishers": 1,
            "state": "STABLE",
            "symbol": "Equity.US.STABLE_TICKER/USD",
        },
        {
            "allowedPublisherIds": [1, 2, 3, 4],
            "feedId": 300,
            "metadata": {"name": "APP"},
            "minPublishers": 3,
            "state": "COMING_SOON",
            "symbol": "Equity.US.APP/USD",
        },
    ],
    "shardId": 1,
}


# ── Task 1: Markdown parser tests ──────────────────────────────────────


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


# ── Task 2: JSON modifier tests ────────────────────────────────────────


def test_modify_config_changes_target_feeds(tmp_path):
    from update_lazer_symbols import modify_config

    config_file = tmp_path / "after.json"
    raw = json.dumps(SAMPLE_CONFIG, indent=2)
    config_file.write_text(raw)

    ticker_pubs = {
        "AIQ": [19, 21, 22, 65, 71],
        "APP": [22, 42, 65, 69, 71],
    }
    result = modify_config(str(config_file), ticker_pubs, dry_run=False)

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


# ── Task 3: CLI integration tests ──────────────────────────────────────


def test_cli_dry_run(tmp_path):
    md_file = tmp_path / "summary.md"
    md_file.write_text(SAMPLE_MD)
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

    result = subprocess.run(
        [
            sys.executable,
            "update_lazer_symbols.py",
            "--summary",
            str(md_file),
            "--config",
            str(config_file),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd="/home/mariobern/integration-benchmarking",
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    with open(config_file) as f:
        data = json.load(f)
    aiq = [f for f in data["feeds"] if f["metadata"]["name"] == "AIQ"][0]
    assert aiq["state"] == "COMING_SOON"


def test_cli_real_run(tmp_path):
    md_file = tmp_path / "summary.md"
    md_file.write_text(SAMPLE_MD)
    config_file = tmp_path / "after.json"
    config_file.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

    result = subprocess.run(
        [
            sys.executable,
            "update_lazer_symbols.py",
            "--summary",
            str(md_file),
            "--config",
            str(config_file),
        ],
        capture_output=True,
        text=True,
        cwd="/home/mariobern/integration-benchmarking",
    )
    assert result.returncode == 0
    with open(config_file) as f:
        data = json.load(f)
    aiq = [f for f in data["feeds"] if f["metadata"]["name"] == "AIQ"][0]
    assert aiq["state"] == "STABLE"
    assert aiq["minPublishers"] == 2
