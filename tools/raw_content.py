#!/usr/bin/env python3
"""Reproduce four-table repairs from pinned original Roco bytes and explicit pairings."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
from zipfile import ZipFile

from content_supplement import resolve, write_output_json
from roco_raw import decode_localization, decode_table

TABLES = ("MESSAGE_CONF", "TASK_CONF", "REWARD_CONF", "SELECT_CONF")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_sha(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8"))


def safe_relative(path):
    value = PurePosixPath(path)
    if (value.is_absolute() or ".." in value.parts or "\\" in path
            or not value.parts or str(value) != path):
        raise ValueError("Unsafe source path: " + path)
    return value


def read_bundle(root, manifest):
    """Read regular files in memory, without extracting archive paths."""
    root = root.resolve()
    path = root / safe_relative(manifest["bundle"]["path"])
    if not path.resolve().is_relative_to(root):
        raise ValueError("Bundle escapes repository")
    raw = path.read_bytes()
    if sha256(raw) != manifest["bundle"]["sha256"] or len(raw) != manifest["bundle"]["byte_length"]:
        raise ValueError("Raw bundle fingerprint mismatch")
    expected = {item["path"]: item for item in manifest["assets"]}
    if len(expected) != len(manifest["assets"]):
        raise ValueError("Duplicate registered raw asset")
    result = {}
    with tarfile.open(path, "r:xz") as archive:
        for entry in archive:
            safe_relative(entry.name)
            if not entry.isfile() or entry.name not in expected or entry.name in result:
                raise ValueError("Unexpected, duplicate, or non-regular raw member")
            item = expected[entry.name]
            if entry.size != item["byte_length"]:
                raise ValueError("Raw member length mismatch")
            member = archive.extractfile(entry)
            if member is None:
                raise ValueError("Unreadable raw member")
            content = member.read()
            if sha256(content) != item["sha256"]:
                raise ValueError("Raw member fingerprint mismatch: " + entry.name)
            result[entry.name] = content
    if result.keys() != expected.keys():
        raise ValueError("Raw bundle is missing registered assets")
    return result


def without_strings(value):
    if isinstance(value, dict):
        return {key: without_strings(item) for key, item in value.items()
                if not isinstance(item, str)}
    if isinstance(value, list):
        return [without_strings(item) for item in value]
    return value


def changed_pointers(left, right, pointer=""):
    """Distinguish absent fields from explicit null, zero, and empty arrays."""
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            path = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in left or key not in right:
                result.append(path)
            else:
                result.extend(changed_pointers(left[key], right[key], path))
        return result
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [path for i, (a, b) in enumerate(zip(left, right))
                for path in changed_pointers(a, b, pointer + "/" + str(i))]
    return [] if type(left) is type(right) and left == right else [pointer or "/"]


def diagnostic_count(decoded):
    return sum(bool(row.get("remaining") or row.get("undefined_presence_bits"))
               for row in decoded["struct_diagnostics"])


def source_ref(pair, assets):
    return {role: ({"path": pair[role], "sha256": assets[pair[role]]["sha256"]}
                   if pair.get(role) else None)
            for role in ("data", "schema", "localization")}


def raw_row_provenance(pair, decoded, ident, assets, sources):
    location = deepcopy(decoded["row_locations"][ident])
    start, length = location["offset"], location["length"]
    location["sha256"] = sha256(sources[pair["data"]][start:start + length])
    return {"pairing_id": pair["id"], "sources": source_ref(pair, assets),
            "row": location,
            "localized_references": [ref for ref in decoded["localized_references"]
                                     if ref["row_id"] == ident]}


def build(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "data/raw/manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "roco_raw_source_manifest_v1":
        raise ValueError("Unknown raw source manifest format")
    sources = read_bundle(root, manifest)
    assets = {item["path"]: item for item in manifest["assets"]}
    baseline_path = root / safe_relative(manifest["baseline_archive"]["path"])
    if sha256(baseline_path.read_bytes()) != manifest["baseline_archive"]["sha256"]:
        raise ValueError("Pinned baseline fingerprint mismatch")
    supplement_path = root / "data/supplements/referenced_content.json"
    supplement = json.loads(supplement_path.read_text(encoding="utf-8"))
    pairs = {pair["id"]: pair for pair in manifest["pairings"]}
    if len(pairs) != len(manifest["pairings"]):
        raise ValueError("Duplicate pairing ID")
    locale_cache = {}

    def locale(path):
        if path is None:
            return None
        if path not in locale_cache:
            locale_cache[path] = decode_localization(sources[path])
        return locale_cache[path]

    # Verify every supplied localization, including unused language alternatives.
    for asset in manifest["assets"]:
        if asset["slot"].startswith("BinLocalize/"):
            locale(asset["path"])
    keep = {pair_id for view in manifest["views"].values() for pair_id in view.values()}
    keep.update(manifest["missing_row_fallback"].values())
    decoded, results = {}, []
    for pair in manifest["pairings"]:
        schema = json.loads(sources[pair["schema"]])
        if schema["Name"] != pair["table"] or pair["table"] not in TABLES:
            raise ValueError("Pairing table/schema mismatch")
        for role, slot in (("data", "BinDataCompressed"), ("schema", "BinConf")):
            asset = assets[pair[role]]
            if asset["table"] != pair["table"] or asset["slot"] != slot:
                raise ValueError("Pairing asset role mismatch")
        if pair.get("localization"):
            asset = assets[pair["localization"]]
            if asset["table"] != pair["table"] or not asset["slot"].startswith("BinLocalize/"):
                raise ValueError("Pairing locale role mismatch")
        value = decode_table(sources[pair["data"]], schema, locale(pair["localization"]), strict=True,
                             allowed_top_level_padding_bits=pair.get("allowed_top_level_padding_bits", ()))
        if pair["id"] in keep:
            decoded[pair["id"]] = value
        entry = {"pairing_id": pair["id"], "sources": source_ref(pair, assets),
                 "row_count": len(value["rows"]), "rows_canonical_sha256": canonical_sha(value["rows"]),
                 "localized_reference_count": len(value["localized_references"]),
                 "missing_localization_count": len(value["missing_localization"]),
                 "struct_diagnostic_count": diagnostic_count(value),
                 "allowed_padding_bits": pair.get("allowed_top_level_padding_bits", []),
                 "structs_with_allowed_padding": sum(bool(x.get("ignored_padding_bits"))
                                                      for x in value["struct_diagnostics"]),
                 "footer": value["footer"]}
        if pair["table"] == "REWARD_CONF":
            entry["reward_19589"] = value["rows"].get("19589")
            if entry["reward_19589"] is not None:
                entry["reward_19589_provenance"] = raw_row_provenance(pair, value, "19589", assets, sources)
        results.append(entry)

    with ZipFile(baseline_path) as archive:
        current = {table: json.loads(archive.read(f"BinDataCompressed/{table}.json"))["RocoDataRows"]
                   for table in TABLES}
        current_pools = {table: {int(k): v for k, v in json.loads(
            archive.read(f"BinLocalize/zh_Hans/{table}.json"))["LocalizationStrings"].items()}
                         for table in TABLES}
    snapshot_results, reproductions = {}, {}
    for table in TABLES:
        pair = pairs[manifest["views"]["snapshot_repair"][table]]
        value = decoded[pair["id"]]
        rows, old = value["rows"], current[table]
        if rows.keys() != old.keys():
            raise ValueError("Snapshot repair ID set does not match pinned table")
        non_text_equal = sum(without_strings(rows[k]) == without_strings(old[k]) for k in rows)
        snapshot_results[table] = {
            "pairing_id": pair["id"], "row_count": len(rows), "identical_id_set": True,
            "changed_row_count": sum(rows[k] != old[k] for k in rows),
            "unchanged_non_text_row_count": non_text_equal,
            "current_locale_exact_matches": [path for path, pool in sorted(locale_cache.items())
                                             if assets[path]["table"] == table and pool == current_pools[table]],
        }
        if table != "REWARD_CONF" and non_text_equal != len(rows):
            raise ValueError("Unexpected non-text change in text-only snapshot repair")
        wrong = manifest["counterfactual_pairings"][table]
        broken = decode_table(sources[wrong["data"]], json.loads(sources[wrong["schema"]]),
                              locale(wrong["localization"]), strict=False)
        if broken["rows"] != old:
            raise ValueError("Counterfactual no longer reproduces the full pinned table: " + table)
        reproductions[table] = {"sources": source_ref(wrong, assets),
                                "identical_row_count": len(old), "full_rows_equal": True,
                                "struct_diagnostic_count": diagnostic_count(broken),
                                "schema_diagnostics": broken["schema_diagnostics"],
                                "missing_localization_count": len(broken["missing_localization"]),
                                "claim_limit": "Exact counterfactual reproduction, not original exporter log verification."}

    targets = {(row["table"], str(row["id"])) for row in supplement["entries"] if row["table"] in TABLES}
    targets.update((row["table"], str(row["id"])) for row in supplement["unresolved"] if row["table"] in TABLES)
    binary_rows = []
    for table, ident in sorted(targets, key=lambda x: (TABLES.index(x[0]), int(x[1]))):
        existing = current[table].get(ident)
        pair_id = (manifest["views"]["snapshot_repair"][table] if existing is not None
                   else manifest["missing_row_fallback"][table])
        pair, value = pairs[pair_id], decoded[pair_id]
        if ident not in value["rows"]:
            raise ValueError("Referenced ID absent from selected raw source: " + table + "/" + ident)
        record = value["rows"][ident]
        binary_rows.append({"table": table, "id": ident, "record": record,
                            "status": "raw_snapshot_repair" if existing is not None else "raw_missing_record_source",
                            "baseline_record_sha256": canonical_sha(existing) if existing is not None else None,
                            "changed_pointers": changed_pointers(existing, record) if existing is not None else ["/"],
                            "provenance": raw_row_provenance(pair, value, ident, assets, sources)})
    recovery = {"format": "roco_binary_content_recovery_v1",
                "target_archive_sha256": manifest["baseline_archive"]["sha256"],
                "source_submission_sha256": manifest["submission"]["sha256"],
                "source_bundle_sha256": manifest["bundle"]["sha256"],
                "scope_supplement_sha256": sha256(supplement_path.read_bytes()),
                "claim_limit": "Raw-source field bindings and values verified. Missing rows are separate Pak-source additions, not proof they belonged to the pinned mixed export. Runtime mount order, reward dispatch and condition semantics are not certified.",
                "entries": binary_rows,
                "summary": {"binary_record_count": len(binary_rows),
                            "snapshot_repairs": sum(x["status"] == "raw_snapshot_repair" for x in binary_rows),
                            "missing_record_sources": sum(x["status"] == "raw_missing_record_source" for x in binary_rows)}}

    historical = resolve(baseline_path, supplement, root)
    merged = {(row["table"], row["id"]): row for row in historical["resolved_records"]}
    merged.update({(row["table"], row["id"]): row for row in binary_rows})
    reviews = [row for row in historical["review_candidates"] if (row["table"], row["id"]) not in targets]
    unresolved = [row for row in historical["unresolved"] if (row["table"], row["id"]) not in targets]
    resolved = {"format": "roco_binary_assisted_content_output_v1",
                "target_archive_sha256": manifest["baseline_archive"]["sha256"],
                "claim_limit": recovery["claim_limit"] + " Unchanged historical recoveries retain historical provenance; this is not whole-game completion.",
                "resolved_records": [merged[key] for key in sorted(merged)],
                "review_candidates": reviews, "unresolved": unresolved,
                "summary": {"resolved_count": len(merged), "review_count": len(reviews),
                            "unresolved_count": len(unresolved), "binary_source_count": len(binary_rows),
                            "historical_source_count": len(merged) - len(binary_rows)}}
    audit = {"format": "roco_raw_content_audit_v1", "submission": manifest["submission"],
             "source_bundle": manifest["bundle"], "baseline_archive": manifest["baseline_archive"],
             "claim_limit": manifest["claim_limit"], "pairings": results,
             "snapshot_repair": snapshot_results, "counterfactual_reproductions": reproductions,
             "recovery_sha256": canonical_sha(recovery),
             "summary": {"raw_asset_count": len(sources), "data_pairing_count": len(results),
                         "localization_file_count": len(locale_cache),
                         "total_decoded_rows": sum(x["row_count"] for x in results),
                         "missing_localization_count": sum(x["missing_localization_count"] for x in results),
                         "struct_diagnostic_count": sum(x["struct_diagnostic_count"] for x in results),
                         **resolved["summary"]}}
    return {"audit": audit, "recovery": recovery, "resolved": resolved,
            "manifest": manifest, "decoded": decoded}


def export(result, root, destination):
    destination = Path(destination)
    inputs = [root / "data/raw/manifest.json", root / "data/raw/roco-config-20261031.tar.xz"]
    for name, key in (("raw_content_audit.json", "audit"),
                      ("binary_content_recovery.json", "recovery"),
                      ("referenced_content_resolved.json", "resolved")):
        write_output_json(destination / name, result[key], root, inputs)
    for view, mapping in result["manifest"]["views"].items():
        for table, pair_id in mapping.items():
            pair = next(p for p in result["manifest"]["pairings"] if p["id"] == pair_id)
            output = {"RocoDataRows": result["decoded"][pair_id]["rows"],
                      "LocalizationStrings": {}, "source_pairing": pair,
                      "view": view, "runtime_mount_order_verified": False}
            write_output_json(destination / view / (table + ".json"), output, root, inputs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    exp = sub.add_parser("export")
    exp.add_argument("--output-dir", type=Path, default=Path("build/raw-content"))
    get = sub.add_parser("get")
    get.add_argument("--table", choices=TABLES, required=True)
    get.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.repo)
        if args.command == "verify":
            for path, key in (("data/evidence/raw_content_audit.json", "audit"),
                              ("data/supplements/binary_content_recovery.json", "recovery")):
                expected = json.loads((args.repo / path).read_text(encoding="utf-8"))
                if expected != result[key]:
                    raise ValueError("Checked-in raw evidence is not reproducible: " + path)
        elif args.command == "export":
            export(result, args.repo, args.output_dir)
        if args.command == "get":
            output = next((x for x in result["resolved"]["resolved_records"]
                           if x["table"] == args.table and x["id"] == args.id), None)
            if output is None:
                raise ValueError("ID not in referenced raw recovery")
        else:
            output = result["audit"]["summary"]
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
