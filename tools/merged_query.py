#!/usr/bin/env python3
"""Read a versioned, FModel-merged Roco configuration ZIP without materializing a Pak overlay.

This tool does not decrypt .pak files, infer mount order, correct Schema, publish game
records, or mix international ROW variants with domestic configuration tables.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from zipfile import BadZipFile

import merged_snapshot
from effective_search import DOMAIN_TABLES

FORMAT = 'roco_merged_snapshot_v1'
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
TABLE = re.compile(r'(BinDataCompressed|BinData)/[A-Za-z0-9_-]+\Z')
MAX_RESULTS = 100
MAX_QUERY = 200


def load_manifest(path: Path) -> dict:
    with path.open('r', encoding='utf-8-sig') as reader:
        doc = json.load(reader)
    if not isinstance(doc, dict) or doc.get('format') != FORMAT:
        raise ValueError('Expected a roco_merged_snapshot_v1 manifest')
    if not isinstance(doc.get('tables'), list) or not isinstance(doc.get('summary'), dict):
        raise ValueError('Manifest lacks table listings or summary')
    if not isinstance(doc.get('snapshot_id'), str) or not doc['snapshot_id']:
        raise ValueError('Missing snapshot ID')
    digest = doc.get('input_zip_sha256')
    if digest is not None and (not isinstance(digest, str) or not SHA256.fullmatch(digest)):
        raise ValueError('Invalid source ZIP SHA-256 in manifest')
    return doc


def index_tables(doc: dict) -> dict[str, dict]:
    """Reject forged paths, bad hashes, duplicate tables, and invalid row counts."""
    mapping = {}
    for item in doc['tables']:
        if not isinstance(item, dict):
            raise ValueError('Malformed manifest table')
        key, path = item.get('table'), item.get('path')
        digest, row_sha = item.get('raw_file_sha256'), item.get('rows_semantic_sha256')
        ids_sha = item.get('row_ids_sha256')
        if not isinstance(key, str) or not TABLE.fullmatch(key) or path != f'{key}.json':
            raise ValueError(f'Invalid manifest table source: {key!r} {path!r}')
        if any(not isinstance(h, str) or not SHA256.fullmatch(h)
               for h in (digest, row_sha, ids_sha)):
            raise ValueError(f'Missing or malformed SHA-256 for {key}')
        if type(item.get('row_count')) is not int or item['row_count'] < 0:
            raise ValueError(f'Invalid row count for {key}')
        if key in mapping:
            raise ValueError(f'Duplicate table {key}')
        mapping[key] = item
    if len(mapping) != doc['summary'].get('regular_table_count'):
        raise ValueError('Regular table count differs from manifest summary')
    return mapping


def open_source(path: Path, doc: dict) -> merged_snapshot.Source:
    source = merged_snapshot.Source(path)
    if source.zip_file is not None:
        fingerprint = doc.get('input_zip_sha256')
        if fingerprint is None or fingerprint != source.zip_sha256:
            source.close()
            raise ValueError('Input ZIP SHA-256 differs from the registered snapshot')
    return source


def table_key(raw: str) -> str:
    value = raw.removesuffix('.json')
    key = value if '/' in value else f'BinDataCompressed/{value}'
    if not TABLE.fullmatch(key):
        raise ValueError(f'Invalid table name: {raw!r}')
    return key


def read_rows(source: merged_snapshot.Source, item: dict) -> dict:
    path = item['path']
    if path not in source.entry:
        raise ValueError(f'Missing snapshot file: {path}')
    data, raw = merged_snapshot.parse_json(source, path)
    if merged_snapshot.sha256(raw) != item['raw_file_sha256']:
        raise ValueError(f'Source file SHA-256 mismatch: {path}')
    rows = data.get('RocoDataRows')
    if not isinstance(rows, dict) or not all(isinstance(r, dict) for r in rows.values()):
        raise ValueError(f'Invalid RocoDataRows: {path}')
    if len(rows) != item['row_count']:
        raise ValueError(f'Row count mismatch: {path}')
    if merged_snapshot.canonical_hash(rows) != item['rows_semantic_sha256']:
        raise ValueError(f'Semantic row hash mismatch: {path}')
    if merged_snapshot.canonical_hash(sorted(rows)) != item['row_ids_sha256']:
        raise ValueError(f'Record ID hash mismatch: {path}')
    if sorted({f for rec in rows.values() for f in rec}) != item.get('observed_fields'):
        raise ValueError(f'Observed field mismatch: {path}')
    return rows


def notice(doc: dict) -> dict:
    return {
        'snapshot_id': doc['snapshot_id'],
        'input_kind': doc.get('source_kind'),
        'pak_mount_order_verified': False,
        'per_table_schema_origin_verified': False,
        'release_status': 'published_archive_schema_origin_unverified',
    }


def tables(doc: dict, entries: dict[str, dict], filter_text: str = '') -> dict:
    if len(filter_text) > MAX_QUERY:
        raise ValueError('Table filter is too long')
    hits = [dict(table=k, row_count=v['row_count'], schema_alignment=v.get('schema_alignment'))
            for k, v in sorted(entries.items()) if filter_text.casefold() in k.casefold()]
    return {**notice(doc), 'total': len(hits), 'tables': hits}


def get_record(doc: dict, entries: dict[str, dict], source: merged_snapshot.Source,
               table: str, rid: str) -> dict:
    key = table_key(table)
    if key not in entries:
        raise ValueError(f'Unknown table: {key}')
    rows = read_rows(source, entries[key])
    if rid not in rows:
        raise ValueError(f'Record {rid!r} not found in {key}')
    return {**notice(doc), 'table': key, 'id': rid, 'record': rows[rid],
            'source_path': entries[key]['path'], 'schema_alignment': entries[key].get('schema_alignment')}


def match_name(doc: dict, entries: dict[str, dict], source: merged_snapshot.Source,
               query: str, domain: list[str] | None = None, table: list[str] | None = None,
               limit: int = 20, exact: bool = False) -> dict:
    if not query.strip() or len(query) > MAX_QUERY:
        raise ValueError('Query must contain 1-200 nonblank characters')
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f'--limit must be between 1 and {MAX_RESULTS}')
    if domain and any(d not in DOMAIN_TABLES for d in domain):
        raise ValueError('Unknown search domain')
    choices = {}  # exact BinDataCompressed table key -> whitelisted fields
    for dom in domain or list(DOMAIN_TABLES):
        for stem, fields in DOMAIN_TABLES[dom].items():
            key = 'BinDataCompressed/' + stem
            if key in entries:
                choices.setdefault(key, set()).update(fields)
    if table:
        selected = set(table_key(x) for x in table)
        unknown = selected - set(entries)
        if unknown:
            raise ValueError('Unknown tables: ' + ', '.join(sorted(unknown)))
        unapproved = selected - set(choices)
        if unapproved:
            raise ValueError('Name search only supports curated tables: ' + ', '.join(sorted(unapproved)))
        choices = {k: v for k, v in choices.items() if k in selected}
    results = []
    total = 0
    needle = query.casefold()
    for key in sorted(choices):
        rows = read_rows(source, entries[key])
        allowed = sorted(choices[key])
        for rid, row in sorted(rows.items()):
            for field in allowed:
                value = row.get(field)
                if not isinstance(value, str):
                    continue
                value_folded = value.casefold()
                matched = value_folded == needle if exact else needle in value_folded
                if matched:
                    total += 1
                    if len(results) < limit:
                        results.append({'table': key, 'id': rid, 'field': field,
                                        'name': value[:150]})
    return {**notice(doc), 'query': query, 'domains': domain or list(DOMAIN_TABLES),
            'total_matches': total, 'truncated': total > limit, 'results': results}


def safe_output(obj: object) -> None:
    formatted = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)
    try:
        print(formatted)
    except UnicodeEncodeError:
        print(json.dumps(obj, ensure_ascii=True, indent=2, allow_nan=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True,
                        help='Existing metadata-only snapshot manifest')
    parser.add_argument('--source', type=Path,
                        help='Local FModel merged JSON ZIP or Bin/ directory (required for get/search)')
    sub = parser.add_subparsers(dest='command', required=True)
    li = sub.add_parser('tables', help='List registered tables without opening data files')
    li.add_argument('--filter', default='')
    get = sub.add_parser('get', help='Read exactly one record from a hash-verified source table')
    get.add_argument('--table', required=True)
    get.add_argument('--id', required=True)
    search = sub.add_parser('search', help='Search only curated names, not dialogues or descriptions')
    search.add_argument('--query', required=True)
    search.add_argument('--domain', action='append', choices=list(DOMAIN_TABLES))
    search.add_argument('--table', action='append')
    search.add_argument('--limit', type=int, default=20)
    search.add_argument('--exact', action='store_true')
    args = parser.parse_args(argv)
    try:
        doc = load_manifest(args.manifest)
        entries = index_tables(doc)
        if args.command == 'tables':
            # A manifest-only listing is useful even when raw data is not present.
            # When a source is supplied, also verify its registered ZIP checksum.
            if args.source is not None:
                with open_source(args.source, doc):
                    pass
            result = tables(doc, entries, args.filter)
        else:
            if args.source is None:
                raise ValueError('--source is required for get/search')
            with open_source(args.source, doc) as source:
                if args.command == 'get':
                    result = get_record(doc, entries, source, args.table, args.id)
                else:
                    result = match_name(doc, entries, source, args.query,
                                        args.domain, args.table, args.limit, args.exact)
        safe_output(result)
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, BadZipFile,
            json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
