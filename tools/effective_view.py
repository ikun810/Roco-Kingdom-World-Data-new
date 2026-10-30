#!/usr/bin/env python3
"""Produce one read-only candidate effective view of layered Pak configuration files.

A higher-priority Pak *file* replaces an entire lower-priority file at the same logical
path. This tool never merges RocoDataRows across layers, never rewrites source files,
and does not claim to have verified a game's custom runtime Pak mount order.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

import build_catalog

FORMAT = "1.0"
PAK_RE = re.compile(r"^(pakchunk[0-9]+-[A-Za-z0-9]+?)(?:_([0-9]+)_P)?$")
DATA_KINDS = ("BinDataCompressed", "BinData")


def standard_order(layer_names: list[str]) -> list[str]:
    """Use standard Unreal numeric _N_P naming as a *hypothesis*, never proof."""
    names = list(layer_names)
    if not names or len(set(names)) != len(names):
        raise ValueError("Missing or repeated Pak layer names")
    found = [PAK_RE.fullmatch(name) for name in names]
    if any(match is None for match in found):
        raise ValueError("Nonstandard Pak filenames: supply an explicit --order")
    if len({match.group(1) for match in found if match is not None}) != 1:
        raise ValueError("Multiple Pak chunk groups: supply an explicit --order")
    ranks = [(-1 if match.group(2) is None else int(match.group(2))) for match in found]
    if len(set(ranks)) != len(ranks):
        raise ValueError("Two Pak layers have the same numeric priority")
    return [name for rank, name in sorted(zip(ranks, names))]


def validate_order(layers: list[str], order: list[str] | None) -> tuple[list[str], str]:
    available = list(layers)
    if not available or len(set(available)) != len(available):
        raise ValueError("Invalid catalog: Pak layer names absent or duplicated")
    if order is None:
        return standard_order(available), "standard_unreal_filename_inference"
    if len(order) != len(available) or set(order) != set(available) or len(set(order)) != len(order):
        raise ValueError("--order must include every catalog Pak layer exactly once")
    return order, "operator_supplied_unverified"


def safe_table_path(relative: str, layer: str, table: str) -> None:
    # Exact match simultaneously rejects traversal, absolute paths and foreign layers.
    if "/" not in table:
        raise ValueError(f"Invalid table key: {table!r}")
    kind, stem = table.split("/", 1)
    if kind not in DATA_KINDS or not re.fullmatch(r"[A-Za-z0-9_-]+", stem):
        raise ValueError(f"Invalid table key: {table!r}")
    if relative != f"{layer}/Bin/{kind}/{stem}.json":
        raise ValueError(f"Mismatched source path for {table}: {relative!r}")


def effective_view(catalog: dict, order: list[str] | None = None) -> dict:
    """Select the highest-priority *complete file* for each table and locale."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get("tables"), list):
        raise ValueError("Expected a full build_catalog catalog, not the summary")
    source_layers = [layer["name"] for layer in catalog.get("layers", [])]
    ordered, method = validate_order(source_layers, order)
    ranks = {layer: i for i, layer in enumerate(ordered)}
    selected, per_layer = [], Counter()
    rows_selected = 0
    total_copies = 0
    overridden = 0
    for table in catalog["tables"]:
        table_id = table.get("table")
        copies = table.get("copies")
        if not isinstance(table_id, str) or not isinstance(copies, list) or not copies:
            raise ValueError("Invalid catalog table entry")
        if len({cp.get("layer") for cp in copies}) != len(copies):
            raise ValueError(f"Duplicate Pak layer in table {table_id}")
        for cp in copies:
            if cp.get("layer") not in ranks:
                raise ValueError(f"Unknown source layer for {table_id}")
            safe_table_path(cp.get("path", ""), cp["layer"], table_id)
            if not isinstance(cp.get("row_count"), int) or cp["row_count"] < 0:
                raise ValueError(f"Invalid row count for {table_id}")
        top = max(copies, key=lambda cp: ranks[cp["layer"]])
        schema_candidates = table.get("candidate_schemas", [])
        if not isinstance(schema_candidates, list):
            raise ValueError(f"Invalid schema candidates for {table_id}")
        selected.append({
            "table": table_id, "data_layer": top["layer"], "data_path": top["path"],
            "source_sha256": top["sha256"], "row_count": top["row_count"],
            "observed_fields": top.get("observed_fields", []),
            # May require reading source _logs/schema_usage.csv to identify the actual
            # decoding schema. Do not silently substitute a newer version's schema.
            "schema_source_layer": top["layer"] if top.get("schema_in_same_layer") else None,
            "schema_source_verified": False,
            "candidate_schema_layers": sorted({entry["layer"] for entry in schema_candidates}),
            "superseded_layers": [cp["layer"] for cp in sorted(copies, key=lambda cp: ranks[cp["layer"]])[:-1]],
            "different_source_hashes": len({cp["sha256"] for cp in copies}) > 1,
        })
        rows_selected += top["row_count"]
        per_layer[top["layer"]] += 1
        total_copies += len(copies)
        overridden += len(copies) > 1
    selected.sort(key=lambda entry: entry["table"])
    # Localizations are also full-file overlays, but language tags are kept distinct
    # (e.g. zh_CN vs zh_Hans are not assumed interchangeable).
    locale_choices = {}
    for entry in catalog.get("localizations", []):
        layer, language, path = entry["layer"], entry["language"], entry["path"]
        if layer not in ranks:
            raise ValueError("Unknown localization layer")
        if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", language):
            raise ValueError("Unsafe localization language")
        filename = PurePosixPath(path).name
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.json", filename):
            raise ValueError("Unsafe localization filename")
        if path != f"{layer}/Bin/BinLocalize/{language}/{filename}":
            raise ValueError("Invalid localization path")
        key = f"{language}/{filename}"
        if key not in locale_choices or ranks[layer] > ranks[locale_choices[key]["layer"]]:
            locale_choices[key] = entry
    locale_selected = [
        {"locale_file": name, "data_layer": value["layer"],
         "data_path": value["path"], "source_sha256": value["sha256"]}
        for name, value in sorted(locale_choices.items())
    ]
    summary = {
        "effective_table_kinds": len(selected),
        "effective_compressed_tables": sum(x["table"].startswith("BinDataCompressed/") for x in selected),
        "effective_rows": rows_selected,
        "source_file_copies": total_copies,
        "overridden_table_kinds": overridden,
        "not_selected_source_rows": catalog.get("summary", {}).get("total_rows_across_layers", 0) - rows_selected,
        "effective_localization_files": len(locale_selected),
        "selected_tables_by_layer": {layer: per_layer[layer] for layer in ordered},
        "source_catalog_issues": len(catalog.get("issues", [])),
    }
    return {
        "view_format": FORMAT,
        "snapshot_label": catalog.get("snapshot_label"),
        "source_commit": catalog.get("source_commit"),
        "priority_low_to_high": ordered,
        "priority_selection_method": method,
        "pak_mount_order_verified": False,
        "read_strategy": "whole_file_replacement_no_record_merge",
        "notice": "Candidate effective view under the selected Pak priority hypothesis. No runtime client mount evidence claimed.",
        "summary": summary, "tables": selected, "localizations": locale_selected,
    }


def load_selected_rows(root: Path, entry: dict) -> dict:
    """Read just one selected source file and verify its catalog fingerprint."""
    root = root.resolve()
    path = entry["data_path"]
    safe_table_path(path, entry["data_layer"], entry["table"])
    relative = Path(*PurePosixPath(path).parts)
    source = root / relative
    if not source.resolve().is_relative_to(root):
        raise ValueError("Source path escapes repository")
    for parent in (source, *source.parents):
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise ValueError("Source symlink not allowed")
    if not source.is_file():
        raise ValueError(f"Selected source file missing: {path}")
    if build_catalog.file_hash(source) != entry["source_sha256"]:
        raise ValueError(f"Selected source hash mismatch: {path}")
    with source.open("r", encoding="utf-8-sig") as reader:
        obj = json.load(reader)
    rows = obj.get("RocoDataRows") if isinstance(obj, dict) else None
    if not isinstance(rows, dict) or len(rows) != entry["row_count"]:
        raise ValueError(f"Selected source row count differs: {path}")
    return rows


def select_table(view: dict, table_name: str) -> dict:
    table_id = table_name if "/" in table_name else "BinDataCompressed/" + table_name.removesuffix(".json")
    chosen = next((t for t in view["tables"] if t["table"] == table_id), None)
    if chosen is None:
        raise ValueError(f"Unknown effective table: {table_id}")
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Generate content-free effective file selection from a catalog")
    build.add_argument("--catalog", type=Path, required=True)
    build.add_argument("--output", type=Path, default=Path("build/effective_view_20260716.json"))
    build.add_argument("--summary", type=Path, default=Path("build/effective_summary_20260716.json"))
    build.add_argument("--order", nargs="+", help="Optional exact layer order, LOW to HIGH priority")
    read = sub.add_parser("get", help="Query one ID in the selected effective source file")
    read.add_argument("--root", type=Path, default=Path("."))
    read.add_argument("--view", type=Path, default=Path("build/effective_view_20260716.json"))
    read.add_argument("--table", required=True)
    read.add_argument("--id", required=True)
    find = sub.add_parser("find", help="Find a text fragment in one field of the selected file")
    find.add_argument("--root", type=Path, default=Path("."))
    find.add_argument("--view", type=Path, default=Path("build/effective_view_20260716.json"))
    find.add_argument("--table", required=True)
    find.add_argument("--field", required=True)
    find.add_argument("--contains", required=True)
    find.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            if args.catalog.resolve() in (args.output.resolve(), args.summary.resolve()):
                raise ValueError("Do not overwrite source catalog")
            if args.output.resolve() == args.summary.resolve():
                raise ValueError("View and summary outputs must differ")
            with args.catalog.open("r", encoding="utf-8") as f:
                catalog = json.load(f)
            view = effective_view(catalog, args.order)
            build_catalog.atomic_json(args.output, view)
            build_catalog.atomic_json(args.summary, {
                key: view[key] for key in ("snapshot_label", "source_commit", "priority_low_to_high",
                                             "priority_selection_method", "pak_mount_order_verified",
                                             "read_strategy", "summary")
            })
            result = view["summary"]
        else:
            if args.command == "find" and (args.limit < 1 or args.limit > 100):
                raise ValueError("--limit must be between 1 and 100")
            with args.view.open("r", encoding="utf-8") as f:
                view = json.load(f)
            entry = select_table(view, args.table)
            rows = load_selected_rows(args.root, entry)
            if args.command == "get":
                if args.id not in rows:
                    raise ValueError(f"Record {args.id!r} absent from effective file {entry['table']}")
                result = {"table": entry["table"], "source_layer": entry["data_layer"],
                          "id": args.id, "record": rows[args.id],
                          "priority_verified": view.get("pak_mount_order_verified", False)}
            else:
                results, count = [], 0
                for key, row in rows.items():
                    if not isinstance(row, dict) or args.field not in row:
                        continue
                    val = row[args.field]
                    s = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
                    if args.contains.casefold() in s.casefold():
                        count += 1
                        if len(results) < args.limit:
                            results.append({"id": key, "preview": s[:150]})
                result = {"table": entry["table"], "source_layer": entry["data_layer"],
                          "field": args.field, "total_matches": count, "results": results,
                          "truncated": count > args.limit}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
