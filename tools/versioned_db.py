#!/usr/bin/env python3
"""Offline, read-only source importer and multi-version index for RocoDataRows JSON.

Input game data is never modified. SQLite and generated reports are local outputs.
Only Python 3.10+ standard library modules are used.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

VERSION = "0.2.0"
DB_SCHEMA_VERSION = 2
READ_SIZE = 1024 * 1024


CREATE_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_commit TEXT,
    source_date TEXT,
    game_build TEXT,
    season TEXT,
    fingerprint TEXT NOT NULL,
    imported_utc TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    runtime_permission TEXT NOT NULL DEFAULT 'none'
        CHECK(runtime_permission = 'none')
);
CREATE TABLE IF NOT EXISTS source_files (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE RESTRICT,
    table_name TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    schema_sha256 TEXT,
    row_count INTEGER NOT NULL CHECK(row_count >= 0),
    unique_key TEXT NOT NULL,
    declared_fields_json TEXT NOT NULL,
    observed_fields_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, table_name)
);
CREATE TABLE IF NOT EXISTS records (
    snapshot_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    record_id TEXT NOT NULL,
    row_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, table_name, record_id),
    FOREIGN KEY(snapshot_id, table_name)
        REFERENCES source_files(snapshot_id, table_name) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS quality_issues (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE RESTRICT,
    table_name TEXT NOT NULL,
    record_id TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, table_name, record_id, issue_type)
);
CREATE INDEX IF NOT EXISTS ix_records_table ON records(snapshot_id, table_name);
CREATE INDEX IF NOT EXISTS ix_quality_issues ON quality_issues(snapshot_id, issue_type);
"""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(READ_SIZE), b""):
            h.update(part)
    return h.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        obj[key] = value
    return obj


def _reject_nonfinite(constant: str) -> None:
    raise ValueError(f"Invalid JSON numeric constant: {constant}")


def parse_json_file(path: Path, expected_sha256: str | None = None) -> Any:
    data = path.read_bytes()
    if expected_sha256 is not None and hash_bytes(data) != expected_sha256:
        raise ValueError(f"Source changed while reading, retry from a stable copy: {path}")
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_reject_duplicate_keys,
                          parse_constant=_reject_nonfinite)
    except UnicodeDecodeError as ex:
        raise ValueError(f"Invalid UTF-8 in {path}: {ex}") from ex
    except json.JSONDecodeError as ex:
        raise ValueError(f"Invalid JSON in {path}: {ex}") from ex


def read_data(path: Path, sha256: str | None = None) -> dict[str, dict]:
    document = parse_json_file(path, sha256)
    if not isinstance(document, dict) or not isinstance(document.get("RocoDataRows"), dict):
        raise ValueError(f"Expected an object with RocoDataRows dictionary: {path}")
    rows = document["RocoDataRows"]
    for rid, row in rows.items():
        if not isinstance(row, dict):
            raise ValueError(f"Non-object row in {path}, record {rid}")
    return rows


def read_schema(path: Path, sha256: str | None = None) -> tuple[str, list[str]]:
    document = parse_json_file(path, sha256)
    if not isinstance(document, dict) or not isinstance(document.get("Properties"), list):
        raise ValueError(f"Expected schema Properties list: {path}")
    key = document.get("UniqueKey") or "id"
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"Invalid schema UniqueKey: {path}")
    fields = []
    for prop in document["Properties"]:
        if not isinstance(prop, dict) or not isinstance(prop.get("Name"), str):
            raise ValueError(f"Invalid schema property: {path}")
        fields.append(prop["Name"])
    if len(fields) != len(set(fields)):
        raise ValueError(f"Duplicate property names in schema: {path}")
    return key, sorted(fields)


def inspect_files(data_dir: Path, schema_dir: Path | None) -> tuple[list[dict], str]:
    if not data_dir.is_dir():
        raise ValueError(f"Missing data directory: {data_dir}")
    if schema_dir is not None and not schema_dir.is_dir():
        raise ValueError(f"Missing schema directory: {schema_dir}")
    paths = sorted(data_dir.glob("*.json"), key=lambda x: x.name)
    if not paths:
        raise ValueError(f"No .json input tables in: {data_dir}")
    inventory: list[dict] = []
    digest = hashlib.sha256()
    for path in paths:
        schema_path = schema_dir / path.name if schema_dir is not None else None
        schema_hash = hash_file(schema_path) if schema_path and schema_path.is_file() else None
        entry = {"table": path.stem, "file": path, "source_sha256": hash_file(path),
                 "schema_file": schema_path if schema_hash else None,
                 "schema_sha256": schema_hash}
        inventory.append(entry)
        digest.update((canonical_json([path.name, entry["source_sha256"], schema_hash]) + "\n").encode("utf-8"))
    return inventory, digest.hexdigest()


def connect_database(path: Path, create: bool = True) -> sqlite3.Connection:
    if not create and not path.is_file():
        raise ValueError(f"Database does not exist: {path}")
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = sqlite3.Row
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, DB_SCHEMA_VERSION):
            raise ValueError(f"Unsupported SQLite schema version {version}; use a new database path")
        if version == 0 and not create:
            raise ValueError(f"Uninitialized database: {path}")
        if version == 0:
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='snapshots'").fetchone():
                raise ValueError("Legacy unversioned database found; use a new database path (schema version 2)")
            with db:
                db.executescript(CREATE_SQL)
                db.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
    except Exception:
        db.close()
        raise
    return db


def check_destination(database: Path, data_dir: Path, schema_dir: Path | None) -> None:
    destination = database.resolve()
    for folder in (data_dir, schema_dir):
        if folder is not None and destination.is_relative_to(folder.resolve()):
            raise ValueError(f"Refusing to write database inside input directory: {folder}")


def collect_table(entry: dict, schema_dir_requested: bool) -> tuple[dict, list[tuple[str, str]]]:
    rows = read_data(entry["file"], entry["source_sha256"])
    missing = schema_dir_requested and entry["schema_file"] is None
    key, declared = read_schema(entry["schema_file"], entry["schema_sha256"]) if entry["schema_file"] else ("id", [])
    fields: set[str] = set()
    errors: list[tuple[str, str]] = []
    if missing:
        errors.append(("", "missing_schema"))
    if entry["schema_file"] is None and not schema_dir_requested:
        errors.append(("", "schema_not_supplied"))
    for record_id, row in rows.items():
        fields.update(row)
        if key not in row:
            errors.append((record_id, "missing_unique_key"))
        elif str(row[key]) != record_id:
            errors.append((record_id, "unique_key_mismatch"))
    summary = {"table_name": entry["table"], "source_sha256": entry["source_sha256"],
               "schema_sha256": entry["schema_sha256"], "rows": rows, "row_count": len(rows),
               "unique_key": key, "declared_fields": declared, "observed_fields": sorted(fields)}
    return summary, errors


def ingest(args: argparse.Namespace) -> dict:
    data_dir = Path(args.data_dir)
    schema_dir = Path(args.schema_dir) if args.schema_dir else None
    db_path = Path(args.database)
    check_destination(db_path, data_dir, schema_dir)
    entries, fingerprint = inspect_files(data_dir, schema_dir)
    db = connect_database(db_path)
    try:
        provenance = (fingerprint, args.source_kind, args.source_ref, args.source_commit,
                      args.source_date, args.game_build, args.season)
        existing = db.execute("""SELECT fingerprint,source_kind,source_ref,source_commit,
            source_date,game_build,season FROM snapshots WHERE snapshot_id=?""", (args.snapshot_id,)).fetchone()
        if existing is not None:
            if tuple(existing) == provenance:
                return {"snapshot_id": args.snapshot_id, "status": "unchanged", "fingerprint": fingerprint}
            raise ValueError("Snapshot ID already used with different files or metadata; choose a new ID")
        n_records = n_issues = 0
        with db:
            db.execute("""INSERT INTO snapshots(snapshot_id,source_kind,source_ref,source_commit,
                source_date,game_build,season,fingerprint,imported_utc,tool_version)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (args.snapshot_id, args.source_kind, args.source_ref,
                args.source_commit, args.source_date, args.game_build, args.season, fingerprint,
                datetime.now(timezone.utc).isoformat(timespec="seconds"), VERSION))
            for entry in entries:
                summary, issues = collect_table(entry, schema_dir is not None)
                name = summary["table_name"]
                db.execute("""INSERT INTO source_files(snapshot_id,table_name,source_sha256,
                    schema_sha256,row_count,unique_key,declared_fields_json,observed_fields_json)
                    VALUES(?,?,?,?,?,?,?,?)""", (args.snapshot_id, name, summary["source_sha256"],
                    summary["schema_sha256"], summary["row_count"], summary["unique_key"],
                    canonical_json(summary["declared_fields"]), canonical_json(summary["observed_fields"])))
                batch: list[tuple[str, str, str, str, str]] = []
                for rid, row in summary["rows"].items():
                    payload = canonical_json(row)
                    batch.append((args.snapshot_id, name, rid, hash_bytes(payload.encode("utf-8")), payload))
                    if len(batch) >= 1000:
                        db.executemany("INSERT INTO records VALUES(?,?,?,?,?)", batch)
                        batch.clear()
                if batch:
                    db.executemany("INSERT INTO records VALUES(?,?,?,?,?)", batch)
                if issues:
                    db.executemany("INSERT INTO quality_issues VALUES(?,?,?,?)",
                                   [(args.snapshot_id, name, rid, issue) for rid, issue in issues])
                n_records += summary["row_count"]
                n_issues += len(issues)
        return {"snapshot_id": args.snapshot_id, "status": "created", "tables": len(entries),
                "records": n_records, "issues": n_issues, "fingerprint": fingerprint,
                "game_build": args.game_build, "tool_version": VERSION}
    finally:
        db.close()


def snapshot(db: sqlite3.Connection, snapshot_id: str) -> dict:
    record = db.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    if record is None:
        raise ValueError(f"Unknown snapshot: {snapshot_id}")
    return dict(record)


def report_manifest(args: argparse.Namespace) -> dict:
    db = connect_database(Path(args.database), create=False)
    try:
        meta = snapshot(db, args.snapshot_id)
        tables = []
        for x in db.execute("SELECT * FROM source_files WHERE snapshot_id=? ORDER BY table_name", (args.snapshot_id,)):
            item = dict(x)
            for k in ("declared_fields_json", "observed_fields_json"):
                item[k.removesuffix("_json")] = json.loads(item.pop(k))
            tables.append(item)
        issues = {x[0]: x[1] for x in db.execute("""SELECT issue_type, COUNT(*) FROM quality_issues
            WHERE snapshot_id=? GROUP BY issue_type ORDER BY issue_type""", (args.snapshot_id,))}
        return {"snapshot": meta, "total_tables": len(tables), "total_records": sum(x["row_count"] for x in tables),
                "quality_issue_counts": issues, "tables": tables}
    finally:
        db.close()


def compare(args: argparse.Namespace) -> dict:
    db = connect_database(Path(args.database), create=False)
    try:
        before = snapshot(db, args.before)
        after = snapshot(db, args.after)
        def files(sid: str) -> dict:
            return {r["table_name"]: dict(r) for r in db.execute(
                "SELECT * FROM source_files WHERE snapshot_id=?", (sid,))}
        old, new = files(args.before), files(args.after)
        changed = []
        for name in sorted(old.keys() & new.keys()):
            a, b = old[name], new[name]
            if (a["source_sha256"], a["schema_sha256"]) == (b["source_sha256"], b["schema_sha256"]):
                continue
            a_rows = dict(db.execute("SELECT record_id,row_sha256 FROM records WHERE snapshot_id=? AND table_name=?",
                                     (args.before, name)))
            b_rows = dict(db.execute("SELECT record_id,row_sha256 FROM records WHERE snapshot_id=? AND table_name=?",
                                     (args.after, name)))
            added = b_rows.keys() - a_rows.keys()
            removed = a_rows.keys() - b_rows.keys()
            modified = {rid for rid in a_rows.keys() & b_rows.keys() if a_rows[rid] != b_rows[rid]}
            a_fields = set(json.loads(a["observed_fields_json"]))
            b_fields = set(json.loads(b["observed_fields_json"]))
            a_decl = set(json.loads(a["declared_fields_json"]))
            b_decl = set(json.loads(b["declared_fields_json"]))
            changed.append({"table": name, "old_rows": a["row_count"], "new_rows": b["row_count"],
                            "added": len(added), "removed": len(removed), "modified": len(modified),
                            "sample_added": sorted(added)[:10], "sample_removed": sorted(removed)[:10],
                            "sample_modified": sorted(modified)[:10],
                            "schema_changed": a["schema_sha256"] != b["schema_sha256"],
                            "source_bytes_changed": a["source_sha256"] != b["source_sha256"],
                            "schema_fields_added": sorted(b_decl - a_decl),
                            "schema_fields_removed": sorted(a_decl - b_decl),
                            "observed_fields_added": sorted(b_fields - a_fields),
                            "observed_fields_removed": sorted(a_fields - b_fields)})
        return {"before": before, "after": after,
                "tables_added": sorted(new.keys() - old.keys()),
                "tables_removed": sorted(old.keys() - new.keys()),
                "tables_changed": changed}
    finally:
        db.close()


def verify(args: argparse.Namespace) -> dict:
    db = connect_database(Path(args.database), create=False)
    try:
        snapshot(db, args.snapshot_id)
        data_dir = Path(args.data_dir)
        schema_dir = Path(args.schema_dir) if args.schema_dir else None
        actual, _ = inspect_files(data_dir, schema_dir)
        old = {r["table_name"]: r for r in db.execute(
            "SELECT * FROM source_files WHERE snapshot_id=?", (args.snapshot_id,))}
        files = {x["table"]: x for x in actual}
        mismatches = []
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            mismatches.append({"table": "", "issue": "sqlite_integrity_check_failed"})
        stored_fingerprint = hashlib.sha256()
        for name in sorted(old):
            f = old[name]
            stored_fingerprint.update((canonical_json([name + ".json", f["source_sha256"],
                                                       f["schema_sha256"]]) + "\n").encode("utf-8"))
        if stored_fingerprint.hexdigest() != snapshot(db, args.snapshot_id)["fingerprint"]:
            mismatches.append({"table": "", "issue": "stored_inventory_fingerprint_mismatch"})
        record_count = 0
        per_table_counts = defaultdict(int)
        for row in db.execute("SELECT table_name,record_id,payload_json,row_sha256 FROM records WHERE snapshot_id=?",
                              (args.snapshot_id,)):
            record_count += 1
            per_table_counts[row["table_name"]] += 1
            if hash_bytes(row["payload_json"].encode("utf-8")) != row["row_sha256"]:
                if sum(x["issue"] == "database_record_hash_mismatch" for x in mismatches) < 30:
                    mismatches.append({"table": row["table_name"], "record_id": row["record_id"],
                                       "issue": "database_record_hash_mismatch"})
        for name, info in sorted(old.items()):
            if per_table_counts[name] != info["row_count"]:
                mismatches.append({"table": name, "issue": "database_record_count_mismatch",
                                   "expected": info["row_count"], "actual": per_table_counts[name]})
        for name in sorted(old.keys() | files.keys()):
            a, b = old.get(name), files.get(name)
            if a is None:
                mismatches.append({"table": name, "issue": "unexpected_source_file"})
            elif b is None:
                mismatches.append({"table": name, "issue": "source_file_missing"})
            else:
                if a["source_sha256"] != b["source_sha256"]:
                    mismatches.append({"table": name, "issue": "source_hash_mismatch"})
                if schema_dir is not None and a["schema_sha256"] != b["schema_sha256"]:
                    mismatches.append({"table": name, "issue": "schema_hash_mismatch"})
        return {"snapshot_id": args.snapshot_id, "verified": len(mismatches) == 0,
                "checked_tables": len(old), "checked_database_records": record_count,
                "schema_checked": schema_dir is not None,
                "sqlite_integrity_check": integrity, "mismatches": mismatches}
    finally:
        db.close()


def inventory_report(args: argparse.Namespace) -> dict:
    data_dir = Path(args.data_dir)
    schema_dir = Path(args.schema_dir) if args.schema_dir else None
    entries, fingerprint = inspect_files(data_dir, schema_dir)
    tables = []
    issues = []
    for entry in entries:
        s, table_issues = collect_table(entry, schema_dir is not None)
        tables.append({k: v for k, v in s.items() if k != "rows"})
        for rid, kind in table_issues:
            issues.append({"table": entry["table"], "record_id": rid, "issue_type": kind})
    return {"tool_version": VERSION, "data_dir": str(data_dir),
            "schema_dir": str(schema_dir) if schema_dir is not None else None,
            "fingerprint": fingerprint, "tables": tables,
            "total_tables": len(tables), "total_records": sum(t["row_count"] for t in tables),
            "issues": issues, "issue_count": len(issues)}


def arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    def add_sources(x: argparse.ArgumentParser):
        x.add_argument("--data-dir", required=True)
        x.add_argument("--schema-dir")
    inv = sub.add_parser("inventory", help="Scan local JSON and schema, producing metadata only")
    add_sources(inv)
    add = sub.add_parser("ingest", help="Import immutable source data into a versioned SQLite snapshot")
    add_sources(add)
    add.add_argument("--database", default="build/roco_versions_v2.sqlite")
    add.add_argument("--snapshot-id", required=True)
    add.add_argument("--source-kind", required=True, choices=[
        "third_party_historical", "local_client_offline", "official_public"])
    add.add_argument("--source-ref", required=True)
    add.add_argument("--source-commit")
    add.add_argument("--source-date")
    add.add_argument("--game-build", help="Only if verifiable from source")
    add.add_argument("--season", help="Only if verifiable from source")
    man = sub.add_parser("manifest", help="Export snapshot metadata: never includes record payloads")
    man.add_argument("--database", default="build/roco_versions_v2.sqlite")
    man.add_argument("--snapshot-id", required=True)
    diff = sub.add_parser("compare", help="Diff two snapshots without dumping record text")
    diff.add_argument("--database", default="build/roco_versions_v2.sqlite")
    diff.add_argument("--before", required=True)
    diff.add_argument("--after", required=True)
    check = sub.add_parser("verify", help="Verify source and optional schema hashes against a snapshot")
    add_sources(check)
    check.add_argument("--database", default="build/roco_versions_v2.sqlite")
    check.add_argument("--snapshot-id", required=True)
    for p2 in (inv, add, man, diff, check):
        p2.add_argument("--output", help="Write JSON report to this path, else stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = arg_parser().parse_args(argv)
    try:
        fn = {"inventory": inventory_report, "ingest": ingest, "manifest": report_manifest,
              "compare": compare, "verify": verify}[args.command]
        report = fn(args)
        payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            destination = Path(args.output)
            if args.command in ("inventory", "ingest", "verify"):
                for folder in (args.data_dir, args.schema_dir):
                    if folder and destination.resolve().is_relative_to(Path(folder).resolve()):
                        raise ValueError(f"Refusing to write report inside source directory: {folder}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(payload, encoding="utf-8")
            print(f"Report written to: {destination}")
        else:
            print(payload, end="")
        return 2 if args.command == "verify" and not report["verified"] else 0
    except (ValueError, OSError, sqlite3.Error, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
