#!/usr/bin/env python3
"""Read-only lookup of decoded Roco JSON in explicitly named Pak layers.

No Pak priority is inferred. This script does not copy or edit input files.
Uses Python 3.10+ standard library only.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any

from versioned_db import canonical_json, hash_bytes, hash_file, read_data

VERSION = "0.1.0"
TABLE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def layers_in(root: Path) -> list[str]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"Not a repository directory: {root}")
    result = []
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink() or not directory.name.startswith("pakchunk"):
            continue
        data_dir = directory / "Bin" / "BinDataCompressed"
        if data_dir.is_dir() and not data_dir.is_symlink():
            result.append(directory.name)
    if not result:
        raise ValueError(f"No Pak data layers found in: {root}")
    return sorted(result)


def data_dir_for(root: Path, layer: str) -> Path:
    if layer not in layers_in(root):
        raise ValueError(f"Unknown Pak layer {layer!r}; list the available layers with 'layers'")
    base = root / layer
    for directory in (base, base / "Bin", base / "Bin" / "BinDataCompressed"):
        if directory.is_symlink():
            raise ValueError(f"Source symlink not allowed: {directory}")
    return base / "Bin" / "BinDataCompressed"


def table_filename(name: str) -> str:
    stem = name.removesuffix(".json")
    if not TABLE_NAME.fullmatch(stem):
        raise ValueError(f"Unsafe or invalid table name: {name!r}")
    return stem + ".json"


def table_names(root: Path, layer: str, match: str = "") -> list[str]:
    directory = data_dir_for(root, layer)
    found = []
    for file in directory.glob("*.json"):
        if file.is_symlink():
            raise ValueError(f"Source symlink not allowed: {file}")
        if file.is_file() and file.stem.casefold().find(match.casefold()) >= 0:
            found.append(file.stem)
    return sorted(found)


def load_table(root: Path, layer: str, table: str) -> tuple[dict[str, dict], str]:
    filename = table_filename(table)
    directory = data_dir_for(root, layer)
    path = directory / filename
    if path.is_symlink():
        raise ValueError(f"Source symlink not allowed: {path}")
    if not path.is_file():
        raise ValueError(f"Table {filename!r} not found in {layer}")
    digest = hash_file(path)
    return read_data(path, digest), digest


def describe(row: dict) -> str:
    for field in ("name", "zone_name", "s_title_subtitle", "s_title", "title", "chapter_name", "task_name"):
        value = row.get(field)
        if isinstance(value, str) and value:
            return value[:120]
    return ""


def table_list(root: Path, layer: str, match: str) -> dict:
    names = table_names(root, layer, match)
    return {"layer": layer, "table_count": len(names), "filter": match, "tables": names}


def get_record(root: Path, layer: str, table: str, record_id: str) -> dict:
    rows, source_hash = load_table(root, layer, table)
    if record_id not in rows:
        raise ValueError(f"Record ID {record_id!r} not found in {layer}/{table_filename(table)}")
    return {"layer": layer, "table": table_filename(table).removesuffix('.json'),
            "record_id": record_id, "source_sha256": source_hash, "row": rows[record_id]}


def find_records(root: Path, layer: str, table: str, field: str, keyword: str, limit: int) -> dict:
    if not field or not keyword:
        raise ValueError("--field and --contains must not be empty")
    if limit < 1 or limit > 100:
        raise ValueError("--limit must be 1..100")
    rows, digest = load_table(root, layer, table)
    found = []
    total = 0
    for record_id, row in rows.items():
        value: Any = row.get(field)
        if value is None:
            continue
        text = value if isinstance(value, str) else canonical_json(value)
        if keyword.casefold() not in text.casefold():
            continue
        total += 1
        if len(found) < limit:
            found.append({"id": record_id, "label": describe(row),
                          "matched_field": field, "matched_value_preview": text[:200]})
    return {"layer": layer, "table": table_filename(table).removesuffix('.json'),
            "field": field, "contains": keyword, "source_sha256": digest,
            "total_matches": total, "limit": limit, "truncated": total > limit,
            "matches": found}


def trace_record(root: Path, table: str, record_id: str) -> dict:
    # Layers are sorted for presentation only. These are not precedence or chronological order.
    layer_names = layers_in(root)
    present, absent = [], []
    variants: dict[str, list[str]] = defaultdict(list)
    for layer in layer_names:
        if table_filename(table).removesuffix('.json') not in table_names(root, layer):
            absent.append(layer)
            continue
        rows, digest = load_table(root, layer, table)
        if record_id not in rows:
            absent.append(layer)
            continue
        row = rows[record_id]
        row_digest = hash_bytes(canonical_json(row).encode('utf-8'))
        present.append({"layer": layer, "source_sha256": digest,
                        "row_sha256": row_digest, "label": describe(row),
                        "fields": sorted(row)})
        variants[row_digest].append(layer)
    return {"table": table_filename(table).removesuffix('.json'), "record_id": record_id,
            "layer_sort": "alphabetical_for_display_only",
            "pak_priority_verified": False,
            "present": present, "absent_or_missing_id": absent,
            "distinct_row_variants": len(variants),
            "variant_layers": [{"row_sha256": digest, "layers": layers}
                               for digest, layers in sorted(variants.items())]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path('.'), help="Repository root with pakchunk* directories")
    sub = parser.add_subparsers(dest="command", required=True)
    layers = sub.add_parser("layers", help="Show available Pak directories")
    tbl = sub.add_parser("tables", help="List tables in one named Pak layer")
    tbl.add_argument("--layer", required=True)
    tbl.add_argument("--filter", default="")
    get = sub.add_parser("get", help="Retrieve one ID in one named Pak layer")
    get.add_argument("--layer", required=True)
    get.add_argument("--table", required=True)
    get.add_argument("--id", required=True)
    find = sub.add_parser("find", help="Find values in a single field and Pak layer")
    find.add_argument("--layer", required=True)
    find.add_argument("--table", required=True)
    find.add_argument("--field", required=True)
    find.add_argument("--contains", required=True)
    find.add_argument("--limit", type=int, default=20)
    trace = sub.add_parser("trace", help="Compare one ID across Pak layers without merging")
    trace.add_argument("--table", required=True)
    trace.add_argument("--id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == 'layers':
            result = {"layers": layers_in(args.root), "pak_priority_verified": False}
        elif args.command == 'tables':
            result = table_list(args.root, args.layer, args.filter)
        elif args.command == 'get':
            result = get_record(args.root, args.layer, args.table, args.id)
        elif args.command == 'find':
            result = find_records(args.root, args.layer, args.table, args.field, args.contains, args.limit)
        else:
            result = trace_record(args.root, args.table, args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
