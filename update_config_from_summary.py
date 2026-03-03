"""
Update after.json from a feed_readiness summary CSV.

Reads a summary CSV, filters out Test/Lazer publishers, intersects
publishers across dates per feed, and surgically modifies the target
JSON config with per-session publisher lists.
"""
import argparse
import csv
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path


def parse_summary_csv(fileobj) -> dict[int, list[dict]]:
    """Parse summary CSV and group rows by feed_id.

    Returns dict mapping feed_id (int) -> list of row dicts.
    """
    reader = csv.DictReader(fileobj)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in reader:
        feed_id = int(row["feed_id"])
        grouped[feed_id].append(row)
    return dict(grouped)
