#!/usr/bin/env python3
"""Compare FModel merged-export schema fingerprints to historical Pak schemas.

This is an evidence-only inspection tool. It never interprets an old schema as a
correct replacement for a newer binary layout and never exports game row values.
Historical Pak mount order is not assumed or verified.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

FORMAT = 'roco_schema_lineage_v1'
MANIFEST_FORMAT = 'roco_merged_snapshot_v1'
LAYER_RE = re.compile(r'pakchunk\d+-WindowsNoEditor(?:_\d+_P)?\Z')
STEM_RE = re.compile(r'[A-Za-z0-9_-]+\Z')
HASH_RE = re.compile(r'[a-f0-9]{64}\Z')


def semantic_hash(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def table_id_from_issue_path(path: str) -> str:
    parts = path.split('/')
    if (len(parts) == 2 and parts[0] in ('BinDataCompressed', 'BinData')
            and parts[-1].endswith('.json')):
        name = parts[-1][:-5]
        if STEM_RE.fullmatch(name):
            return parts[0] + '/' + name
    if (len(parts) == 3 and parts[:2] == ['BinDataCompressed', 'BinDataCompressed_ROW']
            and parts[-1].endswith('.json')):
        name = parts[-1][:-5]
        if STEM_RE.fullmatch(name):
            return 'BinDataCompressed_ROW/' + name
    raise ValueError(f'Invalid or unsupported warning path: {path!r}')


def load_historical_schemas(history_root: Path) -> tuple[dict[str, list[dict]], int]:
    """Read pre-existing historical schema documents; no client assets are copied."""
    history_root = history_root.resolve(strict=True)
    if not history_root.is_dir():
        raise ValueError('Historical root is not a directory')
    by_name: dict[str, list[dict]] = {}
    checked = 0
    layers = sorted((p for p in history_root.iterdir()
                     if p.is_dir() and LAYER_RE.fullmatch(p.name)), key=lambda p: p.name)
    if not layers:
        raise ValueError('No historical Pak layer directories found')
    for layer in layers:
        if layer.is_symlink():
            raise ValueError(f'Pak directory symlink not allowed: {layer}')
        directory = layer / 'Bin' / 'BinConf'
        if directory.is_symlink():
            raise ValueError(f'Schema directory symlink not allowed: {directory}')
        if not directory.is_dir():
            continue
        for p in sorted(directory.glob('*.json')):
            if p.is_symlink():
                raise ValueError(f'Schema source symlink not allowed: {p}')
            if not STEM_RE.fullmatch(p.stem):
                raise ValueError(f'Unsafe historical schema filename: {p.name}')
            try:
                with p.open(encoding='utf-8-sig') as f:
                    obj = json.load(f)
                if not isinstance(obj, dict) or not isinstance(obj.get('Properties'), list):
                    raise ValueError('Invalid schema object or Properties')
                names = [x['Name'] for x in obj['Properties']
                         if isinstance(x, dict) and isinstance(x.get('Name'), str)]
                if len(names) != len(set(names)):
                    raise ValueError('Duplicate declared field names')
                declared = sorted(set(names))
                digest = semantic_hash(obj)
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f'Historical schema parse failed: {p.relative_to(history_root)}: {exc}') from exc
            by_name.setdefault(p.stem, []).append({
                'layer': layer.name,
                'path': p.relative_to(history_root).as_posix(),
                'sha256_semantic': digest,
                'declared_fields': declared,
            })
            checked += 1
    if not checked:
        raise ValueError('No historical schema JSON files')
    return by_name, checked


def analyze(manifest: dict, history_root: Path) -> dict:
    if manifest.get('format') != MANIFEST_FORMAT:
        raise ValueError('Expected merged snapshot v1 manifest')
    if not isinstance(manifest.get('tables'), list) or not isinstance(manifest.get('issues'), list):
        raise ValueError('Malformed merged snapshot: missing tables or issues')
    by_name, scanned = load_historical_schemas(history_root)
    source_entries = manifest['tables'] + manifest.get('international_row_variants', [])
    by_id = {item['table']: item for item in source_entries}
    if len(by_id) != len(source_entries):
        raise ValueError('Duplicate logical table in merged manifest')
    # Exact semantic schema matches can be computed for all exported tables,
    # including non-warning tables, solely from public hash metadata.
    schema_match = Counter()
    for item in source_entries:
        key = item['table']
        stem = key.rsplit('/', 1)[-1]
        digest = item.get('schema_semantic_sha256')
        if digest is None:
            schema_match['no_exported_schema_hash'] += 1
            continue
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            raise ValueError(f'Bad schema semantic digest for {key}')
        hist = by_name.get(stem, [])
        matches = [x for x in hist if x['sha256_semantic'] == digest]
        schema_match['historical_match' if matches else 'historical_no_match'] += 1
        if any(x['layer'] == 'pakchunk4-WindowsNoEditor' for x in matches):
            schema_match['matches_july_base'] += 1
        if matches and not any(x['layer'] == 'pakchunk4-WindowsNoEditor' for x in matches):
            schema_match['matches_historical_patch_only'] += 1
    items = []
    counts = Counter()
    never_seen_names = set()
    warned = [i for i in manifest['issues'] if i.get('code') == 'fields_not_in_schema']
    for issue in sorted(warned, key=lambda e: e['path']):
        table_id = table_id_from_issue_path(issue['path'])
        source = by_id.get(table_id)
        if source is None:
            raise ValueError(f'Warning refers to absent table: {table_id}')
        extras = issue.get('fields')
        if not isinstance(extras, list) or not extras or not all(isinstance(f, str) for f in extras):
            raise ValueError(f'Invalid warning field list for {table_id}')
        observed = source.get('observed_fields')
        if not isinstance(observed, list) or not set(extras).issubset(set(observed)):
            raise ValueError(f'Warning fields not present in observed fields for {table_id}')
        if len(extras) != len(set(extras)):
            raise ValueError(f'Duplicate warning fields for {table_id}')
        kind, stem = table_id.split('/', 1)
        historical = by_name.get(stem, [])
        matches, candidates = [], []
        observed_set, extra_set = set(observed), set(extras)
        fields_seen_before = set()
        full_observed_coverage = False
        full_extra_coverage = False
        for h in historical:
            declared = set(h['declared_fields'])
            fields_seen_before.update(declared)
            missing_observed = sorted(observed_set - declared)
            missing_extra = sorted(extra_set - declared)
            same_schema = h['sha256_semantic'] == source.get('schema_semantic_sha256')
            if same_schema:
                matches.append(h['layer'])
            full_observed_coverage |= not missing_observed
            full_extra_coverage |= not missing_extra
            candidates.append({
                'layer': h['layer'],
                'schema_path': h['path'],
                'schema_equals_exported': same_schema,
                'declared_field_count': len(declared),
                'observed_field_coverage': len(observed_set) - len(missing_observed),
                'observed_field_total': len(observed_set),
                'extra_field_coverage': len(extra_set) - len(missing_extra),
                'extra_field_total': len(extra_set),
                'uncovered_extra_fields': missing_extra,
            })
        entirely_new = sorted(extra_set - fields_seen_before)
        never_seen_names.update(entirely_new)
        counts['warning_files'] += 1
        counts['ordinary_warning_files' if kind != 'BinDataCompressed_ROW' else 'row_variant_warning_files'] += 1
        counts['warning_field_occurrences'] += len(extras)
        counts['historical_full_observed_coverage'] += int(full_observed_coverage)
        counts['historical_full_extra_coverage'] += int(full_extra_coverage)
        counts['exported_schema_same_as_base'] += int('pakchunk4-WindowsNoEditor' in matches)
        counts['exported_schema_matches_any_historical'] += int(bool(matches))
        counts['no_historical_schema_for_table'] += int(not historical)
        counts['warning_files_with_never_seen_fields'] += int(bool(entirely_new))
        counts['never_seen_field_occurrences'] += len(entirely_new)
        items.append({
            'table': table_id,
            'source_schema_sha256_semantic': source.get('schema_semantic_sha256'),
            'fields_missing_from_exported_schema': sorted(extras),
            'historical_schema_exact_matches': matches,
            'any_historical_schema_covers_all_observed_fields': full_observed_coverage,
            'any_historical_schema_covers_all_extra_fields': full_extra_coverage,
            'extras_not_seen_in_july_historical_schemas': entirely_new,
            'historical_candidates': candidates,
        })
    count_keys = [
        'warning_files', 'ordinary_warning_files', 'row_variant_warning_files',
        'warning_field_occurrences', 'historical_full_observed_coverage',
        'historical_full_extra_coverage', 'exported_schema_same_as_base',
        'exported_schema_matches_any_historical', 'no_historical_schema_for_table',
        'warning_files_with_never_seen_fields', 'never_seen_field_occurrences'
    ]
    match_keys = ['historical_match', 'historical_no_match', 'no_exported_schema_hash',
                  'matches_july_base', 'matches_historical_patch_only']
    return {
        'format': FORMAT,
        'snapshot_id': manifest.get('snapshot_id'),
        'snapshot_sha256_from_user_zip': manifest.get('input_zip_sha256'),
        'analysis_rule': 'compare top-level declared field names and canonical schema JSON hashes',
        'limitations': [
            'Historical July schemas are not proof of the correct October binary layout.',
            'An absent observed field may simply be optional and is not treated as a mismatch.',
            'The historical Pak filename order is not proof of runtime mount priority.',
            'This report does not include original game record values.',
        ],
        'summary': {
            'historical_schema_files_scanned': scanned,
            'all_exported_table_entries': len(source_entries),
            'exported_schema_match_statistics': {k: schema_match[k] for k in match_keys},
            **{k: counts[k] for k in count_keys},
            'distinct_never_seen_field_names': len(never_seen_names),
        },
        'warning_tables': items,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--history-root', type=Path, default=Path('.'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--summary', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.output.resolve() == args.summary.resolve() or args.output.resolve() == args.manifest.resolve() or args.summary.resolve() == args.manifest.resolve():
            raise ValueError('Output paths must be distinct from the source manifest and each other')
        with args.manifest.open('r', encoding='utf-8-sig') as f:
            manifest = json.load(f)
        result = analyze(manifest, args.history_root)
        # Local build outputs only. Do not mutate historical Pak directories.
        history_root = args.history_root.resolve()
        for layer in history_root.iterdir():
            if layer.is_dir() and LAYER_RE.fullmatch(layer.name):
                for dest in (args.output, args.summary):
                    if dest.resolve() == layer.resolve() or layer.resolve() in dest.resolve().parents:
                        raise ValueError('Refusing to write output inside historical Pak source')
        from merged_snapshot import write_json
        write_json(args.output, result)
        write_json(args.summary, {'format': result['format'], 'snapshot_id': result['snapshot_id'],
                                  'summary': result['summary'], 'limitations': result['limitations']})
        print(json.dumps(result['summary'], sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, OSError, UnicodeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
