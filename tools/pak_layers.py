#!/usr/bin/env python3
"""Inspect and explicitly stage per-Pak decoded JSON, without assuming patch priority.

The input tree is read only. This script never fetches, decrypts, or modifies a game client.
Any staged data are a *candidate reconstruction* until patch mount order is verified.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from versioned_db import hash_file

VERSION = "0.1.0"


def discover_layers(root: Path) -> list[dict]:
    if not root.is_dir():
        raise ValueError(f"Repository directory not found: {root}")
    result = []
    for directory in sorted(root.iterdir(), key=lambda x: x.name):
        if not directory.is_dir() or not directory.name.startswith("pakchunk"):
            continue
        binroot = directory / "Bin"
        datadir = binroot / "BinDataCompressed"
        schemadir = binroot / "BinConf"
        if not datadir.is_dir():
            continue
        data = files_in(datadir)
        schema = files_in(schemadir)
        localize = binroot / "BinLocalize"
        languages = {}
        if localize.is_dir():
            for lang in sorted(localize.iterdir()):
                if lang.is_dir():
                    languages[lang.name] = len(files_in(lang))
        result.append({"name": directory.name, "directory": directory,
                       "data": data, "schema": schema, "locales": languages})
    if not result:
        raise ValueError("No Pak folders with Bin/BinDataCompressed found")
    return result


def files_in(directory: Path) -> dict[str, dict]:
    if not directory.is_dir():
        return {}
    found = {}
    for path in sorted(directory.glob("*.json"), key=lambda x: x.name):
        if path.is_symlink():
            raise ValueError(f"Source symlinks not supported: {path}")
        if path.is_file():
            found[path.name] = {"path": path, "sha256": hash_file(path), "bytes": path.stat().st_size}
    return found


def analyze(root: Path) -> dict:
    layers = discover_layers(root)
    locations = defaultdict(list)
    schemas = set()
    for layer in layers:
        schemas.update(layer["schema"])
        for name, file_info in layer["data"].items():
            locations[name].append({"layer": layer["name"], "sha256": file_info["sha256"]})
    overlays = [{"table": name, "copies": refs, "different_hashes": len({r["sha256"] for r in refs}) > 1}
                for name, refs in sorted(locations.items()) if len(refs) > 1]
    return {"tool_version": VERSION, "source_root": str(root),
            "notes": "No effective mount order inferred; data from each Pak are kept separate",
            "layers": [{"name": l["name"], "data_tables": len(l["data"]),
                        "schema_files": len(l["schema"]), "locales": l["locales"]} for l in layers],
            "unique_data_tables": len(locations),
            "overlap_tables": len(overlays),
            "different_hash_overlaps": sum(x["different_hashes"] for x in overlays),
            "tables_without_any_schema": sorted(set(locations) - schemas),
            "overlays": overlays}


def staged_plan(root: Path, order: list[str]) -> tuple[list[dict], dict]:
    layers = discover_layers(root)
    known = {layer["name"]: layer for layer in layers}
    if len(order) != len(known) or set(order) != set(known) or len(order) != len(set(order)):
        raise ValueError(f"--order must name every layer exactly once. Found: {', '.join(sorted(known))}")
    ordered = [known[name] for name in order]
    selected = {}
    for index, layer in enumerate(ordered):
        for name, item in layer["data"].items():
            selected[name] = (index, item)
    plan = []
    cross_schemas = 0
    for filename, (data_index, item) in sorted(selected.items()):
        # Prefer a schema from the data layer; otherwise the most recent earlier one.
        choice = None
        for index in range(data_index, -1, -1):
            found = ordered[index]["schema"].get(filename)
            if found:
                choice = (index, found)
                break
        # A later-layer schema is not necessarily compatible, but can be recorded as a candidate.
        schema_after_data = False
        if choice is None:
            for index in range(data_index + 1, len(ordered)):
                found = ordered[index]["schema"].get(filename)
                if found:
                    choice = (index, found)
                    schema_after_data = True
                    break
        if choice and choice[0] != data_index:
            cross_schemas += 1
        plan.append({"table": filename.removesuffix(".json"), "filename": filename,
                     "data_layer": order[data_index], "data_path": item["path"],
                     "source_sha256": item["sha256"],
                     "schema_layer": order[choice[0]] if choice else None,
                     "schema_path": choice[1]["path"] if choice else None,
                     "schema_sha256": choice[1]["sha256"] if choice else None,
                     "schema_after_data_layer": schema_after_data})
    report = {"tool_version": VERSION, "source_root": str(root), "priority_low_to_high": order,
              "order_verified": False,
              "warning": "Operator-supplied Pak order. Candidate reconstruction only, not a verified client effective view.",
              "table_count": len(plan), "cross_layer_schema_count": cross_schemas,
              "missing_schema_count": sum(x["schema_layer"] is None for x in plan),
              "schema_from_later_layer_count": sum(x["schema_after_data_layer"] for x in plan),
              "selections": [{k: v for k, v in x.items() if k not in ("data_path", "schema_path")}
                             for x in plan]}
    return plan, report


def stage(root: Path, order: list[str], target: Path) -> dict:
    if target.exists():
        raise ValueError(f"Refusing to replace existing output directory: {target}")
    if target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Output must be outside the source repository directory")
    plan, report = staged_plan(root, order)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="roco-stage-", dir=target.parent))
    try:
        data_output = temp / "BinDataCompressed"
        schema_output = temp / "BinConf"
        data_output.mkdir()
        schema_output.mkdir()
        for entry in plan:
            shutil.copyfile(entry["data_path"], data_output / entry["filename"])
            if entry["schema_path"]:
                shutil.copyfile(entry["schema_path"], schema_output / entry["filename"])
        report["created_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        report["data_directory"] = "BinDataCompressed"
        report["schema_directory"] = "BinConf"
        (temp / "staging_manifest.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, target)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return {"created": str(target), "table_count": len(plan),
            "cross_layer_schema_count": report["cross_layer_schema_count"],
            "missing_schema_count": report["missing_schema_count"],
            "order_verified": False,
            "warning": report["warning"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("analyze", help="List Pak layers and overlaps without writing input data")
    inv.add_argument("--root", required=True)
    inv.add_argument("--output")
    st = sub.add_parser("stage", help="Copy an explicit precedence-based candidate reconstruction")
    st.add_argument("--root", required=True)
    st.add_argument("--order", nargs="+", required=True, help="Every Pak directory, lowest priority first")
    st.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            result = analyze(Path(args.root))
            payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            if args.output:
                path = Path(args.output)
                if path.resolve().is_relative_to(Path(args.root).resolve()):
                    raise ValueError("Report output must not be inside input repository")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding="utf-8")
                print(f"Report written to: {path}")
            else:
                print(payload, end="")
        else:
            print(json.dumps(stage(Path(args.root), args.order, Path(args.out_dir)),
                             ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
