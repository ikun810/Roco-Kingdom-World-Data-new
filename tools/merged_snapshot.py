#!/usr/bin/env python3
"""Metadata-only snapshot / comparison for FModel's merged Roco Bin JSON export.

Neither operation copies original game data into the produced metadata. A ZIP is
read without extracting paths. The baseline is the existing candidate Pak view,
not a claim that the client's runtime mount priority was independently proven.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from zipfile import ZipFile

FORMAT = 'roco_merged_snapshot_v1'
COMPRESSED = 'BinDataCompressed'
DATA_KINDS = ('BinDataCompressed', 'BinData')
SAFE_STEM = re.compile(r'^[A-Za-z0-9_-]+$')
MAX_FILE = 128 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value: object) -> str:
    # The source and the old repository may indent JSON differently. Compare
    # decoded JSON values instead of raw file bytes or Python object key order.
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8'))


def safe_rel(raw: str) -> str:
    if '\\' in raw or raw.startswith('/') or raw.startswith('./') or '\x00' in raw:
        raise ValueError(f'Unsafe archive path: {raw!r}')
    parts = PurePosixPath(raw).parts
    if not parts or any(x in ('..', '.') for x in parts):
        raise ValueError(f'Unsafe archive path: {raw!r}')
    # The input may be an FModel output root or its Bin/ directory.
    if parts[0] == 'Bin':
        parts = parts[1:]
    if not parts:
        raise ValueError(f'Unsafe archive path: {raw!r}')
    return '/'.join(parts)


def classify(path: str) -> tuple[str, str] | None:
    parts = path.split('/')
    if len(parts) == 2 and parts[1].endswith('.json') and SAFE_STEM.fullmatch(parts[1][:-5]):
        if parts[0] in DATA_KINDS:
            return ('data', f'{parts[0]}/{parts[1][:-5]}')
        if parts[0] == 'BinConf':
            return ('schema', parts[1][:-5])
    if (len(parts) == 3 and parts[0] == COMPRESSED
            and parts[1] == 'BinDataCompressed_ROW' and parts[2].endswith('.json')
            and SAFE_STEM.fullmatch(parts[2][:-5])):
        return ('row', parts[2][:-5])
    if (len(parts) == 3 and parts[0] == 'BinLocalize'
            and SAFE_STEM.fullmatch(parts[1]) and parts[2].endswith('.json')
            and SAFE_STEM.fullmatch(parts[2][:-5])):
        return ('localization', '/'.join(parts[1:]))
    return None


class Source:
    """Safely enumerate and read a ZIP or directory without extracting files."""
    def __init__(self, path: Path):
        self.path = path
        self.zip_file: ZipFile | None = None
        self.entry: dict[str, str | Path] = {}
        self.zip_sha256: str | None = None
        if path.is_file():
            self.zip_file = ZipFile(path)
            self.zip_sha256 = file_sha256(path)
            entries = [(p.filename, p) for p in self.zip_file.infolist() if not p.is_dir()]
            total = sum(info.file_size for _, info in entries)
            if total > MAX_TOTAL:
                raise ValueError('ZIP uncompressed total exceeds limit')
            for name, info in entries:
                if info.file_size > MAX_FILE:
                    raise ValueError(f'ZIP entry too large: {name}')
                rel = safe_rel(name)
                if rel in self.entry:
                    raise ValueError(f'Duplicate ZIP logical path: {rel}')
                # Refuse symlink entries, even though we never extract them.
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError(f'Symlink in ZIP: {rel}')
                self.entry[rel] = info.filename
        elif path.is_dir():
            base = path / 'Bin' if (path / 'Bin').is_dir() else path
            for root, dirs, files in os.walk(base, followlinks=False):
                current = Path(root)
                if current.is_symlink() or any((current / d).is_symlink() for d in dirs):
                    raise ValueError('Symlinks are not allowed in source directories')
                for name in files:
                    item = current / name
                    if item.is_symlink():
                        raise ValueError(f'Source symlink: {item}')
                    rel = safe_rel(item.relative_to(base).as_posix())
                    if rel in self.entry:
                        raise ValueError(f'Duplicate logical path: {rel}')
                    self.entry[rel] = item
        else:
            raise ValueError(f'Source must be an existing ZIP or directory: {path}')

    def read(self, path: str) -> bytes:
        item = self.entry[path]
        if self.zip_file is not None:
            return self.zip_file.read(str(item))
        p = Path(item)
        if p.stat().st_size > MAX_FILE:
            raise ValueError(f'Source entry too large: {path}')
        return p.read_bytes()

    def close(self):
        if self.zip_file is not None:
            self.zip_file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def parse_json(source: Source, path: str) -> tuple[dict, bytes]:
    raw = source.read(path)
    obj = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(obj, dict):
        raise ValueError(f'JSON root is not an object: {path}')
    return obj, raw


def make_snapshot(source: Source, *, game_version: str, build_number: str,
                  capture_date: str, season_source_pak: str | None = None) -> dict:
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2,5}', game_version):
        raise ValueError('Invalid game version')
    if not re.fullmatch(r'[0-9]+', build_number):
        raise ValueError('Invalid build number')
    if not re.fullmatch(r'\d{4}-\d\d-\d\d', capture_date):
        raise ValueError('capture_date must be YYYY-MM-DD')
    entries = sorted(p for p in source.entry if classify(p) is not None)
    grouped: dict[str, list[tuple[str, str]]] = {x: [] for x in ('data', 'schema', 'localization', 'row')}
    for p in entries:
        k, logical = classify(p)  # type: ignore[misc]
        grouped[k].append((p, logical))
    schema_map = {}
    issues = []
    for p, stem in grouped['schema']:
        data, raw = parse_json(source, p)
        props = data.get('Properties')
        if not isinstance(props, list):
            issues.append({'path': p, 'code': 'schema_properties_invalid'})
            fields = []
        else:
            fields = sorted({x['Name'] for x in props
                             if isinstance(x, dict) and isinstance(x.get('Name'), str)})
        schema_map[stem] = {'path': p, 'sha256': sha256(raw),
                            'schema_value_sha256': canonical_hash(data),
                            'declared_fields': fields, 'unique_key': data.get('UniqueKey')}
    tables = []
    row_overlays = []
    count_rows = 0
    empty = 0
    for kind in ('data', 'row'):
        for path, key in grouped[kind]:
            obj, raw = parse_json(source, path)
            rows = obj.get('RocoDataRows')
            if not isinstance(rows, dict):
                issues.append({'path': path, 'code': 'invalid_roco_data_rows'})
                continue
            invalid_rows = sum(not isinstance(v, dict) for v in rows.values())
            if invalid_rows:
                issues.append({'path': path, 'code': 'invalid_row_shape', 'count': invalid_rows})
            fields = sorted({field for val in rows.values() if isinstance(val, dict)
                             for field in val.keys()})
            stem = key.split('/')[-1]
            schema = schema_map.get(stem)
            if schema is None:
                issues.append({'path': path, 'code': 'missing_matching_schema'})
            extra_fields = sorted(set(fields) - set(schema['declared_fields'])) if schema else []
            if extra_fields:
                issues.append({'path': path, 'code': 'fields_not_in_schema', 'severity': 'warning',
                               'field_count': len(extra_fields), 'fields': extra_fields})
            row_count = len(rows)
            record = {
                'table': key if kind == 'data' else f'BinDataCompressed_ROW/{key}',
                'path': path, 'raw_file_sha256': sha256(raw),
                'rows_semantic_sha256': canonical_hash(rows),
                'row_ids_sha256': canonical_hash(sorted(rows)),
                'row_count': row_count, 'observed_fields': fields,
                'schema_path': schema['path'] if schema else None,
                'schema_semantic_sha256': schema['schema_value_sha256'] if schema else None,
                'schema_source_layer': None,
                'schema_source_verified': False,
                'schema_alignment': 'observed_extra_fields' if extra_fields else 'no_extra_fields_observed',
            }
            if kind == 'data':
                tables.append(record)
                count_rows += row_count
                empty += row_count == 0
            else:
                # ROW configurations are separate international variants, never
                # silently counted as regular effective tables or overlaid.
                row_overlays.append(record)
    locales = []
    for path, key in grouped['localization']:
        obj, raw = parse_json(source, path)
        strings = obj.get('LocalizationStrings')
        if not isinstance(strings, dict):
            issues.append({'path': path, 'code': 'invalid_localization_strings'})
            continue
        locales.append({'locale_file': key, 'path': path,
                        'file_sha256': sha256(raw),
                        'strings_semantic_sha256': canonical_hash(strings),
                        'strings_count': len(strings)})
    known = len(entries)
    other = sorted(set(source.entry) - set(entries))
    summary = {
        'json_files_in_input': len(source.entry),
        'classified_json_files': known,
        'other_files_not_processed': len(other),
        'schema_files': len(schema_map),
        'regular_table_count': len(tables),
        'regular_record_count': count_rows,
        'empty_regular_tables': empty,
        'row_variant_files': len(row_overlays),
        'localization_files': len(locales),
        'issue_count': len(issues),
        'schema_discrepancy_tables': sum(i['code'] == 'fields_not_in_schema' for i in issues),
        'fatal_issue_count': sum(i.get('severity', 'error') == 'error' for i in issues),
    }
    return {
        'format': FORMAT,
        'snapshot_id': f'pc-{game_version}-{build_number}',
        'game_version': game_version, 'build_number': build_number,
        'capture_date': capture_date,
        'input_type': 'zip' if source.zip_file else 'directory',
        'input_zip_sha256': source.zip_sha256,
        'source_kind': 'user_supplied_fmodel_merged_export',
        'source_path_disclosed': False,
        'full_pak_layer_provenance_available': False,
        'game_runtime_mount_order_verified': False,
        'table_selection': 'fmodel_merged_export_candidate',
        'season_conf_source_pak_reported': season_source_pak,
        'notice': 'Metadata and hashes only; not proof that FModel selected every runtime-effective file. No game record values are embedded.',
        'summary': summary,
        'tables': sorted(tables, key=lambda x: x['table']),
        'international_row_variants': sorted(row_overlays, key=lambda x: x['table']),
        'localizations': sorted(locales, key=lambda x: x['locale_file']),
        'issues': sorted(issues, key=lambda x: (x['path'], x['code'])),
    }


def compare_to_view(new: dict, old_view: dict, old_root: Path) -> dict:
    if new.get('format') != FORMAT:
        raise ValueError('Unknown merged snapshot manifest format')
    if old_view.get('view_format') != '1.0':
        raise ValueError('Expected the prior effective_view.py catalog view')
    import effective_view  # existing sibling in tools/
    recent = {t['table']: t for t in new['tables']}
    baseline = {t['table']: t for t in old_view['tables']}
    details = []
    counts = Counter()
    delta_all = 0
    for key in sorted(set(recent) | set(baseline)):
        before, after = baseline.get(key), recent.get(key)
        if before is None:
            category = 'added_in_new_export'
            old_count, old_fields, old_hash = None, [], None
        else:
            old_rows = effective_view.load_selected_rows(old_root, before)
            old_hash = canonical_hash(old_rows)
            old_count = len(old_rows)
            old_fields = before.get('observed_fields', [])
            if after is None:
                # Absence from an FModel export does not establish deletion.
                category = 'missing_from_new_export_unverified'
            elif old_hash == after['rows_semantic_sha256']:
                category = 'unchanged'
            else:
                category = 'modified'
        new_count = after['row_count'] if after is not None else None
        if after is None:
            new_fields = []
        else:
            new_fields = after.get('observed_fields', [])
        diff_count = (new_count - old_count) if (new_count is not None and old_count is not None) else None
        if diff_count is not None:
            delta_all += diff_count
        counts[category] += 1
        details.append({
            'table': key, 'classification': category,
            'prior_rows': old_count, 'new_rows': new_count,
            'row_count_change': diff_count,
            'prior_semantic_sha256': old_hash,
            'new_semantic_sha256': after['rows_semantic_sha256'] if after else None,
            'row_ids_same': (canonical_hash(sorted(old_rows)) == after['row_ids_sha256'])
            if after is not None and before is not None else None,
            'fields_added': sorted(set(new_fields) - set(old_fields)) if after else [],
            'fields_removed': sorted(set(old_fields) - set(new_fields)) if after else [],
            'record_id_diff_not_computed': True,
        })
    return {
        'format': 'roco_merged_vs_effective_v1',
        'new_snapshot': new['snapshot_id'],
        'old_snapshot': old_view.get('snapshot_label'),
        'old_priority_verified': old_view.get('pak_mount_order_verified', False),
        'new_runtime_mount_verified': new['game_runtime_mount_order_verified'],
        'record_id_comparison': 'hash_match_only; per-ID added/removed/changed requires both raw snapshot sets',
        'warning': 'Files absent from the merged export are not assumed deleted from the game.',
        'summary': {
            'prior_table_count': len(baseline),
            'new_table_count': len(recent),
            'prior_row_total': old_view['summary']['effective_rows'],
            'new_row_total': new['summary']['regular_record_count'],
            'row_delta_across_all_tables_not_valid_if_missing': len(baseline.keys() - recent.keys()) > 0,
            'compared_rows_delta_only_tables_present_in_both': delta_all,
            **{key: counts[key] for key in ('unchanged', 'modified', 'added_in_new_export',
                                            'missing_from_new_export_unverified')},
        },
        'tables': details,
    }


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', suffix='.tmp', delete=False) as f:
            temp = Path(f.name)
            json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
        temp.replace(path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    a = sub.add_parser('snapshot', help='Generate metadata-only manifest from FModel merged Bin ZIP or directory')
    a.add_argument('--source', type=Path, required=True)
    a.add_argument('--game-version', required=True)
    a.add_argument('--build-number', required=True)
    a.add_argument('--capture-date', required=True)
    a.add_argument('--season-source-pak')
    a.add_argument('--output', type=Path, required=True)
    a.add_argument('--strict', action='store_true')
    b = sub.add_parser('compare', help='Compare new merged metadata with historical effective whole-file view')
    b.add_argument('--new-manifest', type=Path, required=True)
    b.add_argument('--old-view', type=Path, required=True)
    b.add_argument('--old-root', type=Path, required=True)
    b.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.action == 'snapshot':
            if args.source.is_dir() and args.output.resolve().is_relative_to(args.source.resolve()):
                raise ValueError('Refusing to write output inside source tree')
            if args.source.is_file() and args.output.resolve() == args.source.resolve():
                raise ValueError('Output must not overwrite input ZIP')
            with Source(args.source) as src:
                result = make_snapshot(src, game_version=args.game_version,
                                       build_number=args.build_number,
                                       capture_date=args.capture_date,
                                       season_source_pak=args.season_source_pak)
            write_json(args.output, result)
            print(json.dumps(result['summary'], ensure_ascii=False, sort_keys=True))
            return 2 if args.strict and result['summary']['fatal_issue_count'] else 0
        if args.output.resolve() in (args.new_manifest.resolve(), args.old_view.resolve()):
            raise ValueError('Refusing to replace input manifest')
        with args.new_manifest.open('r', encoding='utf-8-sig') as stream:
            new = json.load(stream)
        with args.old_view.open('r', encoding='utf-8-sig') as stream:
            old = json.load(stream)
        result = compare_to_view(new, old, args.old_root)
        write_json(args.output, result)
        print(json.dumps(result['summary'], ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
