"""Synthetic-only tests for Oct merged schema versus July Pak schema lineage."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import schema_lineage as mod

BASE = 'pakchunk4-WindowsNoEditor'
PATCH = 'pakchunk4-WindowsNoEditor_0_P'


class SchemaLineageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write_schema(BASE, 'SEASON_CONF', ['id', 'name'])
        self.write_schema(PATCH, 'SEASON_CONF', ['id', 'name', 'new_icon'])
        self.write_schema(BASE, 'NPC_CONF', ['id', 'name'])
        self.base_digest = mod.semantic_hash(self.schema(['id', 'name']))
        self.manifest = {
            'format': 'roco_merged_snapshot_v1',
            'snapshot_id': 'pc-1.111.0.177-229314',
            'input_zip_sha256': 'a'*64,
            'tables': [{
                'table': 'BinDataCompressed/SEASON_CONF',
                'path': 'BinDataCompressed/SEASON_CONF.json',
                'schema_semantic_sha256': self.base_digest,
                'observed_fields': ['id', 'name', 'new_icon'],
                'row_count': 1,
            }],
            'international_row_variants': [],
            'issues': [{
                'path': 'BinDataCompressed/SEASON_CONF.json',
                'code': 'fields_not_in_schema',
                'fields': ['new_icon'],
            }],
        }

    @staticmethod
    def schema(fields):
        return {'Name': 'any', 'Type': 'struct', 'UniqueKey': 'id',
                'Properties': [{'Name': f, 'Type': 'EString', 'Offset': i}
                               for i, f in enumerate(fields)]}

    def write_schema(self, layer, name, fields):
        folder = self.root / layer / 'Bin' / 'BinConf'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (name + '.json')).write_text(
            json.dumps(self.schema(fields), ensure_ascii=False), encoding='utf-8')

    def run_analysis(self):
        return mod.analyze(self.manifest, self.root)

    def test_historical_patch_covers_extras_missing_from_exported_base(self):
        x = self.run_analysis()
        s = x['summary']
        self.assertEqual(s['warning_files'], 1)
        self.assertEqual(s['exported_schema_same_as_base'], 1)
        self.assertEqual(s['historical_full_observed_coverage'], 1)
        self.assertEqual(s['historical_full_extra_coverage'], 1)
        self.assertEqual(s['never_seen_field_occurrences'], 0)
        warning = x['warning_tables'][0]
        self.assertEqual(warning['historical_schema_exact_matches'], [BASE])
        self.assertEqual(warning['fields_missing_from_exported_schema'], ['new_icon'])
        patch = next(c for c in warning['historical_candidates'] if c['layer'] == PATCH)
        self.assertEqual(patch['uncovered_extra_fields'], [])

    def test_never_seen_fields_are_explicitly_unexplained(self):
        self.manifest['tables'][0]['observed_fields'].append('future_only')
        self.manifest['issues'][0]['fields'].append('future_only')
        x = self.run_analysis()
        self.assertEqual(x['summary']['never_seen_field_occurrences'], 1)
        self.assertEqual(x['summary']['distinct_never_seen_field_names'], 1)
        self.assertFalse(x['warning_tables'][0]['any_historical_schema_covers_all_observed_fields'])
        self.assertEqual(x['warning_tables'][0]['extras_not_seen_in_july_historical_schemas'], ['future_only'])

    def test_absent_optional_fields_not_counted_as_schema_warnings(self):
        self.manifest['issues'] = []
        self.manifest['tables'][0]['observed_fields'] = ['id']
        x = self.run_analysis()
        self.assertEqual(x['summary']['warning_files'], 0)
        self.assertEqual(len(x['warning_tables']), 0)
        self.assertEqual(x['summary']['exported_schema_match_statistics']['matches_july_base'], 1)

    def test_row_variant_kept_separate(self):
        self.manifest['tables'] = []
        self.manifest['international_row_variants'] = [{
            'table': 'BinDataCompressed_ROW/SEASON_CONF',
            'schema_semantic_sha256': self.base_digest,
            'observed_fields': ['id', 'name', 'new_icon'],
        }]
        self.manifest['issues'][0]['path'] = 'BinDataCompressed/BinDataCompressed_ROW/SEASON_CONF.json'
        x = self.run_analysis()
        self.assertEqual(x['summary']['row_variant_warning_files'], 1)
        self.assertEqual(x['summary']['ordinary_warning_files'], 0)
        self.assertEqual(x['warning_tables'][0]['table'], 'BinDataCompressed_ROW/SEASON_CONF')

    def test_missing_historical_schema_is_not_silently_substituted(self):
        self.manifest['tables'][0]['table'] = 'BinDataCompressed/NEW_TABLE'
        self.manifest['issues'][0]['path'] = 'BinDataCompressed/NEW_TABLE.json'
        x = self.run_analysis()
        self.assertEqual(x['summary']['no_historical_schema_for_table'], 1)
        self.assertEqual(x['summary']['warning_files_with_never_seen_fields'], 1)
        self.assertEqual(x['warning_tables'][0]['historical_candidates'], [])

    def test_history_invalid_schema_rejected(self):
        p = self.root / BASE / 'Bin' / 'BinConf' / 'NPC_CONF.json'
        p.write_text('{oops', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Historical schema parse failed'):
            self.run_analysis()

    def test_bad_manifest_rejected(self):
        self.manifest['format'] = 'fake'
        with self.assertRaisesRegex(ValueError, 'Expected merged'):
            self.run_analysis()

    def test_unsafe_warning_path_rejected(self):
        self.manifest['issues'][0]['path'] = '../SEASON_CONF.json'
        with self.assertRaises(ValueError):
            self.run_analysis()

    def test_warning_must_have_observed_fields(self):
        self.manifest['tables'][0]['observed_fields'] = ['id']
        with self.assertRaisesRegex(ValueError, 'not present'):
            self.run_analysis()

    def test_duplicate_warning_field_rejected(self):
        self.manifest['issues'][0]['fields'] = ['new_icon', 'new_icon']
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.run_analysis()

    def test_symlinked_schema_rejected(self):
        p = self.root / BASE / 'Bin' / 'BinConf' / 'NPC_CONF.json'
        p.unlink()
        p.symlink_to(self.root / BASE / 'Bin' / 'BinConf' / 'SEASON_CONF.json')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_analysis()

    def test_cli_writes_two_content_free_reports(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')
        detail = self.root / 'build' / 'lineage.json'
        summary = self.root / 'build' / 'summary.json'
        with contextlib.redirect_stdout(io.StringIO()):
            rc = mod.main(['--manifest', str(manifest), '--history-root', str(self.root),
                           '--output', str(detail), '--summary', str(summary)])
        self.assertEqual(rc, 0)
        d = json.loads(detail.read_text(encoding='utf-8'))
        a = json.loads(summary.read_text(encoding='utf-8'))
        self.assertEqual(d['summary'], a['summary'])
        self.assertNotIn('隐私记录正文', json.dumps(d, ensure_ascii=False))
        self.assertEqual(d['format'], mod.FORMAT)

    def test_cli_protects_input_manifest(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps(self.manifest), encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()):
            rc = mod.main(['--manifest', str(manifest), '--history-root', str(self.root),
                           '--output', str(manifest), '--summary', str(self.root / 'out.json')])
        self.assertEqual(rc, 2)

    def test_cli_refuses_writing_inside_pak_source(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps(self.manifest), encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()):
            rc = mod.main(['--manifest', str(manifest), '--history-root', str(self.root),
                           '--output', str(self.root / BASE / 'report.json'),
                           '--summary', str(self.root / 'summary.json')])
        self.assertEqual(rc, 2)

    def test_deterministic_and_no_game_records_in_report(self):
        a, b = self.run_analysis(), self.run_analysis()
        self.assertEqual(a, b)
        self.assertNotIn('old_game_dialogue', json.dumps(a))
        self.assertEqual(a['limitations'][0], 'Historical July schemas are not proof of the correct October binary layout.')

    def test_invalid_schema_hash_rejected(self):
        self.manifest['tables'][0]['schema_semantic_sha256'] = 'broken'
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.run_analysis()

    def test_schema_match_counts_all_tables_not_only_warnings(self):
        self.manifest['tables'].append({'table': 'BinDataCompressed/NPC_CONF',
                                        'schema_semantic_sha256': self.base_digest,
                                        'observed_fields': ['id']})
        x = self.run_analysis()
        self.assertEqual(x['summary']['all_exported_table_entries'], 2)
        self.assertEqual(x['summary']['exported_schema_match_statistics']['matches_july_base'], 2)


if __name__ == '__main__':
    unittest.main()
