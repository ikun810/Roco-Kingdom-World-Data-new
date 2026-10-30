"""Only synthetic fixtures. Never bundle or publish user game content in CI."""
from __future__ import annotations
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import merged_snapshot
import release_candidate as rc


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode('utf-8')


class ReleaseCandidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / 'candidate.zip'
        self.content = {
            'Bin/BinConf/SEASON_CONF.json': encode({'UniqueKey': 'id', 'Properties': [{'Name': 'id'}, {'Name': 'name'}]}),
            'Bin/BinDataCompressed/SEASON_CONF.json': encode({'RocoDataRows': {str(k): {'id': k, 'name': 'season'} for k in range(1,5)}}),
            'Bin/BinConf/PETBASE_CONF.json': encode({'UniqueKey': 'id', 'Properties': [{'Name': 'id'}, {'Name': 'name'}]}),
            'Bin/BinDataCompressed/PETBASE_CONF.json': encode({'RocoDataRows': {'10': {'id': 10, 'name': '喵喵', 'new_property': True}}}),
            'Bin/BinLocalize/dev_CN/PETBASE_CONF.json': encode({'LocalizationStrings': {'1': '测试'}}),
            'Bin/BinDataCompressed/BinDataCompressed_ROW/PETBASE_CONF.json': encode({'RocoDataRows': {'11': {'id': 11, 'name': 'ROW'}}}),
        }
        self.write_zip()
        with merged_snapshot.Source(self.archive) as source:
            self.manifest = merged_snapshot.make_snapshot(source, game_version='1.111.0.177',build_number='229314',capture_date='2026-10-30')
        self.lineage = self.make_lineage()

    def write_zip(self):
        with ZipFile(self.archive, 'w') as z:
            for key, val in sorted(self.content.items()):
                z.writestr(key,val)

    def make_lineage(self):
        warn = []
        for issue in self.manifest['issues']:
            if issue['code'] != 'fields_not_in_schema':
                continue
            field = issue['fields']
            table = issue['path'].replace('.json','').replace('BinDataCompressed/BinDataCompressed_ROW/', 'BinDataCompressed_ROW/')
            warn.append({'table':table,'fields_missing_from_exported_schema':field,
                         'extras_not_seen_in_july_historical_schemas':field,
                         'historical_schema_exact_matches':['pakchunk4-WindowsNoEditor'],
                         'any_historical_schema_covers_all_observed_fields':False})
        return {'format':rc.LINEAGE_FORMAT,'snapshot_id':self.manifest['snapshot_id'],
                'snapshot_sha256_from_user_zip':self.manifest['input_zip_sha256'],
                'summary':{'warning_files':len(warn),
                           'warning_files_with_never_seen_fields':len(warn),
                           'never_seen_field_occurrences':sum(len(w['extras_not_seen_in_july_historical_schemas']) for w in warn)},
                'warning_tables':warn}

    def audit(self):
        with merged_snapshot.Source(self.archive) as source:
            return rc.audit(source,self.manifest,self.lineage)

    def test_all_content_hashes_and_s4_checked(self):
        a=self.audit()
        self.assertEqual(a['technical_integrity']['status'],'passed')
        self.assertEqual(a['input_count'],len(self.content))
        self.assertTrue(a['technical_integrity']['season_ids_1_through_4_present'])
        self.assertEqual(a['schema_review']['tables_with_fields_not_seen_in_july'],1)
        self.assertEqual(a['technical_integrity']['ordinary_row_count'],5)
        self.assertEqual(a['technical_integrity']['international_row_files'],1)

    def test_no_game_record_values_or_localizations_in_report(self):
        s=json.dumps(self.audit(),ensure_ascii=False)
        self.assertNotIn('喵喵',s)
        self.assertNotIn('测试',s)
        self.assertNotIn('\"name\": \"season\"',s)
        self.assertIn('new_property',s)

    def test_unseen_field_types_and_frequency(self):
        a=self.audit()
        pet=next(x for x in a['schema_review']['unseen_field_details'] if x['table'].endswith('PETBASE_CONF'))
        self.assertEqual(pet['new_fields'],[{'name':'new_property','rows_present':1,'value_types':{'bool':1}}])

    def test_modified_zip_blocked_by_sha256(self):
        self.content['Bin/BinDataCompressed/PETBASE_CONF.json'] = encode({'RocoDataRows':{'10':{'id':10,'name':'changed'}}})
        self.write_zip()
        with self.assertRaisesRegex(ValueError,'ZIP SHA-256'):
            self.audit()

    def test_manifest_missing_file_blocked(self):
        del self.content['Bin/BinLocalize/dev_CN/PETBASE_CONF.json']
        self.write_zip()
        self.manifest['input_zip_sha256']=rc.merged_snapshot.file_sha256(self.archive)
        self.lineage['snapshot_sha256_from_user_zip']=self.manifest['input_zip_sha256']
        with self.assertRaisesRegex(ValueError,'source ZIP file set'):
            self.audit()

    def test_schema_fingerprint_tampering_fails(self):
        a=next(x for x in self.manifest['tables'] if x['table'].endswith('PETBASE_CONF'))
        a['schema_semantic_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'schema semantic SHA-256'):
            self.audit()

    def test_lineage_snapshot_mismatch_fails(self):
        self.lineage['snapshot_id']='wrong'
        with self.assertRaisesRegex(ValueError,'lineage snapshot ID'):
            self.audit()

    def test_schema_warning_mismatch_fails(self):
        self.lineage['warning_tables'][0]['fields_missing_from_exported_schema']=['wrong']
        with self.assertRaisesRegex(ValueError,'lineage warning field list'):
            self.audit()

    def test_staged_bundle_contains_all_sources_separately_and_metadata(self):
        target=self.root/'local_review.zip'
        with merged_snapshot.Source(self.archive) as source:
            rc.pack_local(source,self.manifest,rc.audit(source,self.manifest,self.lineage),target)
        with ZipFile(target) as z:
            self.assertEqual(len(z.namelist()),len(self.content)+3)
            self.assertIn('Bin/BinDataCompressed/BinDataCompressed_ROW/PETBASE_CONF.json',z.namelist())
            self.assertEqual(z.read('Bin/BinDataCompressed/PETBASE_CONF.json'),self.content['Bin/BinDataCompressed/PETBASE_CONF.json'])
            self.assertIn(b'Private review only',z.read('README_LOCAL_REVIEW.txt'))

    def test_existing_stage_package_must_not_be_overwritten(self):
        target=self.root/'local_review.zip'
        target.write_text('original',encoding='utf-8')
        with merged_snapshot.Source(self.archive) as source:
            with self.assertRaisesRegex(ValueError,'existing release package'):
                rc.pack_local(source,self.manifest,rc.audit(source,self.manifest,self.lineage),target)
        self.assertEqual(target.read_text(encoding='utf-8'),'original')

    def test_package_source_zip_overwrite_guard(self):
        with merged_snapshot.Source(self.archive) as source:
            with self.assertRaisesRegex(ValueError,'input ZIP'):
                rc.pack_local(source,self.manifest,rc.audit(source,self.manifest,self.lineage),self.archive)

    def test_zip_traversal_is_refused(self):
        self.content['../unsafe.json']=b'{}'
        self.write_zip()
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            merged_snapshot.Source(self.archive)

    def test_invalid_s4_missing_fails(self):
        self.content['Bin/BinDataCompressed/SEASON_CONF.json']=encode({'RocoDataRows': {'1': {'id':1,'name':'first'}}})
        self.write_zip()
        with merged_snapshot.Source(self.archive) as source:
            manifest=merged_snapshot.make_snapshot(source,game_version='1.111.0.177',build_number='229314',capture_date='2026-10-30')
            lin=self.make_lineage()
            lin['snapshot_sha256_from_user_zip']=manifest['input_zip_sha256']
            with self.assertRaisesRegex(ValueError,'S1-S4'):
                rc.audit(source,manifest,lin)

    def test_unicode_cli_json_output(self):
        mp=self.root/'manifest.json';lp=self.root/'lineage.json';report=self.root/'qa.json'
        mp.write_text(json.dumps(self.manifest,ensure_ascii=False),encoding='utf-8')
        lp.write_text(json.dumps(self.lineage,ensure_ascii=False),encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rc.main(['--source',str(self.archive),'--manifest',str(mp),
                                      '--lineage',str(lp),'--report',str(report)]),0)
        self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['technical_integrity']['status'],'passed')

    def test_cli_disallows_report_overwrite_source(self):
        mp=self.root/'manifest.json';lp=self.root/'lineage.json'
        mp.write_text(json.dumps(self.manifest),encoding='utf-8')
        lp.write_text(json.dumps(self.lineage),encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rc.main(['--source',str(self.archive),'--manifest',str(mp),
                                      '--lineage',str(lp),'--report',str(self.archive)]),2)

    def test_published_report_metadata_consistency(self):
        self.assertIsNone(rc.check_published_report(self.manifest,self.lineage,self.audit()))

    def test_tampered_published_report_is_rejected(self):
        result=self.audit()
        result['schema_review']['unseen_field_details'][0]['new_fields'][0]['name']='not_that_field'
        with self.assertRaisesRegex(ValueError,'published new fields'):
            rc.check_published_report(self.manifest,self.lineage,result)

    def test_metadata_check_does_not_claim_zip_reverification(self):
        mp=self.root/'manifest.json';lp=self.root/'lineage.json';rp=self.root/'qa.json'
        mp.write_text(json.dumps(self.manifest),encoding='utf-8')
        lp.write_text(json.dumps(self.lineage),encoding='utf-8')
        rp.write_text(json.dumps(self.audit()),encoding='utf-8')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(rc.main(['--manifest',str(mp),'--lineage',str(lp),
                                      '--report',str(rp),'--check-published-report']),0)
        self.assertFalse(json.loads(out.getvalue())['zip_bytes_verified_in_this_run'])

    def test_named_record_keys_classified_without_deleting_rows(self):
        self.content['Bin/BinConf/ROGUE_CHALLENGE_GLOBAL_CONFIG.json']=encode({'UniqueKey':'id','Properties':[{'Name':'id'}]})
        self.content['Bin/BinDataCompressed/ROGUE_CHALLENGE_GLOBAL_CONFIG.json']=encode({'RocoDataRows':{'reroll_cost_base':{'id':1}}})
        self.write_zip()
        with merged_snapshot.Source(self.archive) as source:
            m=merged_snapshot.make_snapshot(source,game_version='1.111.0.177',build_number='229314',capture_date='2026-10-30')
            lin=self.make_lineage()
            lin['snapshot_sha256_from_user_zip']=m['input_zip_sha256']
            result=rc.audit(source,m,lin)
        self.assertEqual(result['technical_integrity']['id_unique_key_mismatch_tables'],1)
        self.assertEqual(result['technical_integrity']['id_unique_key_mismatch_rows'],1)
        self.assertEqual(result['technical_integrity']['id_key_anomalies'][0]['table'],'BinDataCompressed/ROGUE_CHALLENGE_GLOBAL_CONFIG')


if __name__=='__main__':
    unittest.main()
