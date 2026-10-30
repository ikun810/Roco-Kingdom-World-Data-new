"""Synthetic-only merged FModel snapshot/overlay regression tests (no game data)."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import merged_snapshot as mod

BASE = 'pakchunk4-WindowsNoEditor'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = {
            'BinConf/SEASON_CONF.json': encoded({'UniqueKey': 'id', 'Properties': [
                {'Name': 'id'}, {'Name': 's_title_subtitle'}]}),
            'BinDataCompressed/SEASON_CONF.json': encoded({'RocoDataRows': {
                '1': {'id': 1, 's_title_subtitle': '旧日'},
                '4': {'id': 4, 's_title_subtitle': '月涌狂想'}}}),
            'BinDataCompressed/PETBASE_CONF.json': encoded({'RocoDataRows': {
                '1': {'id': 1, 'name': '喵喵'}}}),
            'BinConf/PETBASE_CONF.json': encoded({'UniqueKey': 'id', 'Properties': [
                {'Name': 'id'}, {'Name': 'name'}]}),
            'BinConf/ACTIVITY_CONF.json': encoded({'UniqueKey': 'id', 'Properties': [
                {'Name': 'id'}]}),
            'BinDataCompressed/BinDataCompressed_ROW/ACTIVITY_CONF.json': encoded({
                'RocoDataRows': {'2': {'id': 2}}}),
            'BinLocalize/dev_CN/SEASON_CONF.json': encoded({
                'LocalizationStrings': {'1': '测试'}}),
        }
        self.zip_path = self.root / 'config.zip'
        self.write_zip(self.files)

    def write_zip(self, files):
        with ZipFile(self.zip_path, 'w') as z:
            for key, val in files.items():
                z.writestr(key, val)

    def build(self):
        with mod.Source(self.zip_path) as source:
            return mod.make_snapshot(source, game_version='1.111.0.177',
                                     build_number='229314', capture_date='2026-10-30',
                                     season_source_pak=BASE+'_3_P.pak')

    def test_zip_snapshot_counts_and_no_raw_values(self):
        d = self.build()
        self.assertEqual(d['summary']['regular_table_count'], 2)
        self.assertEqual(d['summary']['regular_record_count'], 3)
        self.assertEqual(d['summary']['schema_files'], 3)
        self.assertEqual(d['summary']['row_variant_files'], 1)
        self.assertEqual(d['summary']['localization_files'], 1)
        self.assertEqual(d['game_version'], '1.111.0.177')
        self.assertEqual(d['season_conf_source_pak_reported'], BASE+'_3_P.pak')
        s = json.dumps(d, ensure_ascii=False)
        self.assertNotIn('月涌狂想', s)
        self.assertNotIn('喵喵', s)
        self.assertNotIn('旧日', s)
        self.assertNotIn('测试', s)
        self.assertFalse(d['game_runtime_mount_order_verified'])

    def test_zip_file_sha_and_row_hash(self):
        d = self.build()
        t = next(x for x in d['tables'] if x['table'].endswith('/SEASON_CONF'))
        self.assertEqual(t['raw_file_sha256'], mod.sha256(self.files[t['path']]))
        self.assertTrue(t['rows_semantic_sha256'])
        self.assertEqual(len(t['rows_semantic_sha256']), 64)

    def test_reordered_json_has_same_semantic_hash(self):
        a = {'1': {'id': 1, 'name': '测试', 'k': 3}}
        b = {'1': {'k': 3, 'name': '测试', 'id': 1}}
        self.assertEqual(mod.canonical_hash(a), mod.canonical_hash(b))

    def test_missing_schema_is_fatal(self):
        del self.files['BinConf/PETBASE_CONF.json']
        self.write_zip(self.files)
        self.assertEqual(self.build()['summary']['fatal_issue_count'], 1)

    def test_undeclared_fields_are_warnings(self):
        self.files['BinDataCompressed/PETBASE_CONF.json'] = encoded({'RocoDataRows': {
            '1': {'id': 1, 'name': '喵喵', 'new_field': '秘密'}}})
        self.write_zip(self.files)
        d = self.build()
        self.assertEqual(d['summary']['fatal_issue_count'], 0)
        self.assertEqual(d['summary']['schema_discrepancy_tables'], 1)
        self.assertEqual(next(x for x in d['tables'] if x['table'].endswith('PETBASE_CONF'))['schema_alignment'],
                         'observed_extra_fields')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.main(['snapshot', '--source', str(self.zip_path),
                                       '--game-version', '1.111.0.177', '--build-number', '229314',
                                       '--capture-date', '2026-10-30', '--strict',
                                       '--output', str(self.root/'manifest.json')]), 0)

    def test_row_variant_separate_from_base_tables(self):
        d = self.build()
        self.assertNotIn('BinDataCompressed_ROW/ACTIVITY_CONF', [x['table'] for x in d['tables']])
        self.assertEqual(d['international_row_variants'][0]['row_count'], 1)
        self.assertFalse(any(x['table'].endswith('ACTIVITY_CONF') for x in d['tables']))

    def test_directory_equivalence_without_archive(self):
        folder = self.root/'input'/'Bin'
        for name, data in self.files.items():
            p = folder/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        with mod.Source(folder.parent) as source:
            b = mod.make_snapshot(source, game_version='1.111.0.177',
                                  build_number='229314', capture_date='2026-10-30')
        a = self.build()
        self.assertEqual(a['tables'], b['tables'])
        self.assertIsNone(b['input_zip_sha256'])

    def test_zip_path_traversal_refused(self):
        self.write_zip({'../evil.json': b'{}'})
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            mod.Source(self.zip_path)

    def test_duplicate_logical_paths_refused(self):
        self.write_zip({'Bin/BinConf/TEST.json': b'{}', 'BinConf/TEST.json': b'{}'})
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            mod.Source(self.zip_path)

    def test_invalid_version_rejected(self):
        with mod.Source(self.zip_path) as source:
            with self.assertRaises(ValueError):
                mod.make_snapshot(source, game_version='???', build_number='123', capture_date='2026-10-30')

    def test_output_cannot_overwrite_source(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mod.main(['snapshot', '--source', str(self.zip_path),
                                      '--game-version', '1.111.0.177', '--build-number', '229314',
                                      '--capture-date', '2026-10-30', '--output', str(self.zip_path)]), 2)

    def test_compare_classifies_new_modified_unchanged_and_missing(self):
        current = self.build()
        current['tables'].append({'table': 'BinDataCompressed/UNUSED',
                                  'row_count': 0, 'observed_fields': [],
                                  'rows_semantic_sha256': mod.canonical_hash({}),
                                  'row_ids_sha256': mod.canonical_hash([])})
        old = {'view_format': '1.0', 'snapshot_label': '2026-07-16',
               'pak_mount_order_verified': False,
               'summary': {'effective_rows': 3},
               'tables': [
                   {'table': 'BinDataCompressed/SEASON_CONF', 'observed_fields': ['id', 's_title_subtitle']},
                   {'table': 'BinDataCompressed/PETBASE_CONF', 'observed_fields': ['id', 'name']},
                   {'table': 'BinDataCompressed/REMOVED', 'observed_fields': ['id']},
               ]}
        old_rows = {'BinDataCompressed/SEASON_CONF': {'1': {'id': 1, 's_title_subtitle': '旧日'},
                                                   '4': {'id': 4, 's_title_subtitle': '月涌狂想'}},
                    'BinDataCompressed/PETBASE_CONF': {'1': {'id': 1, 'name': 'old pet'}},
                    'BinDataCompressed/REMOVED': {}}
        with patch.dict(sys.modules, {'effective_view': type('Stub', (), {
                'load_selected_rows': staticmethod(lambda root, entry: old_rows[entry['table']])})()}):
            report = mod.compare_to_view(current, old, self.root)
        self.assertEqual(report['summary']['unchanged'], 1)
        self.assertEqual(report['summary']['modified'], 1)
        self.assertEqual(report['summary']['added_in_new_export'], 1)
        self.assertEqual(report['summary']['missing_from_new_export_unverified'], 1)
        self.assertTrue(report['summary']['row_delta_across_all_tables_not_valid_if_missing'])
        missing = next(x for x in report['tables'] if x['table'].endswith('/REMOVED'))
        self.assertEqual(missing['classification'], 'missing_from_new_export_unverified')
        self.assertIsNone(missing['new_rows'])

    def test_unicode_terminal_captured(self):
        output = self.root/'metadata.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.main(['snapshot', '--source', str(self.zip_path),
                                      '--game-version', '1.111.0.177', '--build-number', '229314',
                                      '--capture-date', '2026-10-30', '--output', str(output)]), 0)
        self.assertTrue(output.exists())
        self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['summary']['regular_table_count'], 2)

    def test_serialize_json_is_deterministic_except_archive_sha(self):
        self.assertEqual(self.build(), self.build())


if __name__ == '__main__':
    unittest.main()
