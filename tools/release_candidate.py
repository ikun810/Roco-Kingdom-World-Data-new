#!/usr/bin/env python3
"""Validate and stage a LOCAL Roco merged-JSON candidate release.

The source is the user's FModel ZIP/directory, not a public GitHub asset. Audit
reports contain only metadata. The optional ZIP bundle includes game data and
must not be published unless distribution rights have been independently checked.
No Unreal Pak files are required or redistributed by this script.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import merged_snapshot

FORMAT = 'roco_candidate_release_gate_v1'
MANIFEST_FORMAT = 'roco_merged_snapshot_v1'
LINEAGE_FORMAT = 'roco_schema_lineage_v1'
FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def _read_json(path: Path) -> dict:
    with path.open('r', encoding='utf-8-sig') as stream:
        obj = json.load(stream)
    if not isinstance(obj, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return obj


def _verify_equal(actual: object, expected: object, description: str) -> None:
    if actual != expected:
        raise ValueError(f'Verification failed: {description}')


def _value_type(value: object) -> str:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, int):
        return 'int'
    if isinstance(value, float):
        return 'float'
    if isinstance(value, str):
        return 'str'
    if isinstance(value, list):
        return 'list'
    if isinstance(value, dict):
        return 'object'
    raise ValueError('Unsupported decoded JSON value type')


def _load_table(source: merged_snapshot.Source, path: str) -> tuple[dict, dict, bytes]:
    obj, raw = merged_snapshot.parse_json(source, path)
    rows = obj.get('RocoDataRows')
    if not isinstance(rows, dict) or not all(isinstance(row, dict) for row in rows.values()):
        raise ValueError(f'Invalid RocoDataRows: {path}')
    return obj, rows, raw


def audit(source: merged_snapshot.Source, manifest: dict, lineage: dict) -> dict:
    """Revalidate each of the 2,314 source files with hashes, without exposing row values."""
    if manifest.get('format') != MANIFEST_FORMAT:
        raise ValueError('Manifest must be roco_merged_snapshot_v1')
    if lineage.get('format') != LINEAGE_FORMAT:
        raise ValueError('Lineage must be roco_schema_lineage_v1')
    if source.zip_file is not None:
        _verify_equal(source.zip_sha256, manifest.get('input_zip_sha256'), 'original ZIP SHA-256')
    _verify_equal(lineage.get('snapshot_id'), manifest.get('snapshot_id'), 'lineage snapshot ID')
    _verify_equal(lineage.get('snapshot_sha256_from_user_zip'), manifest.get('input_zip_sha256'), 'lineage ZIP SHA-256')
    files = manifest.get('tables', []) + manifest.get('international_row_variants', [])
    schemas = {s.get('schema_path') for s in files if s.get('schema_path')}
    entries = list(files) + list(manifest.get('localizations', []))
    expected_source_paths = set(schemas)
    expected_source_paths.update(record['path'] for record in entries)
    _verify_equal(set(source.entry), expected_source_paths, 'source ZIP file set')
    _verify_equal(len(source.entry), manifest['summary']['json_files_in_input'], 'source file count')
    _verify_equal(len(manifest['tables']), manifest['summary']['regular_table_count'], 'normal table count')
    _verify_equal(len(manifest['international_row_variants']), manifest['summary']['row_variant_files'], 'ROW file count')
    _verify_equal(len(manifest.get('localizations', [])), manifest['summary']['localization_files'], 'localization count')

    computed_schema = {}
    for path in sorted(schemas):
        obj, raw = merged_snapshot.parse_json(source, path)
        props = obj.get('Properties')
        if not isinstance(props, list):
            raise ValueError(f'Malformed schema: {path}')
        names = [p['Name'] for p in props if isinstance(p, dict) and isinstance(p.get('Name'), str)]
        if len(names) != len(set(names)):
            raise ValueError(f'Duplicate declared schema fields: {path}')
        computed_schema[path] = {
            'sha256': merged_snapshot.canonical_hash(obj),
            'fields': set(names),
            'unique_key': obj.get('UniqueKey') or 'id',
        }

    by_path = {item['path']: item for item in files}
    if len(by_path) != len(files):
        raise ValueError('Duplicate data table path in manifest')
    lineage_by_table = {item['table']: item for item in lineage.get('warning_tables', [])}
    if len(lineage_by_table) != len(lineage.get('warning_tables', [])):
        raise ValueError('Duplicate warning table in lineage')
    manifest_issues = {
        (issue['path'], issue.get('code')): issue
        for issue in manifest.get('issues', []) if issue.get('code') == 'fields_not_in_schema'
    }
    if len(manifest_issues) != manifest['summary']['schema_discrepancy_tables']:
        raise ValueError('Malformed source schema warning count')
    if len(lineage_by_table) != len(manifest_issues):
        raise ValueError('Lineage warning entries do not match the source manifest')

    records = 0
    empty = 0
    id_inconsistency_tables = 0
    id_inconsistency_rows = 0
    id_key_anomalies: list[dict] = []
    tested_source_bytes = 0
    fields_not_seen_anywhere_in_july = []
    checked_warning_tables = []
    mismatch_counts = Counter()
    for path, entry in sorted(by_path.items()):
        _obj, rows, raw = _load_table(source, path)
        _verify_equal(merged_snapshot.sha256(raw), entry['raw_file_sha256'], f'{path} raw SHA-256')
        _verify_equal(merged_snapshot.canonical_hash(rows), entry['rows_semantic_sha256'], f'{path} semantic SHA-256')
        _verify_equal(merged_snapshot.canonical_hash(sorted(rows)), entry['row_ids_sha256'], f'{path} row-ID SHA-256')
        _verify_equal(len(rows), entry['row_count'], f'{path} row count')
        observed = {key for row in rows.values() for key in row}
        _verify_equal(sorted(observed), entry['observed_fields'], f'{path} observed fields')
        schema_path = entry['schema_path']
        if schema_path not in computed_schema:
            raise ValueError(f'Missing linked schema: {path}')
        schema = computed_schema[schema_path]
        _verify_equal(schema['sha256'], entry['schema_semantic_sha256'], f'{path} schema semantic SHA-256')
        extras = sorted(observed - schema['fields'])
        warning = manifest_issues.get((path, 'fields_not_in_schema'))
        _verify_equal(extras, warning.get('fields', []) if warning else [], f'{path} mismatch field list')
        if warning is not None:
            lin = lineage_by_table.get(entry['table'])
            if lin is None:
                raise ValueError(f'Warning missing in lineage: {entry["table"]}')
            _verify_equal(lin['fields_missing_from_exported_schema'], extras, f'{path} lineage warning field list')
            new_field_names = lin.get('extras_not_seen_in_july_historical_schemas', [])
            _verify_equal(sorted(set(new_field_names)), sorted(new_field_names), f'{path} new field names')
            row_counts = Counter()
            type_counts: dict[str, Counter] = defaultdict(Counter)
            for row in rows.values():
                for name in new_field_names:
                    if name in row:
                        row_counts[name] += 1
                        type_counts[name][_value_type(row[name])] += 1
            if new_field_names:
                fields_not_seen_anywhere_in_july.append({
                    'table': entry['table'], 'row_count': len(rows),
                    'new_fields': [
                        {'name': name, 'rows_present': row_counts[name],
                         'value_types': dict(sorted(type_counts[name].items()))}
                        for name in sorted(new_field_names)
                    ],
                    'prior_schema_versions_cover_all_observed': lin.get('any_historical_schema_covers_all_observed_fields', False),
                    'historical_schema_exact_matches': lin.get('historical_schema_exact_matches', []),
                })
            checked_warning_tables.append(entry['table'])
            mismatch_counts['warnings'] += 1
        uid = schema['unique_key']
        if isinstance(uid, str):
            mismatches = sum(1 for rid, row in rows.items() if uid in row and str(row[uid]) != rid)
            if mismatches:
                id_inconsistency_rows += mismatches
                id_inconsistency_tables += 1
                id_key_anomalies.append({'table': entry['table'], 'rows': mismatches,
                                         'declared_unique_key': uid,
                                         'note': 'Record map keys may be named configuration keys; ID mismatch is not automatically corruption.'})
        if entry['table'].startswith('BinDataCompressed/'):
            records += len(rows)
            empty += len(rows) == 0
        tested_source_bytes += len(raw)
    _verify_equal(records, manifest['summary']['regular_record_count'], 'regular record total')
    _verify_equal(empty, manifest['summary']['empty_regular_tables'], 'empty normal tables')
    for loc in manifest.get('localizations', []):
        obj, raw = merged_snapshot.parse_json(source, loc['path'])
        strings = obj.get('LocalizationStrings')
        if not isinstance(strings, dict):
            raise ValueError(f'Invalid LocalizationStrings: {loc["path"]}')
        _verify_equal(merged_snapshot.sha256(raw), loc['file_sha256'], f'{loc["path"]} file SHA-256')
        _verify_equal(merged_snapshot.canonical_hash(strings), loc['strings_semantic_sha256'], f'{loc["path"]} strings SHA-256')
        _verify_equal(len(strings), loc['strings_count'], f'{loc["path"]} localization count')
        tested_source_bytes += len(raw)
    # Schemas' hashes are indirectly verified by all linked table semantic hashes.
    if len(schemas) != manifest['summary']['schema_files']:
        raise ValueError('Distinct schema file count mismatch')
    _verify_equal(len(fields_not_seen_anywhere_in_july),
                  lineage['summary']['warning_files_with_never_seen_fields'],
                  'tables with fields absent from July history')
    _verify_equal(len(checked_warning_tables), lineage['summary']['warning_files'], 'warning table count')
    season = by_path.get('BinDataCompressed/SEASON_CONF.json')
    if manifest.get('game_version') == '1.111.0.177':
        if season is None:
            raise ValueError('Expected SEASON_CONF in October snapshot')
        _obj, season_rows, _raw = _load_table(source, season['path'])
        if not {'1', '2', '3', '4'}.issubset(season_rows):
            raise ValueError('October season configuration does not include S1-S4')
    return {
        'format': FORMAT,
        'snapshot_id': manifest['snapshot_id'],
        'game_version': manifest.get('game_version'),
        'build_number': manifest.get('build_number'),
        'source_zip_sha256': manifest.get('input_zip_sha256'),
        'upstream_lineage_run': '41069687803',
        'input_count': len(source.entry),
        'technical_integrity': {
            'status': 'passed',
            'file_sha256_and_semantic_hashes_match': True,
            'source_manifest_complete': True,
            'original_json_parse_errors': 0,
            'ordinary_tables': len(manifest['tables']),
            'international_row_files': len(manifest['international_row_variants']),
            'schema_files': len(schemas),
            'localization_files': len(manifest['localizations']),
            'ordinary_row_count': records,
            'ordinary_empty_tables': empty,
            'source_bytes_of_data_and_localization_verified': tested_source_bytes,
            'id_unique_key_mismatch_rows': id_inconsistency_rows,
            'id_unique_key_mismatch_tables': id_inconsistency_tables,
            'id_key_anomalies': id_key_anomalies,
            'season_ids_1_through_4_present': manifest.get('game_version') == '1.111.0.177',
        },
        'schema_review': {
            'status': 'incomplete',
            'record_fields_outside_exported_schema_tables': len(checked_warning_tables),
            'tables_with_fields_not_seen_in_july': len(fields_not_seen_anywhere_in_july),
            'new_fields_occurrences': sum(len(item['new_fields']) for item in fields_not_seen_anywhere_in_july),
            'rows_for_unseen_fields_checked': True,
            'unseen_field_details': sorted(fields_not_seen_anywhere_in_july, key=lambda x: x['table']),
            'evidence_limit': 'The FModel merged JSON does not prove the originating Pak and corresponding .non for each table.',
        },
        'release_decision': {
            'private_candidate_preparation': 'ready',
            'public_release': 'hold_until_rights_and_schema_provenance_review',
            'does_not_contain_raw_game_values': True,
            'reason': 'Source rights for public redistribution unverified; per-table .non/Pak provenance is unverified for some tables.',
        },
    }


def pack_local(source: merged_snapshot.Source, manifest: dict, audit_report: dict, output: Path) -> None:
    """Stage a portable bundle LOCAL to the user's environment; never commit it to Git."""
    if source.path.is_dir() and output.resolve().is_relative_to(source.path.resolve()):
        raise ValueError('Output must not be placed inside the source tree')
    if source.path.is_file() and output.resolve() == source.path.resolve():
        raise ValueError('Output must not overwrite the input ZIP')
    if output.exists():
        raise ValueError('Refusing to overwrite existing release package')
    output.parent.mkdir(parents=True, exist_ok=True)
    def add_text(archive: zipfile.ZipFile, arcname: str, text: str):
        info = zipfile.ZipInfo(arcname, FIXED_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, text.encode('utf-8'), compresslevel=6)
    try:
        with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                             allowZip64=True) as archive:
            for rel in sorted(source.entry):
                # All source files have already passed the manifest verification above.
                info = zipfile.ZipInfo('Bin/' + rel, FIXED_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, source.read(rel), compresslevel=6)
            add_text(archive, 'metadata/source_manifest.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
            add_text(archive, 'metadata/technical_audit.json', json.dumps(audit_report, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
            add_text(archive, 'README_LOCAL_REVIEW.txt',
                     'ROCO Kingdom World candidate data release ' + manifest['snapshot_id'] + '\n'
                     'Private review only: the payload contains third-party game data.\n'
                     'Do not upload the payload to a public repository without checking redistribution permission.\n'
                     'Do not replace the July Pak-history directory with this merged export.\n'
                     'The merge does not attest individual Pak mount/Schema provenance.\n')
    except BaseException:
        output.unlink(missing_ok=True)
        raise



def check_published_report(manifest: dict, lineage: dict, report: dict) -> None:
    """CI consistency check only; does not replace source ZIP byte verification."""
    if manifest.get('format') != MANIFEST_FORMAT or lineage.get('format') != LINEAGE_FORMAT:
        raise ValueError('Unexpected source metadata formats')
    if report.get('format') != FORMAT:
        raise ValueError('Unexpected release-audit report format')
    if report.get('snapshot_id') != manifest.get('snapshot_id') or report['snapshot_id'] != lineage.get('snapshot_id'):
        raise ValueError('Snapshot IDs are inconsistent')
    digest = manifest.get('input_zip_sha256')
    if digest != report.get('source_zip_sha256') or digest != lineage.get('snapshot_sha256_from_user_zip'):
        raise ValueError('ZIP SHA-256 metadata mismatch')
    summaries = report.get('technical_integrity', {}), report.get('schema_review', {})
    t, s = summaries
    if not (t.get('status') == 'passed' and t.get('file_sha256_and_semantic_hashes_match') is True):
        raise ValueError('Local archive verification is not marked passed')
    expected = {
        'input_count': manifest['summary']['json_files_in_input'],
        'ordinary_tables': manifest['summary']['regular_table_count'],
        'international_row_files': manifest['summary']['row_variant_files'],
        'schema_files': manifest['summary']['schema_files'],
        'localization_files': manifest['summary']['localization_files'],
        'ordinary_row_count': manifest['summary']['regular_record_count'],
        'ordinary_empty_tables': manifest['summary']['empty_regular_tables'],
        'record_fields_outside_exported_schema_tables': lineage['summary']['warning_files'],
        'tables_with_fields_not_seen_in_july': lineage['summary']['warning_files_with_never_seen_fields'],
        'new_fields_occurrences': lineage['summary']['never_seen_field_occurrences'],
    }
    for key, val in expected.items():
        actual = report['input_count'] if key == 'input_count' else t.get(key, s.get(key))
        _verify_equal(actual, val, f'published report {key}')
    if report.get('release_decision', {}).get('public_release') == 'ready':
        raise ValueError('Metadata cannot attest public redistribution permission')
    lineage_new = {
        item['table']: sorted(item['extras_not_seen_in_july_historical_schemas'])
        for item in lineage['warning_tables'] if item['extras_not_seen_in_july_historical_schemas']
    }
    report_new = {
        item['table']: sorted(f['name'] for f in item['new_fields'])
        for item in s.get('unseen_field_details', [])
    }
    _verify_equal(report_new, lineage_new, 'published new fields vs historical lineage')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Local FModel merged ZIP or Bin/ directory')
    parser.add_argument('--manifest', type=Path, required=True, help='Metadata-only snapshot already generated')
    parser.add_argument('--lineage', type=Path, required=True, help='PR #7 schema lineage metadata')
    parser.add_argument('--report', type=Path, required=True, help='Local metadata-only QA report JSON')
    parser.add_argument('--package', type=Path, help='Optional local private-review ZIP including game data')
    parser.add_argument('--check-published-report', action='store_true', help='CI: check published report against metadata only, without game ZIP')
    args = parser.parse_args(argv)
    try:
        if args.package is not None and args.package.resolve() == args.report.resolve():
            raise ValueError('Package and report paths must differ')
        manifest, lineage = _read_json(args.manifest), _read_json(args.lineage)
        if args.check_published_report:
            if args.source is not None or args.package is not None:
                raise ValueError('Metadata-only mode forbids source/package arguments')
            check_published_report(manifest, lineage, _read_json(args.report))
            print(json.dumps({'snapshot_id': manifest['snapshot_id'],
                              'metadata_consistent': True,
                              'zip_bytes_verified_in_this_run': False},sort_keys=True))
            return 0
        if args.source is None:
            raise ValueError('--source required for local archive audit')
        if args.report.resolve() in (args.source.resolve(), args.manifest.resolve(), args.lineage.resolve()):
            raise ValueError('Cannot overwrite source or metadata inputs')
        if args.source.is_dir() and args.report.resolve().is_relative_to(args.source.resolve()):
            raise ValueError('Cannot write report inside source')
        with merged_snapshot.Source(args.source) as source:
            result = audit(source, manifest, lineage)
            if args.package:
                pack_local(source, manifest, result, args.package)
        merged_snapshot.write_json(args.report, result)
        print(json.dumps({
            'snapshot_id': result['snapshot_id'],
            'files_verified': result['input_count'],
            'ordinary_records': result['technical_integrity']['ordinary_row_count'],
            'new_field_tables': result['schema_review']['tables_with_fields_not_seen_in_july'],
            'private_bundle': str(args.package) if args.package else None,
            'public_release': result['release_decision']['public_release'],
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, IndexError, TypeError, UnicodeError,
            zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
