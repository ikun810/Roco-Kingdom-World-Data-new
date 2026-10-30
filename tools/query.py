#!/usr/bin/env python3
"""Short entry point for querying the checked-in current data archive."""
from pathlib import Path
import sys
from merged_query import main

BASE = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    raise SystemExit(main([
        "--manifest", str(BASE / "docs/snapshots/pc-1.111.0.177-229314.json"),
        "--source", str(BASE / "data/current.zip"),
        *sys.argv[1:],
    ]))
