#!/usr/bin/env python3
"""Search names in a candidate Pak-effective view and compare snapshot metadata.

Pure standard library. Raw source JSON is opened on demand, verified with SHA256,
and NEVER copied to repository output. The effective file priority remains a
hypothesis until the game's mount order has been independently verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import build_catalog
import effective_view

# Curated tables/fields, deliberately excluding full dialogues and descriptions.
# Optional source tables/fields vary by client build and are skipped when absent.
DOMAIN_TABLES: dict[str, dict[str, tuple[str, ...]]] = {
    "pet": {
        "PETBASE_CONF": ("name",), "PET_CONF": ("name",),
        "PET_NAME_MAP_CONF": ("name",), "PET_HANDBOOK": ("name",),
    },
    "skill": {"SKILL_CONF": ("name",)},
    "map": {
        "WORLD_MAP_CONF": ("zone_name", "zone_name_roco", "element_text_name"),
        "AREA_CONF": ("name", "area_name"),
        "SCENE_CONF": ("name", "scene_name"),
    },
    "task": {
        "TASK_CONF": ("name",), "TASK_SUMMARY": ("task_name",),
        "CHAPTER_CONF": ("title",),
    },
    "item": {
        "BAG_ITEM_CONF": ("name", "known_name"),
        "IMPORTANT_ITEM_CONF": ("name",),
        "SEASON_ITEM_CONF": ("name",),
        "FASHION_ITEM_CONF": ("name",),
        "FURNITURE_ITEM_CONF": ("name",),
    },
    "npc": {"NPC_CONF": ("name", "show_name", "title")},
    "season": {
        "SEASON_CONF": ("s_title", "s_title_subtitle"),
        "SEASON_ADVENTURE_CONF": ("name",),
        "SEASON_ADVENTURE_CHAPTER": ("chapter_name", "chapter_story_name"),
    },
}
NAME_FIELDS = frozenset(field for tables in DOMAIN_TABLES.values()
                        for fields in tables.values() for field in fields)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def load_view(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as file:
        obj = json.load(file)
    if not isinstance(obj, dict) or obj.get("view_format") != effective_view.FORMAT:
        raise ValueError("Not a supported candidate effective view")
    if not isinstance(obj.get("tables"), list) or not isinstance(obj.get("localizations", []), list):
        raise ValueError("Candidate view lacks table/localization listings")
    return obj


def index_tables(view: dict) -> dict[str, dict]:
    """Fail closed on duplicate, malformed or forged path/hash metadata."""
    out = {}
    for row in view["tables"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid effective table descriptor")
        table, layer, path, digest = (row.get(key) for key in
                                       ("table", "data_layer", "data_path", "source_sha256"))
        if not all(isinstance(x, str) for x in (table, layer, path, digest)):
            raise ValueError("Missing effective table source metadata")
        effective_view.safe_table_path(path, layer, table)
        if not SHA256.fullmatch(digest):
            raise ValueError(f"Invalid SHA256 digest for {table}")
        count = row.get("row_count")
        if type(count) is not int or count < 0:
            raise ValueError(f"Invalid row count for {table}")
        if table in out:
            raise ValueError(f"Duplicate effective table: {table}")
        out[table] = row
    return out


def index_localizations(view: dict) -> dict[str, dict]:
    out = {}
    for row in view.get("localizations", []):
        if not isinstance(row, dict):
            raise ValueError("Invalid localization descriptor")
        key, path, layer, digest = (row.get(k) for k in
                                    ("locale_file", "data_path", "data_layer", "source_sha256"))
        if not all(isinstance(x, str) for x in (key, path, layer, digest)):
            raise ValueError("Missing localization source metadata")
        if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.json", key):
            raise ValueError("Invalid localization key")
        if path != f"{layer}/Bin/BinLocalize/{key}" or not SHA256.fullmatch(digest):
            raise ValueError("Invalid localization source path or digest")
        if key in out:
            raise ValueError(f"Duplicate localization: {key}")
        out[key] = row
    return out


def name_search(root: Path, view: dict, query: str, domains: list[str] | None = None,
                tables: list[str] | None = None, fields: list[str] | None = None,
                limit: int = 20, exact: bool = False) -> dict:
    """Search explicit name-like fields in the selected whole-file snapshot."""
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("Query must contain 1-200 nonblank characters")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("--limit must be between 1 and 100")
    descriptors = index_tables(view)
    selected: dict[str, set[str]] = {}
    if tables:
        if fields:
            if any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x)
                   for x in fields):
                raise ValueError("Invalid --field name")
            wanted_fields = set(fields)
        else:
            wanted_fields = set(NAME_FIELDS)
        for table in tables:
            key = table if "/" in table else "BinDataCompressed/" + table.removesuffix(".json")
            if key not in descriptors:
                raise ValueError(f"Unknown table {key}")
            selected[key] = wanted_fields.copy()
    else:
        groups = domains or list(DOMAIN_TABLES)
        if fields:
            raise ValueError("--field requires --table to avoid scanning arbitrary text")
        for group in groups:
            if group not in DOMAIN_TABLES:
                raise ValueError(f"Unknown name-search domain {group}")
            for table, columns in DOMAIN_TABLES[group].items():
                key = "BinDataCompressed/" + table
                if key in descriptors:
                    selected.setdefault(key, set()).update(columns)
    query_fold = query.strip().casefold()
    matches: list[dict] = []
    total = 0
    examined = 0
    for table in sorted(selected):
        descriptor = descriptors[table]
        rows = effective_view.load_selected_rows(root, descriptor)
        columns = selected[table]
        for record_id, record in rows.items():
            examined += 1
            if not isinstance(record, dict):
                continue
            found = []
            for field in sorted(columns):
                value = record.get(field)
                if not isinstance(value, str) or not value or len(value) > 400:
                    continue
                compare = value.casefold()
                if (compare == query_fold if exact else query_fold in compare):
                    found.append({"field": field, "name": value[:120]})
            if found:
                total += 1
                if len(matches) < limit:
                    matches.append({"table": table, "id": str(record_id),
                                    "source_layer": descriptor["data_layer"], "names": found})
    return {
        "snapshot_label": view.get("snapshot_label"),
        "source_commit": view.get("source_commit"),
        "pak_mount_order_verified": view.get("pak_mount_order_verified", False),
        "query": query.strip(), "exact": exact,
        "tables_searched": list(sorted(selected)), "records_examined": examined,
        "total_matches": total, "results": matches, "truncated": total > limit,
        "notice": "Read-only candidate view: text names shown only in local command output.",
    }


def _change_group(before: dict, after: dict) -> dict:
    added, removed, modified, relocated, unchanged = [], [], [], [], 0
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old is None:
            added.append(key)
        elif new is None:
            removed.append(key)
        elif old["source_sha256"] != new["source_sha256"]:
            modified.append(key)
        elif old["data_path"] != new["data_path"]:
            relocated.append(key)
        else:
            unchanged += 1
    return {"added": added, "removed": removed, "modified": modified,
            "relocated_identical_content": relocated, "unchanged": unchanged,
            "summary": {"added": len(added), "removed": len(removed),
                        "modified": len(modified),
                        "relocated_identical_content": len(relocated), "unchanged": unchanged}}


def compare_views(before: dict, after: dict) -> dict:
    """Metadata-only incremental diff. No game dialogue or row payloads."""
    a, b = index_tables(before), index_tables(after)
    loc_a, loc_b = index_localizations(before), index_localizations(after)
    table_changes = _change_group(a, b)
    loc_changes = _change_group(loc_a, loc_b)
    details = []
    for name in table_changes["modified"]:
        old, new = a[name], b[name]
        details.append({"table": name, "before_layer": old["data_layer"],
                        "after_layer": new["data_layer"],
                        "before_sha256": old["source_sha256"],
                        "after_sha256": new["source_sha256"],
                        "before_rows": old["row_count"], "after_rows": new["row_count"],
                        "row_count_delta": new["row_count"]-old["row_count"]})
    return {
        "diff_format": "1.0",
        "before": {"snapshot_label": before.get("snapshot_label"),
                   "source_commit": before.get("source_commit")},
        "after": {"snapshot_label": after.get("snapshot_label"),
                  "source_commit": after.get("source_commit")},
        "priority_inference_only": not (before.get("pak_mount_order_verified", False)
                                         and after.get("pak_mount_order_verified", False)),
        "before_priority_low_to_high": before.get("priority_low_to_high"),
        "after_priority_low_to_high": after.get("priority_low_to_high"),
        "tables": table_changes, "localizations": loc_changes,
        "modified_table_details": details,
        "notice": "SHA256-based file-level diff; no record-level changes inferred from file size.",
    }


def _row_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def row_id_differences(before: dict, after: dict, before_root: Path, after_root: Path,
                       sample_limit: int = 10) -> dict:
    """Optional verified per-ID comparison; only selected changed source files."""
    if type(sample_limit) is not int or not 1 <= sample_limit <= 50:
        raise ValueError("--sample-limit must be 1-50")
    old, new = index_tables(before), index_tables(after)
    changed = compare_views(before, after)["tables"]
    result = []
    for table in sorted(changed["added"] + changed["removed"] + changed["modified"]):
        left = effective_view.load_selected_rows(before_root, old[table]) if table in old else {}
        right = effective_view.load_selected_rows(after_root, new[table]) if table in new else {}
        left_ids, right_ids = set(left), set(right)
        added = sorted(right_ids - left_ids)
        removed = sorted(left_ids - right_ids)
        changed_ids = sorted(k for k in left_ids & right_ids if _row_hash(left[k]) != _row_hash(right[k]))
        result.append({"table": table,
                       "added_count": len(added), "removed_count": len(removed),
                       "changed_count": len(changed_ids),
                       "added_id_sample": added[:sample_limit],
                       "removed_id_sample": removed[:sample_limit],
                       "changed_id_sample": changed_ids[:sample_limit]})
    return {"table_diffs": result, "sample_limit": sample_limit,
            "verified_selected_source_sha256": True,
            "notice": "ID and content-hash differences only; record payloads are not exported."}


def print_result(result: dict) -> None:
    """Prefer readable UTF-8; fall back to ASCII escapes for legacy Windows pipes."""
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        try:
            rendered.encode(encoding)
        except (UnicodeEncodeError, LookupError):
            rendered = json.dumps(result, ensure_ascii=True, indent=2)
    print(rendered)


def reject_pak_output(path: Path) -> None:
    if any(part.startswith("pakchunk") for part in path.resolve().parts):
        raise ValueError("Refusing to write comparison report inside a Pak directory")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search", help="Search safe name fields in selected effective tables")
    s.add_argument("--view", type=Path, required=True)
    s.add_argument("--root", type=Path, default=Path("."))
    s.add_argument("--query", required=True)
    s.add_argument("--domain", action="append", choices=list(DOMAIN_TABLES))
    s.add_argument("--table", action="append", help="Exact table name; repeatable")
    s.add_argument("--field", action="append", help="Field filter; requires --table")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--exact", action="store_true")
    d = sub.add_parser("compare", help="Compare two effective manifests by file SHA256")
    d.add_argument("--before", type=Path, required=True)
    d.add_argument("--after", type=Path, required=True)
    d.add_argument("--output", type=Path, help="Optional local JSON report path")
    d.add_argument("--before-root", type=Path)
    d.add_argument("--after-root", type=Path)
    d.add_argument("--row-ids", action="store_true", help="Verify changed files and compare row IDs")
    d.add_argument("--sample-limit", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            view = load_view(args.view)
            result = name_search(args.root, view, args.query, args.domain,
                                 args.table, args.field, args.limit, args.exact)
        else:
            before, after = load_view(args.before), load_view(args.after)
            result = compare_views(before, after)
            if args.row_ids:
                if args.before_root is None or args.after_root is None:
                    raise ValueError("--row-ids requires both --before-root and --after-root")
                result["row_ids"] = row_id_differences(before, after,
                                                        args.before_root, args.after_root,
                                                        args.sample_limit)
            if args.output:
                reject_pak_output(args.output)
                if args.output.resolve() in (args.before.resolve(), args.after.resolve()):
                    raise ValueError("Cannot overwrite either input effective view")
                for root in (args.before_root, args.after_root):
                    if root is not None:
                        build_catalog.guard_output(args.output, root.resolve())
                build_catalog.atomic_json(args.output, result)
        print_result(result)
        return 0
    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
