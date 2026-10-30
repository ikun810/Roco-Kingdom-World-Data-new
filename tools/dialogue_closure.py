#!/usr/bin/env python3
"""Audit explicit dialogue/choice references and prepare additive source recovery."""
import argparse
from collections import Counter, deque
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import ZipFile, BadZipFile

from content_supplement import git_blob_sha, resolve, sha256_file, write_output_json

TABLES = ("DIALOGUE_CONF", "SELECT_CONF")
LINKS = {
    "DIALOGUE_CONF": (("next_dialog_id", "DIALOGUE_CONF", False),
                      ("select_ids", "SELECT_CONF", True)),
    "SELECT_CONF": (("select_next_dialogue", "DIALOGUE_CONF", False),
                    ("notimes_dialogue", "DIALOGUE_CONF", False)),
}


def _key(table, ident):
    ident = str(ident)
    if table not in TABLES or not ident.isdecimal() or int(ident) <= 0:
        raise ValueError("Invalid graph table or record ID")
    return table, ident


def trace_graph(current, historical, roots):
    """Follow observed edges; current rows always win, without merging fields."""
    queue = deque(_key(t, i) for t, i in roots)
    seen, nodes, edges, missing, additions, reviews = set(), [], [], [], [], []
    while queue:
        table, ident = queue.popleft()
        if (table, ident) in seen:
            continue
        seen.add((table, ident))
        if ident in current[table]:
            row, origin = current[table][ident], "current_archive"
        elif ident in historical[table]:
            row, origin = historical[table][ident], "historical_fallback"
        else:
            missing.append({"table": table, "id": ident})
            continue
        if not isinstance(row, dict) or str(row.get("id")) != ident:
            raise ValueError("Graph record ID differs from its source key")
        nodes.append({"table": table, "id": ident, "origin": origin})
        if origin == "historical_fallback":
            additions.append({"table": table, "id": ident, "record": row})
        old = historical[table].get(ident)
        if table == "SELECT_CONF" and origin == "current_archive" and old is not None:
            if str(old.get("id")) != ident:
                raise ValueError("Historical record ID differs from its source key")
            if row.get("text") != old.get("text"):
                reviews.append({"table": table, "id": ident, "fields": ["text"],
                                "record": old})
        for field, target_table, is_array in LINKS[table]:
            if field not in row:
                continue
            values = row[field] if is_array else [row[field]]
            if not isinstance(values, list):
                raise ValueError("Reference array is not a list: " + field)
            for index, value in enumerate(values):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError("Reference is not an integer: " + field)
                if value <= 0:
                    continue
                target_id = str(value)
                edge = {"from_table": table, "from_id": ident,
                        "field": field + ("/" + str(index) if is_array else ""),
                        "to_table": target_table, "to_id": target_id,
                        "source": origin}
                edges.append(edge)
                queue.append((target_table, target_id))
    for group in (nodes, missing, additions, reviews):
        group.sort(key=lambda r: (r["table"], int(r["id"])))
    edges.sort(key=lambda e: (e["from_table"], int(e["from_id"]), e["field"],
                              e["to_table"], int(e["to_id"])))
    return {"nodes": nodes, "edges": edges, "missing": missing,
            "additions": additions, "text_reviews": reviews}


def _read_history(root, source, table):
    name, sha = source["path"], source["git_blob_sha"]
    p = PurePosixPath(name)
    if (p.is_absolute() or ".." in p.parts or "\\" in name or
            not re.fullmatch(r"[0-9a-f]{40}", sha)):
        raise ValueError("Unsafe historical source")
    path = root.joinpath(*p.parts)
    if (path.is_symlink() or not path.resolve().is_relative_to(root) or
            p.name != table + ".json"):
        raise ValueError("Historical source does not match the declared table")
    raw = path.read_bytes()
    if git_blob_sha(raw) != sha:
        raise ValueError("Historical Git blob SHA mismatch")
    return json.loads(raw.decode("utf-8-sig"))["RocoDataRows"]


def audit(archive, supplement, history_root):
    """Validate the supplied source supplement before deriving reference coverage."""
    resolved = resolve(archive, supplement, history_root)
    config = supplement["dialogue_reference_scope"]
    root = Path(history_root).resolve()
    historical = {table: _read_history(root, config["historical_sources"][table], table)
                  for table in TABLES}
    with ZipFile(archive) as z:
        current = {table: json.loads(z.read("BinDataCompressed/" + table + ".json")
                                    .decode("utf-8-sig"))["RocoDataRows"] for table in TABLES}
    roots = [("DIALOGUE_CONF", ident) for ident in config["root_dialogue_ids"]]
    result = trace_graph(current, historical, roots)
    incoming = {}
    for edge in result["edges"]:
        incoming.setdefault((edge["to_table"], edge["to_id"]), []).append(edge)
    expanded = deepcopy(supplement)
    existing = {(x["table"], str(x["id"])): x for x in expanded["entries"]}
    new_count = Counter()
    for group, operation in (("additions", "add_if_absent"), ("text_reviews", "review_conflict")):
        for row in result[group]:
            key = (row["table"], row["id"])
            if key in existing:
                old = existing[key]
                if old["operation"] != operation or old["record"] != row["record"]:
                    raise ValueError("Existing supplement conflicts with graph evidence")
                if operation == "review_conflict" and "text" not in old["fields"]:
                    raise ValueError("Existing selector review does not cover text")
                continue
            source = config["historical_sources"][row["table"]]
            item = {"table": row["table"], "id": row["id"], "operation": operation,
                    "fields": row.get("fields", []), "source_path": source["path"],
                    "source_blob_sha": source["git_blob_sha"], "record": row["record"],
                    "referenced_by": incoming.get(key, [])}
            expanded["entries"].append(item)
            existing[key] = item
            new_count[operation] += 1
    for row in result["missing"]:
        if not any((u["table"], str(u["id"])) == (row["table"], row["id"])
                   for u in expanded["unresolved"]):
            expanded["unresolved"].append({**row, "reason": "Explicit dialogue reference has no source row"})
    counts = Counter(x["operation"] for x in expanded["entries"])
    expanded["summary"].update({"entry_count": len(expanded["entries"]), **counts,
                                "missing_from_checked_history": len(expanded["unresolved"])})
    report = {
        "format": "roco_dialogue_reference_audit_v1",
        "target_archive_sha256": sha256_file(archive),
        "historical_is_not_verified_as_current": True,
        "scope": config,
        "summary": {"root_dialogue_count": len(roots), "node_count": len(result["nodes"]),
                    "edge_count": len(result["edges"]), "missing_target_count": len(result["missing"]),
                    "historical_dialogue_count": sum(n["table"] == "DIALOGUE_CONF" and
                         n["origin"] == "historical_fallback" for n in result["nodes"]),
                    "current_selector_count": sum(n["table"] == "SELECT_CONF" and
                         n["origin"] == "current_archive" for n in result["nodes"]),
                    "selector_text_review_count": len(result["text_reviews"]),
                    "new_additions": new_count["add_if_absent"],
                    "new_reviews": new_count["review_conflict"],
                    "input_supplement_summary": resolved["summary"]},
        "nodes": result["nodes"], "edges": result["edges"], "missing": result["missing"],
        "limits": ["Only the four explicitly listed reference fields are followed.",
                   "Existing rows are traversed as exported, without historical field replacement.",
                   "Zero missing targets is structural coverage, not proof of correct current text, condition evaluation, game receipts or story playability."]}
    return report, expanded


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("data/current.zip"))
    parser.add_argument("--supplement", type=Path, default=Path("data/supplements/referenced_content.json"))
    parser.add_argument("--history-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("build/dialogue_reference_audit.json"))
    parser.add_argument("--expanded-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.expanded_output and args.output.resolve() == args.expanded_output.resolve():
            raise ValueError("Audit and expanded supplement outputs must differ")
        supplement = json.loads(args.supplement.read_text(encoding="utf-8-sig"))
        report, expanded = audit(args.archive, supplement, args.history_root)
        root = args.history_root.resolve()
        inputs = [args.archive, args.supplement]
        write_output_json(args.output, report, root, inputs)
        if args.expanded_output:
            write_output_json(args.expanded_output, expanded, root, inputs)
        print(json.dumps(report["summary"], ensure_ascii=True, sort_keys=True))
        return 0 if not report["missing"] else 1
    except (OSError, ValueError, TypeError, KeyError, BadZipFile) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
