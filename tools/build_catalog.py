#!/usr/bin/env python3
"""Generate a deterministic, content-free catalog of decoded multi-Pak configuration files.

The tool reads all JSON configuration tables and schemas without modifying sources.
It NEVER selects an effective Pak layer or serializes actual game records.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

FORMAT_VERSION = "1.0"
DATA_TYPES = ("BinDataCompressed", "BinData")


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def paths_in(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    if directory.is_symlink():
        raise ValueError(f"Refusing symlink directory: {directory}")
    files = sorted(directory.glob("*.json"), key=lambda p: p.name)
    if any(f.is_symlink() for f in files):
        raise ValueError(f"Refusing source symlink in {directory}")
    return [f for f in files if f.is_file()]


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_object(path: Path, issues: list[dict], root: Path, expected: str) -> dict | None:
    try:
        with path.open("r", encoding="utf-8-sig") as source:
            data = json.load(source)
    except (UnicodeError, json.JSONDecodeError, OSError) as exc:
        issues.append({"path": relative(path, root), "code": "parse_error",
                       "details": str(exc)[:250]})
        return None
    if not isinstance(data, dict):
        issues.append({"path": relative(path, root), "code": "invalid_envelope",
                       "details": f"Expected a JSON object for {expected}"})
        return None
    return data


def describe_schema(path: Path, root: Path, issues: list[dict]) -> dict:
    descriptor = {"path": relative(path, root), "sha256": file_hash(path),
                  "bytes": path.stat().st_size, "unique_key": None, "declared_fields": []}
    data = load_object(path, issues, root, "schema")
    if data is None:
        return descriptor
    if data.get("UniqueKey") is not None:
        descriptor["unique_key"] = str(data["UniqueKey"])
    props = data.get("Properties", [])
    if not isinstance(props, list):
        issues.append({"path": relative(path, root), "code": "invalid_schema_properties"})
    else:
        descriptor["declared_fields"] = sorted({str(field["Name"]) for field in props
                                                   if isinstance(field, dict) and isinstance(field.get("Name"), str)})
    return descriptor


def describe_data(path: Path, root: Path, issues: list[dict]) -> dict:
    descriptor = {"path": relative(path, root), "sha256": file_hash(path),
                  "bytes": path.stat().st_size, "row_count": 0,
                  "observed_fields": [], "localization_string_count": 0,
                  "row_shape_issues": 0, "row_key_mismatches": None}
    data = load_object(path, issues, root, "config table")
    if data is None:
        return descriptor
    rows = data.get("RocoDataRows")
    if not isinstance(rows, dict):
        issues.append({"path": relative(path, root), "code": "invalid_data_rows",
                       "details": "RocoDataRows must be a JSON object"})
        return descriptor
    descriptor["row_count"] = len(rows)
    fields = set()
    shape_errors = 0
    for record in rows.values():
        if not isinstance(record, dict):
            shape_errors += 1
            continue
        fields.update(str(key) for key in record.keys())
    descriptor["observed_fields"] = sorted(fields)
    descriptor["row_shape_issues"] = shape_errors
    if shape_errors:
        issues.append({"path": relative(path, root), "code": "invalid_row_shape",
                       "count": shape_errors})
    loc = data.get("LocalizationStrings", {})
    if isinstance(loc, dict):
        descriptor["localization_string_count"] = len(loc)
    elif loc is not None:
        issues.append({"path": relative(path, root), "code": "invalid_localization_strings"})
    return descriptor


def guard_output(path: Path, root: Path) -> None:
    target = path.resolve()
    for child in root.iterdir():
        if child.is_dir() and child.name.startswith("pakchunk"):
            if target == child.resolve() or child.resolve() in target.parents:
                raise ValueError("Output must not be written inside a Pak source directory")


def catalog(root: Path, snapshot: str = "2026-07-16", source_commit: str | None = None) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Repository directory not found: {root}")
    issues: list[dict] = []
    pak_dirs = [p for p in sorted(root.iterdir(), key=lambda p: p.name)
                if p.name.startswith("pakchunk") and p.is_dir()]
    if not pak_dirs:
        raise ValueError("No Pak directories found")
    for layer in pak_dirs:
        if layer.is_symlink():
            raise ValueError(f"Refusing source symlink: {layer}")

    tables: dict[str, list[dict]] = defaultdict(list)
    schemas: dict[str, list[dict]] = defaultdict(list)
    localizations: list[dict] = []
    layer_summaries: list[dict] = []
    data_file_count = 0
    schema_file_count = 0
    total_rows = 0
    empty_tables = 0
    for layer in pak_dirs:
        binroot = layer / "Bin"
        layer_summary = {"name": layer.name, "data_files": {}, "schema_files": 0,
                         "localization_files": 0, "data_rows": 0}
        for path in paths_in(binroot / "BinConf"):
            d = describe_schema(path, root, issues)
            d["layer"] = layer.name
            schemas[path.name].append(d)
            schema_file_count += 1
            layer_summary["schema_files"] += 1
        for kind in DATA_TYPES:
            count = 0
            for path in paths_in(binroot / kind):
                d = describe_data(path, root, issues)
                d["layer"] = layer.name
                d["kind"] = kind
                count += 1
                data_file_count += 1
                total_rows += d["row_count"]
                layer_summary["data_rows"] += d["row_count"]
                if d["row_count"] == 0:
                    empty_tables += 1
                tables[f"{kind}/{path.stem}"].append(d)
            layer_summary["data_files"][kind] = count
        locroot = binroot / "BinLocalize"
        if locroot.is_dir():
            if locroot.is_symlink():
                raise ValueError(f"Refusing source symlink: {locroot}")
            for lang in sorted(locroot.iterdir(), key=lambda p: p.name):
                if not lang.is_dir():
                    continue
                if lang.is_symlink():
                    raise ValueError(f"Refusing source symlink: {lang}")
                for path in paths_in(lang):
                    localizations.append({"path": relative(path, root), "layer": layer.name,
                                          "language": lang.name, "bytes": path.stat().st_size,
                                          "sha256": file_hash(path)})
                    layer_summary["localization_files"] += 1
        layer_summaries.append(layer_summary)

    combined = []
    for table, copies in sorted(tables.items()):
        base_name = table.split("/", 1)[1] + ".json"
        possible_schemas = schemas.get(base_name, [])
        candidates = [{"layer": s["layer"], "path": s["path"],
                       "sha256": s["sha256"]} for s in possible_schemas]
        for d in copies:
            local = next((s for s in possible_schemas if s["layer"] == d["layer"]), None)
            d["schema_in_same_layer"] = local is not None
            d["schema_unique_key"] = local["unique_key"] if local else None
            if local and d["row_shape_issues"] == 0:
                # Compare actual row keys only when a local schema key is defined.
                # Row IDs are not serialized by this metadata-only catalog.
                d["row_key_mismatches"] = None
        combined.append({"table": table, "layers": [d["layer"] for d in copies],
                         "copies": copies, "candidate_schemas": candidates,
                         "overlap": len(copies) > 1,
                         "different_content_hashes": len({d["sha256"] for d in copies}) > 1})
    all_schemas = [{"table": name, "copies": copies} for name, copies in sorted(schemas.items())]
    summary = {
        "layer_count": len(layer_summaries), "data_files": data_file_count,
        "compressed_files": sum(x["data_files"]["BinDataCompressed"] for x in layer_summaries),
        "uncompressed_files": sum(x["data_files"]["BinData"] for x in layer_summaries),
        "schema_files": schema_file_count, "localization_files": len(localizations),
        "unique_table_kinds": len(combined),
        "unique_compressed_table_names": len({x["table"] for x in combined
                                               if x["table"].startswith("BinDataCompressed/")}),
        "overlapping_table_kinds": sum(x["overlap"] for x in combined),
        "overlaps_with_different_hashes": sum(x["different_content_hashes"] for x in combined
                                               if x["overlap"]),
        "total_rows_across_layers": total_rows, "empty_table_copies": empty_tables,
        "issue_count": len(issues),
    }
    return {"catalog_format": FORMAT_VERSION, "snapshot_label": snapshot,
            "source_commit": source_commit,
            "game_build_verified": False,
            "pak_mount_order_verified": False,
            "scope": "Decoded BinDataCompressed/BinData JSON, BinConf schemas and BinLocalize file metadata",
            "notice": "Raw records and localized strings are not included; no Pak override order inferred.",
            "summary": summary, "layers": layer_summaries,
            "tables": combined, "schemas": all_schemas,
            "localizations": localizations, "issues": sorted(issues, key=lambda x: (x["path"], x["code"]))}


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            tmp_name = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(tmp_name, path)
    finally:
        if tmp_name is not None and os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--snapshot", default="2026-07-16")
    parser.add_argument("--source-commit")
    parser.add_argument("--output", default="build/catalog_20260716.json")
    parser.add_argument("--summary", default="build/catalog_summary_20260716.json")
    parser.add_argument("--strict", action="store_true", help="Non-zero exit on malformed JSON/table records")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root)
        output, summary_path = Path(args.output), Path(args.summary)
        for path in (output, summary_path):
            guard_output(path, root.resolve())
        if output.resolve() == summary_path.resolve():
            raise ValueError("Catalog and summary paths must differ")
        result = catalog(root, snapshot=args.snapshot, source_commit=args.source_commit)
        short = {k: result[k] for k in ("catalog_format", "snapshot_label", "source_commit",
                                        "game_build_verified", "pak_mount_order_verified",
                                        "scope", "notice", "summary", "layers", "issues")}
        atomic_json(output, result)
        atomic_json(summary_path, short)
        print(json.dumps(short["summary"], ensure_ascii=False, sort_keys=True))
        if args.strict and result["issues"]:
            print(f"Catalog reports {len(result['issues'])} issues, check {summary_path}", file=sys.stderr)
            return 1
        return 0
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
