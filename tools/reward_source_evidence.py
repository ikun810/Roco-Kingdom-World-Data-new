#!/usr/bin/env python3
"""Reproduce reward source evidence without editing any source snapshot."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
import zipfile
from content_supplement import write_output_json

SOURCE_BLOBS = {
    "pakchunk4-WindowsNoEditor/Bin/BinDataCompressed/REWARD_CONF.json": "6df56391210dc9b5fed66a5f7a5bedab8903cb39",
    "pakchunk4-WindowsNoEditor_0_P/Bin/BinDataCompressed/REWARD_CONF.json": "bdd5c823288814f4928797fa341ced33f4968ddc",
    "pakchunk4-WindowsNoEditor_1_P/Bin/BinDataCompressed/REWARD_CONF.json": "730c946a49630ed5ea76dac24421cf7984e4b92d",
    "pakchunk4-WindowsNoEditor_2_P/Bin/BinDataCompressed/REWARD_CONF.json": "8eee89f7137feea20f57a6e7afa30e6592249944",
    "pakchunk4-WindowsNoEditor_2_P/PB/proto_out/xls_enum.proto": "aeb2b10623468bf8e689b061e00caa79cd4b2902",
    "pakchunk4-WindowsNoEditor_2_P/PB/proto_out/com_goods.proto": "c5bf700506a95dc10a5c88943ba2bb1b38816ee0",
    "pakchunk4-WindowsNoEditor_1_P/Bin/BinConf/REWARD_CONF.json": "52e5f9303b2b87bf2fd0940a7dfe20707594e122",
    "pakchunk4-WindowsNoEditor_2_P/Bin/BinDataCompressed/BAG_ITEM_CONF.json": "76c7153c0a946eb03293756b517fc1b6bfe5a31e",
    "pakchunk4-WindowsNoEditor_2_P/Bin/BinDataCompressed/VISUAL_ITEM_CONF.json": "055fe2d79f162a994284cfde76ea9ead2ec0be45",
    "pakchunk4-WindowsNoEditor_2_P/Bin/BinDataCompressed/PET_CONF.json": "0fdf9d0a310f250e65f34a9e40754b4d61802888",
    "pakchunk4-WindowsNoEditor_2_P/Bin/BinDataCompressed/CARD_SKIN_CONF.json": "901215559ada565ed95c2b79529fc7a8d1723e2a",
    "pakchunk4-WindowsNoEditor_2_P/Bin/BinDataCompressed/CARD_LABEL_CONF.json": "41f532dedbc3704b4d757270c9ae34b1ad436a52",
    "pakchunk4-WindowsNoEditor_2_P/Bin/BinDataCompressed/ROLEPLAY_BEHAVIOR_CONF.json": "d6f92627de6af90a65e4f7286666203288392885",
}


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def checked_source_bytes(root, path, expected_blob):
    source = pathlib.Path(root) / path
    if source.is_symlink() or not source.resolve().is_relative_to(pathlib.Path(root).resolve()):
        raise ValueError("Source path escapes repository")
    raw = source.read_bytes()
    if blob_sha(raw) != expected_blob:
        raise ValueError("Historical Git blob mismatch: " + path)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    root = args.repo
    supplement_path = "data/supplements/referenced_content.json"
    supplement = json.loads((root / supplement_path).read_bytes())
    entries = [row for row in supplement["entries"] if row["table"] == "REWARD_CONF"]
    sources = {}
    row_cache = {}
    raw_cache = {}

    def source(path: str) -> dict:
        if path not in sources:
            if path not in SOURCE_BLOBS:
                raise ValueError("Historical source is not registered: " + path)
            raw = checked_source_bytes(root, path, SOURCE_BLOBS[path])
            raw_cache[path] = raw
            sources[path] = {
                "path": path,
                "git_blob_sha": blob_sha(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        return sources[path]

    def rows(path: str) -> dict:
        if path not in row_cache:
            source(path)
            row_cache[path] = json.loads(raw_cache[path])["RocoDataRows"]
        return row_cache[path]

    historical_search = []
    for path in sorted(root.glob("pak*/Bin/BinDataCompressed/REWARD_CONF.json")):
        relpath = path.relative_to(root).as_posix()
        data = rows(relpath)
        historical_search.append({
            "source_path": relpath,
            "row_count": len(data),
            "id_19589_present": "19589" in data,
        })
    archive_path = root / "data/current.zip"
    archive_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if archive_sha256 != supplement["target_archive_sha256"]:
        raise ValueError("Current archive no longer matches the supplement target")
    with zipfile.ZipFile(archive_path) as archive:
        reward_member = "BinDataCompressed/REWARD_CONF.json"
        task_member = "BinDataCompressed/TASK_CONF.json"
        reward_data = archive.read(reward_member)
        task_data = archive.read(task_member)
        current = json.loads(reward_data)["RocoDataRows"]
        tasks = json.loads(task_data)["RocoDataRows"]
        current_sources = {
            "archive_path": "data/current.zip",
            "archive_sha256": archive_sha256,
            "members": [
                {"path": reward_member, "sha256": hashlib.sha256(reward_data).hexdigest()},
                {"path": task_member, "sha256": hashlib.sha256(task_data).hexdigest()},
            ],
        }
    references = [
        {"table": "TASK_CONF", "id": key, "field": "Reward", "raw_record": row}
        for key, row in tasks.items() if row.get("Reward") == 19589
    ]
    base0 = rows("pakchunk4-WindowsNoEditor_0_P/Bin/BinDataCompressed/REWARD_CONF.json")
    current_distribution = collections.Counter(
        json.dumps(row.get("RewardItem"), ensure_ascii=False, sort_keys=True)
        for row in current.values()
    )
    same_layer = "pakchunk4-WindowsNoEditor_2_P"
    enum_path = f"{same_layer}/PB/proto_out/xls_enum.proto"
    goods_path = f"{same_layer}/PB/proto_out/com_goods.proto"
    schema_path = "pakchunk4-WindowsNoEditor_1_P/Bin/BinConf/REWARD_CONF.json"
    source(enum_path)
    source(goods_path)
    source(schema_path)
    enum_text = raw_cache[enum_path].decode('utf-8')
    enum_names = ["GoodsType", "RewardType", "RewardTag", "OpType"]
    enums = {}
    for name in enum_names:
        match = re.search(r"enum " + name + r"\s*\{([^}]*)\}", enum_text)
        if not match:
            raise ValueError(f"Missing enum {name}")
        enums[name] = {
            "source_path": enum_path,
            "members": {label: int(number) for label, number in re.findall(
                r"(\w+)\s*=\s*(\d+)\s*;", match.group(1))},
        }
    mapping = {
        1: ("BAG_ITEM_CONF", "name"),
        2: ("VISUAL_ITEM_CONF", "displayName"),
        4: ("PET_CONF", "name"),
        14: ("CARD_SKIN_CONF", "skin_resource_name"),
        15: ("CARD_LABEL_CONF", "label_text"),
        20: ("ROLEPLAY_BEHAVIOR_CONF", "name_text"),
    }
    tables = {
        kind: rows(f"{same_layer}/Bin/BinDataCompressed/{table}.json")
        for kind, (table, _) in mapping.items()
    }
    reverse_enums = {number: label for label, number in enums["GoodsType"]["members"].items()}
    identities = {}
    rewards = []
    all_items = []
    for entry in entries:
        source(entry["source_path"])
        reward = entry["record"]
        historical_table = rows(entry["source_path"])
        if historical_table.get(entry["id"]) != reward:
            raise ValueError(f"Supplement differs from historical source: {entry['id']}")
        if sources[entry["source_path"]]["git_blob_sha"] != entry["source_blob_sha"]:
            raise ValueError(f"Historical blob fingerprint changed: {entry['source_path']}")
        components = []
        for index, component in enumerate(reward.get("RewardItem", [])):
            kind, item_id = component["Type"], component["Id"]
            table, name_field = mapping[kind]
            identity_key = f"{kind}:{item_id}"
            record = tables[kind].get(str(item_id))
            if record is None:
                raise ValueError(f"Missing same-source identity {identity_key}")
            identities[identity_key] = {
                "goods_type": kind,
                "goods_enum_label": reverse_enums[kind],
                "id": item_id,
                "table": table,
                "source_path": f"{same_layer}/Bin/BinDataCompressed/{table}.json",
                "display_name_field": name_field,
                "display_name": record.get(name_field),
                "raw_record": record,
                "binding_status": "same_snapshot_numeric_identity_and_protocol_supported",
                "runtime_handler_verified": False,
            }
            components.append({"index": index, "identity_ref": identity_key, "raw_component": component})
            all_items.append(component)
        rewards.append({
            "id": entry["id"],
            "supplement_operation": entry["operation"],
            "source_path": entry["source_path"],
            "reward_type_raw": reward.get("Type"),
            "reward_type_label": "RT_GIFT" if reward.get("Type") == 1 else None,
            "name_raw": reward.get("Name"),
            "description_raw": reward.get("Description"),
            "components": components,
            "settlement_authorized": False,
        })
    result = {
        "format": "roco-reward-source-evidence-v1",
        "basis_repository_commit": "b5e36a2bb22400599dbeeccf44c75b4e318a4518",
        "scope": "114 REWARD_CONF historical candidates in the existing referenced-content supplement",
        "source_limitations": [
            "These are historical source identities, not verification of current-client reward settlement.",
            "The schema declares integer Type/Id/Count, not the config Type-to-enum binding; GoodsItem protocol explicitly uses GoodsType and source records corroborate the namespace.",
            "Count is preserved as an unsigned stored value; DropWeight arrays and game runtime algorithms are not interpreted.",
            "Do not infer a replacement reward from neighboring IDs or localization indexes.",
            "Display Name/Description strings may disagree with structured counts; never rewrite Count from those strings.",
            "REWARD_CONF schema is retained in historical _1_P; _2_P does not contain a replacement schema. Runtime mount/inheritance order is not asserted.",
            "Upstream tree checks describe the observed investigation, not fresh network requests by this reproduction script.",
        ],
        "summary": {
            "historical_reward_records": len(rewards),
            "raw_components": len(all_items),
            "distinct_numeric_identities": len(identities),
            "missing_same_source_identities": 0,
            "component_types": dict(sorted(collections.Counter(i["Type"] for i in all_items).items())),
            "all_top_level_type_is_1": all(e["record"].get("Type") == 1 for e in entries),
            "all_counts_present": all("Count" in item for item in all_items),
        },
        "current_snapshot": current_sources,
        "current_reward_anomaly": {
            "record_count": len(current),
            "ids_equal_historical_0_P": current.keys() == base0.keys(),
            "identical_complete_rows_with_historical_0_P": sum(current[k] == base0[k] for k in current.keys() & base0.keys()),
            "rows_without_RewardItem": sum("RewardItem" not in row for row in current.values()),
            "repeated_22_1000000_rows": current_distribution['[{"Count": 1000000, "Type": 22}]'],
            "interpretation": "Evidence of a broad export anomaly, not proof that historical records equal current runtime values.",
        },
        "unresolved_reward_19589": {
            "status": "no_verified_definition",
            "current_present": "19589" in current,
            "historical_search": historical_search,
            "current_task_references": references,
            "upstream_tree_checks": [
                {"repository": "candyflosssss/Roco-Kingdom-World-Data", "commit": "93e9130bc7b53d370003571fa266d1487a2a43bf", "result": "all four REWARD_CONF blobs identical to this repository"},
                {"repository": "giraffe995/Roco-Kingdom-World-Data", "commit": "d118fca39420d0dd4dac95444d6aab4313475565", "reward_blob_sha": "fcf7e3849c5ae34d76bb82c6e69095c30ff9f21c", "row_count": 7179, "result": "record-for-record equal to the repository base layer; no 19589"},
                {"repository": "ikun810/Roco-Kingdom-World-Data", "commit": "d118fca39420d0dd4dac95444d6aab4313475565", "reward_blob_sha": "fcf7e3849c5ae34d76bb82c6e69095c30ff9f21c", "result": "same tree and reward blob as giraffe995"},
            ],
            "required_next_source": "A coherent current-client REWARD_CONF data/schema export containing the exact row 19589; do not substitute localization entry 19589.",
        },
        "enums": enums,
        "identity_bindings": list(identities.values()),
        "rewards": rewards,
        "known_description_conflicts": [
            {"reward_id": "19501", "description_fragment": "8恶系灵碎", "raw_component": {"Type": 1, "Id": 100305, "Count": 4}},
            {"reward_id": "19502", "description_fragment": "12恶系灵碎", "raw_component": {"Type": 1, "Id": 100305, "Count": 8}},
        ],
        "sources": list(sources.values()),
    }
    write_output_json(args.output, result, root, [archive_path, root / supplement_path])
    print(json.dumps({"output": str(args.output), "summary": result["summary"], "unresolved_reward_19589": len(references)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
