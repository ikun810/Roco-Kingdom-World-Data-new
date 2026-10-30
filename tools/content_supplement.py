#!/usr/bin/env python3
"""Verify and resolve a limited, provenance-tagged historical content supplement."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import ZipFile, BadZipFile

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1048576), b""):
            h.update(b)
    return h.hexdigest()

def git_blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def resolve(archive, supplement, history_root):
    if supplement.get("format") != "roco_referenced_content_supplement_v1":
        raise ValueError("Unknown supplement version")
    if sha256_file(archive) != supplement["target_archive_sha256"]:
        raise ValueError("Current archive SHA-256 does not match registered target")
    old_cache, new_cache = {}, {}
    records, reviews, unresolved = [], [], list(supplement.get("unresolved", []))
    stats, seen = Counter(), set()
    root = Path(history_root).resolve()
    with ZipFile(archive) as z:
        for x in supplement["entries"]:
            table, ident, mode = x["table"], str(x["id"]), x["operation"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", table) or not ident.isdigit():
                raise ValueError("Unsafe table or record ID")
            if (table, ident) in seen:
                raise ValueError("Duplicate target ID")
            seen.add((table, ident))
            if mode not in ("add_if_absent", "backfill_missing_fields", "review_conflict"):
                raise ValueError("Unknown recovery mode")
            name, blob = x["source_path"], x["source_blob_sha"]
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name or not re.fullmatch("[0-9a-f]{40}", blob):
                raise ValueError("Unsafe source reference")
            path = root.joinpath(*p.parts)
            if not path.resolve().is_relative_to(root) or path.is_symlink():
                raise ValueError("Source path escapes history root")
            if name not in old_cache:
                raw = path.read_bytes()
                if git_blob_sha(raw) != blob:
                    raise ValueError("Historical Git blob SHA mismatch")
                old_cache[name] = json.loads(raw.decode("utf-8-sig"))["RocoDataRows"]
            record = x["record"]
            if old_cache[name].get(ident) != record or str(record.get("id")) != ident:
                raise ValueError("Historical row does not match original")
            if table not in new_cache:
                new_cache[table] = json.loads(z.read("BinDataCompressed/" + table + ".json").decode("utf-8-sig"))["RocoDataRows"]
            current = new_cache[table].get(ident)
            provenance = {"source_path": name, "source_blob_sha": blob,
                          "historical_source_commit": supplement["historical_source_commit"]}
            if mode == "add_if_absent":
                if current is None:
                    records.append({"table": table, "id": ident, "record": record,
                                    "status": "historical_fallback", "provenance": provenance})
                    stats["historical_fallback"] += 1
                else:
                    reviews.append({"table": table, "id": ident, "current": current, "candidate": record,
                                    "status": "existing_id_not_overwritten", "provenance": provenance})
                    stats["existing_id_not_overwritten"] += 1
            elif mode == "backfill_missing_fields":
                if current is None:
                    unresolved.append({"table": table, "id": ident, "reason": "Current row not present for backfill"})
                    continue
                merged, added = deepcopy(current), []
                for field in x["fields"]:
                    if field not in record:
                        raise ValueError("Historical field is missing")
                    if field not in merged:
                        merged[field] = record[field]
                        added.append(field)
                records.append({"table": table, "id": ident, "record": merged,
                                "status": "backfilled_fields" if added else "already_present",
                                "fields_added": added, "provenance": provenance})
                stats["backfilled_fields" if added else "already_present"] += 1
            else:
                reviews.append({"table": table, "id": ident, "current": current,
                                "candidate": record, "fields_to_review": x["fields"],
                                "status": "review_required", "provenance": provenance})
                stats["review_required"] += 1
    return {"format": "roco_content_recovery_output_v1",
            "historical_is_not_verified_as_current": True,
            "resolved_records": records, "review_candidates": reviews, "unresolved": unresolved,
            "summary": {"resolved_count": len(records), "review_count": len(reviews),
                        "unresolved_count": len(unresolved), **stats}}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("data/current.zip"))
    parser.add_argument("--supplement", type=Path, default=Path("data/supplements/referenced_content.json"))
    parser.add_argument("--history-root", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    exp = sub.add_parser("export")
    exp.add_argument("--output", type=Path, default=Path("build/referenced_content_resolved.json"))
    get = sub.add_parser("get")
    get.add_argument("--table", required=True)
    get.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    try:
        with args.supplement.open("r", encoding="utf-8-sig") as f:
            supplement = json.load(f)
        output = resolve(args.archive, supplement, args.history_root)
        if args.command == "export":
            destination = args.output.resolve()
            root = args.history_root.resolve()
            if destination == args.archive.resolve() or destination == args.supplement.resolve():
                raise ValueError("Output must not overwrite source")
            if any(destination.is_relative_to((root / p).resolve()) for p in ("data", "pakchunk4-WindowsNoEditor",
                 "pakchunk4-WindowsNoEditor_0_P", "pakchunk4-WindowsNoEditor_1_P",
                 "pakchunk4-WindowsNoEditor_2_P", "pakchunk4-WindowsNoEditor_3_P")):
                raise ValueError("Output must be outside source data directories")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.command == "get":
            table = args.table.removesuffix(".json")
            out = next((r for group in ("resolved_records","review_candidates","unresolved")
                        for r in output[group] if r["table"] == table and r["id"] == args.id), None)
            if out is None:
                raise ValueError("ID not in scoped source supplement")
        else:
            out = output["summary"]
        print(json.dumps(out, ensure_ascii=True, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, BadZipFile, json.JSONDecodeError) as e:
        print("ERROR: " + str(e), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
