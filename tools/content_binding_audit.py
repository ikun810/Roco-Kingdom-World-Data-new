#!/usr/bin/env python3
"""Read-only audit of a scoped content supplement's conflict candidates."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
from content_supplement import write_output_json


def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def leaves(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, path + "/" + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, path + "/" + str(index))
    else:
        yield path, value


def without_text(value):
    if isinstance(value, dict):
        return {key: without_text(item) for key, item in value.items()
                if not isinstance(item, str)}
    if isinstance(value, list):
        return [without_text(item) for item in value]
    return value


def audit(root, supplement_path=None):
    supplement_path = supplement_path or root / "data/supplements/referenced_content.json"
    supplement = json.loads(supplement_path.read_text(encoding="utf-8"))
    archive_raw = (root / "data/current.zip").read_bytes()
    if hashlib.sha256(archive_raw).hexdigest() != supplement["target_archive_sha256"]:
        raise ValueError("Current archive SHA-256 does not match registered target")
    candidates = [row for row in supplement["entries"] if row["operation"] == "review_conflict"]
    table_names = sorted({row["table"] for row in candidates})
    report = {
        "format": "roco_binding_audit_v1",
        "source_archive_sha256": supplement["target_archive_sha256"],
        "claim_limit": "Historical bindings and current string-pool membership do not prove current binary index bindings or current runtime reward values.",
        "binary_inputs_present": False,
        "tables": {},
        "candidates": [],
    }
    with ZipFile(root / "data/current.zip") as archive:
        report["binary_inputs_present"] = any(name.endswith((".bytes", ".non")) for name in archive.namelist())
        for table in table_names:
            current_raw = archive.read(f"BinDataCompressed/{table}.json")
            current = json.loads(current_raw)["RocoDataRows"]
            locale_path = f"BinLocalize/zh_Hans/{table}.json"
            locale_raw = archive.read(locale_path)
            locale = json.loads(locale_raw)["LocalizationStrings"]
            history = {}
            for source in sorted(root.glob(f"pak*/Bin/BinDataCompressed/{table}.json")):
                raw = source.read_bytes()
                history[source.relative_to(root).as_posix()] = {
                    "rows": json.loads(raw)["RocoDataRows"], "blob_sha": blob_sha(raw)}
            table_report = {
                "current_rows": len(current),
                "current_raw_sha256": hashlib.sha256(current_raw).hexdigest(),
                "locale_path": locale_path,
                "locale_raw_sha256": hashlib.sha256(locale_raw).hexdigest(),
                "history_comparisons": [],
            }
            for name, source in history.items():
                rows = source["rows"]
                common = current.keys() & rows.keys()
                table_report["history_comparisons"].append({
                    "path": name, "blob_sha": source["blob_sha"], "row_count": len(rows),
                    "common_id_count": len(common), "identical_id_set": current.keys() == rows.keys(),
                    "identical_row_count": sum(current[key] == rows[key] for key in common),
                })
            if table == "REWARD_CONF":
                payloads = Counter(json.dumps(row.get("RewardItem"), sort_keys=True) for row in current.values())
                table_report["reward_payload_counts"] = [
                    {"payload": json.loads(payload), "count": count}
                    for payload, count in payloads.most_common()
                ]
            report["tables"][table] = table_report
            for candidate in [row for row in candidates if row["table"] == table]:
                key = candidate["id"]
                historical = candidate["record"]
                source = history[candidate["source_path"]]
                if source["blob_sha"] != candidate["source_blob_sha"] or source["rows"].get(key) != historical:
                    raise ValueError(f"Historical source mismatch: {table}/{key}")
                stable_sources = []
                for name, source in history.items():
                    row = source["rows"].get(key)
                    if row is None:
                        continue
                    stable_sources.append({
                        "path": name, "blob_sha": source["blob_sha"],
                        "candidate_fields_equal": all(row.get(field) == historical.get(field) for field in candidate["fields"]),
                    })
                result = {
                    "table": table, "id": key, "candidate_source_path": candidate["source_path"],
                    "candidate_source_blob_sha": candidate["source_blob_sha"],
                    "historical_field_agreement": stable_sources,
                    "historical_is_not_verified_as_current": True,
                }
                if table == "REWARD_CONF":
                    result.update({"current_payload": current[key].get("RewardItem"),
                                   "historical_payload": historical.get("RewardItem"),
                                   "decision": "current_runtime_value_requires_binary_or_runtime_evidence"})
                else:
                    current_fields = dict(leaves(current[key]))
                    historical_fields = dict(leaves(historical))
                    proposals = []
                    for field, value in historical_fields.items():
                        if table == "SELECT_CONF" and field != "/text":
                            continue
                        if isinstance(value, str) and current_fields.get(field) != value:
                            proposals.append({
                                "pointer": field,
                                "current": current_fields.get(field),
                                "historical_candidate": value,
                                "current_locale_indices_with_exact_text": [index for index, text in locale.items() if text == value],
                            })
                    result["text_leaf_proposals"] = proposals
                    all_text_present = all(field["current_locale_indices_with_exact_text"] for field in proposals)
                    result["all_proposed_text_present_in_current_locale"] = all_text_present
                    result["decision"] = ("historical_binding_supported_by_current_text_pool; not_current_index_verified"
                                          if all_text_present else
                                          "historical_binding_only; current_text_pool_does_not_cover_all_candidates")
                    if table == "TASK_CONF":
                        result["task_condition_numeric_structure_equal"] = without_text(current[key].get("task_condition")) == without_text(historical.get("task_condition"))
                        result["go_guide_numeric_structure_equal"] = without_text(current[key].get("go_guide")) == without_text(historical.get("go_guide"))
                    if table == "SELECT_CONF":
                        result["all_non_text_fields_equal"] = {k: v for k, v in current[key].items() if k != "text"} == {k: v for k, v in historical.items() if k != "text"}
                        result["selected_graph_fields_equal"] = {field: current[key].get(field) for field in ("enable_cond", "enable_cond_params", "select_next_dialogue", "notimes_dialogue")} == {field: historical.get(field) for field in ("enable_cond", "enable_cond_params", "select_next_dialogue", "notimes_dialogue")}
                report["candidates"].append(result)
    report["summary"] = {
        "candidate_count": len(report["candidates"]),
        "candidates_stable_across_all_observed_historical_layers": sum(
            all(item["candidate_fields_equal"] for item in row["historical_field_agreement"])
            for row in report["candidates"]),
        "text_leaf_proposal_count": sum(len(row.get("text_leaf_proposals", [])) for row in report["candidates"]),
        "text_leaf_proposals_present_in_current_locale": sum(
            bool(field["current_locale_indices_with_exact_text"])
            for row in report["candidates"] for field in row.get("text_leaf_proposals", [])),
    }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--supplement", type=Path, help="Optional scoped supplement; defaults to the repository supplement")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.repo, args.supplement)
    write_output_json(args.output, result, args.repo,
                      [args.repo / 'data/current.zip', args.supplement or args.repo / 'data/supplements/referenced_content.json'])
    print(json.dumps(result["summary"], ensure_ascii=False))
