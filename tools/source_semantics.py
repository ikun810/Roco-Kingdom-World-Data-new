#!/usr/bin/env python3
"""Export pinned source evidence; does not implement or certify game semantics."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import BadZipFile, ZipFile
from content_supplement import write_output_json

REPOSITORY = "ikun810/Roco-Kingdom-World-Data-new"
SOURCE_COMMIT = "b5e36a2bb22400599dbeeccf44c75b4e318a4518"
OPTIONAL_PATH = "pakchunk4-WindowsNoEditor_2_P/Bin/BinDataCompressed/SEASON_BONUSCATCH_STORY_CONF.json"
XLS_PATH = "pakchunk4-WindowsNoEditor_3_P/PB/proto_out/xls_enum.proto"
TASK_PROTO_PATH = "pakchunk4-WindowsNoEditor_3_P/PB/proto_out/com_task.proto"
SOURCE_BLOBS = {
    OPTIONAL_PATH: "08841f72cd940c043fd5a81a0a84ef7e07f96bfa",
    XLS_PATH: "15238458364b18d6e8cf7f3a56015a2e03390b11",
    TASK_PROTO_PATH: "e431a47ee1662c4f71ee9ae5e8fc8851dfe6ca7f",
}
RUNTIME_SOURCE = {
    "repository": "ikun810/rock-world-lite",
    "commit": "6b9a7455a899c793f4a5b6db69234fdff113c5bf",
    "path": "data/runtime-map.json",
    "git_blob_sha": "9fd8572671fccc6d6ab5d4671791f8ad4d460a81",
}
ENUM_NAMES = {
    XLS_PATH: [
        "TaskKeyType", "TaskAcceptConditionType", "TaskSwitchCondition",
        "TaskStateChangeActionType", "ConditionType", "DlgSelectEnableCond",
        "DlgSelectDisableCond", "OptionEnableCond", "NpcCombType", "OptionCondType",
        "CombinationResultType", "StoryFlagAction", "TaskClientTriggerType",
        "NextTaskType", "TaskStructureType", "TaskGuideType", "TaskGoActionType",
        "TaskTeleportType", "TaskGoRetentionType", "NpcOptTimesDecCond",
        "SelectTimesDecCond", "RefreshType", "PatrolBelongType", "TeleportDestType",
        "TeleportBeginPointType", "AreaType", "NpcInteractOption", "ActionType",
    ],
    TASK_PROTO_PATH: ["EMTaskState", "WorldLevelTaskState"],
}
FIELD_ENUM_CANDIDATES = [
    ("accept_condition", "TaskAcceptConditionType"),
    ("task_condition", "TaskKeyType"),
    ("accept_action", "TaskStateChangeActionType"),
    ("finish_action", "TaskStateChangeActionType"),
    ("reward_action", "TaskStateChangeActionType"),
    ("failed_action", "TaskStateChangeActionType"),
]


def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def checked_source(repo, path, expected_blob):
    source = Path(repo) / path
    if not source.resolve().is_relative_to(Path(repo).resolve()) or source.is_symlink():
        raise ValueError("Source path escapes repository")
    raw = source.read_bytes()
    if blob_sha(raw) != expected_blob:
        raise ValueError("Historical Git blob mismatch: " + path)
    return raw, {"repository": REPOSITORY, "commit": SOURCE_COMMIT,
                 "path": path, "git_blob_sha": expected_blob,
                 "sha256": hashlib.sha256(raw).hexdigest()}


def validate_target(repo):
    repo = Path(repo)
    supplement = json.loads((repo / "data/supplements/referenced_content.json").read_text(encoding="utf-8"))
    if supplement.get("format") != "roco_referenced_content_supplement_v1":
        raise ValueError("Unknown supplement version")
    archive_sha = hashlib.sha256((repo / "data/current.zip").read_bytes()).hexdigest()
    if archive_sha != supplement.get("target_archive_sha256"):
        raise ValueError("Current archive SHA-256 does not match registered target")
    return supplement, archive_sha


def parse_proto_enums(text, names):
    # Retain newline counts when discarding comments, for reproducible source lines.
    text = re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: "\n" * m.group().count("\n"), text, flags=re.S)
    result = []
    for name in names:
        match = re.search(r"^\s*enum\s+" + re.escape(name) + r"\s*\{([^}]*)\}", text, re.M)
        if match is None:
            raise ValueError("Missing enum: " + name)
        symbols = [{"symbol": symbol, "value": int(value)} for symbol, value in re.findall(
            r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(-?\d+)\s*;", match.group(1), re.M)]
        if not symbols:
            raise ValueError("Empty enum: " + name)
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        result.append({"enum": name, "source_line": text[:start].count("\n") + 1, "members": symbols})
    return result


def numeric_coverage(rows, field, enum_name, symbols):
    counts, omitted, invalid, unknown = Counter(), [], [], []
    for key in sorted(rows, key=int):
        row = rows[key]
        for index, value in enumerate(row.get(field, [])):
            source = {"task_id": row["id"], "index": index,
                      "pointer": "/RocoDataRows/" + key + "/" + field + "/" + str(index),
                      "condition": value}
            if not isinstance(value, dict) or "type" not in value:
                omitted.append(source)
                continue
            kind = value["type"]
            if type(kind) is not int:
                invalid.append(source)
                continue
            counts[kind] += 1
            if kind not in symbols:
                unknown.append(source)
    return {"field": "TASK_CONF." + field + "[].type", "candidate_enum": enum_name,
            "candidate_binding_status": "inference_not_declared_by_BinConf_schema",
            "observed_slots": sum(counts.values()) + len(omitted) + len(invalid),
            "omitted_type_slots": len(omitted), "invalid_type_slots": len(invalid),
            "observed_values": [{"value": value, "symbol_in_historical_enum": symbols.get(value),
                                 "count": count} for value, count in sorted(counts.items())],
            "unknown_values": sorted(value for value in counts if value not in symbols),
            "unknown_source_rows": unknown, "omitted_source_rows": omitted,
            "invalid_source_rows": invalid}


def scene_entry_links(resources, contents, areas):
    entries = []
    for key in sorted(resources, key=int):
        resource = resources[key]
        content_id = resource.get("world_map_entry_npc_content_id")
        if not content_id:
            continue
        content = contents.get(str(content_id))
        area = areas.get(str(content.get("refresh_param"))) if content and content.get("refresh_type") == 1 else None
        entries.append({"scene_res_id": resource["id"], "scene_id": resource.get("scene_id"),
                        "scene_export_id": resource.get("scene_export_id"),
                        "world_map_entry_npc_content_id": content_id,
                        "content_record": {k: content[k] for k in ["id", "refresh_type", "refresh_param", "npc_id"] if k in content} if content else None,
                        "refresh_param_area_record": area,
                        "association_status": "explicit_content_id_reference_and_matching_area_id" if area else "incomplete"})
    return entries


def optional_supplement(original, current, historical, provenance):
    if current.keys() != historical.keys() or any(current[k].get("text") != historical[k].get("text") for k in current):
        raise ValueError("Optional story IDs or text do not match the historical source")
    fields = ["initial_bubble_dialogue_npc_id", "initial_bubble_dialogue_id", "initial_backdrop_id", "option"]
    entries = []
    for key in sorted(current, key=int):
        added = [field for field in fields if field not in current[key] and field in historical[key]]
        if added:
            entries.append({"table": "SEASON_BONUSCATCH_STORY_CONF", "id": key,
                            "operation": "backfill_missing_fields", "fields": added,
                            "source_path": OPTIONAL_PATH, "source_blob_sha": provenance["git_blob_sha"],
                            "record": historical[key]})
    output = {key: original[key] for key in ["format", "target_repository_commit", "target_archive_sha256", "historical_source_repository", "record_policy"]}
    output.update({"historical_source_commit": SOURCE_COMMIT,
                   "status": "historical_evidence_only_not_verified_as_current_client",
                   "scope": "optional_season_bonuscatch_story_only",
                   "notes": ["Explicitly optional story content; separate from mandatory progression.",
                             "Historical and target IDs and text fields match exactly.",
                             "Only absent keys are backfilled. Existing values are never overwritten.",
                             "The source has no successor field. No successor or completion semantics are fabricated.",
                             "Bubble dialogue and NPC group resources are not verified by this supplement. Recovery does not establish a playable event chain.",
                             "Historical evidence is not attestation against the currently installed client."],
                   "summary": {"entry_count": len(entries), "backfill_missing_fields": len(entries),
                               "review_conflict": 0, "add_if_absent": 0, "missing_from_checked_history": 0},
                   "entries": entries, "unresolved": []})
    return output


def generate(repo, runtime_map=None):
    repo = Path(repo)
    original, archive_sha = validate_target(repo)
    raw_sources = {path: checked_source(repo, path, blob) for path, blob in SOURCE_BLOBS.items()}
    enums = []
    for path, names in ENUM_NAMES.items():
        raw, source = raw_sources[path]
        for parsed in parse_proto_enums(raw.decode("utf-8"), names):
            enums.append({"enum": parsed["enum"], "source": source,
                          "source_line": parsed["source_line"], "members": parsed["members"]})
    symbols = {entry["enum"]: {m["value"]: m["symbol"] for m in entry["members"]} for entry in enums}
    outputs = {"condition_action_source_enums.json": {
        "format": "roco_source_enum_evidence_v1", "historical_is_not_verified_as_current": True,
        "scope": "Source symbol-to-integer definitions only; field mapping inferences are a separate output.",
        "binding_limit": "BinConf numeric fields do not declare protobuf enums. This dictionary does not assert field bindings, operands, defaults, omitted-zero rules or evaluation code.",
        "evaluation_limit": "ALL/ONE_OF/ANY/SEQ symbols do not establish an AND/OR default for arbitrary arrays or empty-array behavior.",
        "enum_count": len(enums), "member_count": sum(len(e["members"]) for e in enums), "enums": enums}}
    with ZipFile(repo / "data/current.zip") as archive:
        tables = ["SCENE_CONF", "SCENE_RES_CONF", "AREA_CONF", "NPC_REFRESH_CONTENT_CONF", "TELEPORT_CONF", "TASK_CONF", "SEASON_BONUSCATCH_STORY_CONF"]
        raws = {table: archive.read("BinDataCompressed/" + table + ".json") for table in tables}
        rows = {table: json.loads(raw)["RocoDataRows"] for table, raw in raws.items()}
        sources = {table: {"archive": "data/current.zip", "archive_sha256": archive_sha,
                           "member": "BinDataCompressed/" + table + ".json",
                           "member_sha256": hashlib.sha256(raw).hexdigest()} for table, raw in raws.items()}
        historical = json.loads(raw_sources[OPTIONAL_PATH][0])["RocoDataRows"]
        outputs["optional_story_content.json"] = optional_supplement(original, rows["SEASON_BONUSCATCH_STORY_CONF"], historical, raw_sources[OPTIONAL_PATH][1])
        schema_raw = archive.read("BinConf/TASK_CONF.json")
        schema = json.loads(schema_raw)
        checks = []
        for field, candidate in FIELD_ENUM_CANDIDATES:
            check = numeric_coverage(rows["TASK_CONF"], field, candidate, symbols[candidate])
            index, prop = next((i, p) for i, p in enumerate(schema["Properties"]) if p["Name"] == field)
            sub_index, type_prop = next((i, p) for i, p in enumerate(prop["Struct"]["Properties"]) if p["Name"] == "type")
            check["schema_evidence"] = {"pointer": "/Properties/" + str(index) + "/Struct/Properties/" + str(sub_index), "property": type_prop}
            check["inference_basis"] = "Field role/name and observed numeric overlap with the named historical enum; not an explicit schema binding or a runtime implementation."
            checks.append(check)
        outputs["condition_action_numeric_coverage.json"] = {
            "format": "roco_enum_numeric_coverage_investigation_v1", "archive_sha256": archive_sha,
            "source": sources["TASK_CONF"], "schema_source": {"member": "BinConf/TASK_CONF.json", "member_sha256": hashlib.sha256(schema_raw).hexdigest()},
            "limits": ["Candidate field-to-enum mappings are inferences, separate from verified symbol definitions.",
                       "Coverage does not prove operand ordering or executable semantics.",
                       "Omitted type keys are kept separate from explicit zero and null. No default is assigned."], "checks": checks}
        identity_sources = {table: sources[table] for table in tables[:5]}
        entries = scene_entry_links(rows["SCENE_RES_CONF"], rows["NPC_REFRESH_CONTENT_CONF"], rows["AREA_CONF"])
        outputs["scene_entry_identity_evidence.json"] = {
            "format": "roco_scene_entry_identity_evidence_v1", "target_archive_sha256": archive_sha,
            "sources": identity_sources, "entry_count": len(entries), "entries": entries,
            "limits": ["Scene resource identity and exported scene identity are distinct from scene_id.",
                       "Resources 10003 and 10018 both have scene_id 103; do not merge them by scene_id.",
                       "refresh_type=1 matches historical symbol RFT_AREA; matching refresh_param IDs are preserved with full AREA_CONF records. This is not a runtime field-binding attestation.",
                       "No downstream location ID or display-name matching is applied."]}
        if runtime_map is not None:
            raw = Path(runtime_map).read_bytes()
            if blob_sha(raw) != RUNTIME_SOURCE["git_blob_sha"]:
                raise ValueError("Runtime map Git blob mismatch")
            runtime = json.loads(raw)
            anchors = []
            for marker in runtime["sources"]:
                xy = [marker["position"]["x"], marker["position"]["y"]]
                hits = [a for a in rows["AREA_CONF"].values() if a.get("area_type") == 2 and a.get("center_xyz", [])[:2] == xy]
                ids = [c["id"] for c in rows["NPC_REFRESH_CONTENT_CONF"].values() if c.get("refresh_type") == 1 and c.get("refresh_param") == hits[0]["id"]] if len(hits) == 1 else []
                anchors.append({"runtime_marker": marker, "area_matches": hits, "npc_content_ids": ids,
                                "method": "exact_integer_xy_on_unique_point_area_no_name_matching"})
            outputs["m1_coordinate_anchor_investigation.json"] = {
                "format": "roco_m1_coordinate_anchor_investigation_v1", "runtime_source": RUNTIME_SOURCE,
                "target_archive_sha256": archive_sha, "sources": identity_sources, "anchors": anchors,
                "limits": ["Coordinate matches support these markers only, not all region, interior, task or actor identities.",
                           "No display name was used to select a row. No downstream movement or teleport permission is changed."]}
    return outputs


def write_outputs(outputs, output, repo, inputs=()):
    input_paths = {Path(path).resolve() for path in inputs}
    for name in outputs:
        if (Path(output) / name).resolve() in input_paths:
            raise ValueError("Output must not overwrite source input")
    for name, data in outputs.items():
        write_output_json(Path(output) / name, data, repo, inputs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("build/source-evidence"))
    parser.add_argument("--runtime-map", type=Path, help="Optional exact pinned runtime-map.json; never downloaded")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        output = args.output_dir if args.output_dir.is_absolute() else repo / args.output_dir
        output = output.resolve()
        for protected in [repo / "data", *repo.glob("pakchunk*")]:
            if output.is_relative_to(protected.resolve()):
                raise ValueError("Output directory must be outside source data directories")
        outputs = generate(repo, args.runtime_map)
        inputs = [repo / 'data/current.zip', repo / 'data/supplements/referenced_content.json']
        if args.runtime_map:
            inputs.append(args.runtime_map)
        write_outputs(outputs, output, repo, inputs)
        dictionary = outputs["condition_action_source_enums.json"]
        print(json.dumps({"files": list(outputs), "optional_entries": outputs["optional_story_content.json"]["summary"]["entry_count"],
                          "enum_count": dictionary["enum_count"], "member_count": dictionary["member_count"],
                          "scene_entry_count": outputs["scene_entry_identity_evidence.json"]["entry_count"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, StopIteration, BadZipFile) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
