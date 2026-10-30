"""Synthetic ZIP-only tests; no third-party game records or source Pak needed."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import merged_snapshot
import merged_query as mq


class MergedQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'raw.zip'
        self.manifest = self.root / 'manifest.json'
        self.fixture = {
            'BinConf/SEASON_CONF.json': {'UniqueKey': 'id', 'Properties': [{'Name':'id'},{'Name':'s_title_subtitle'}, {'Name':'s_title'}]},
            'BinDataCompressed/SEASON_CONF.json': {'RocoDataRows': {'4': {'id':4, 's_title':'S4赛季', 's_title_subtitle':'月涌狂想'}, '1': {'id':1,'s_title_subtitle':'暗夜拾光'}}},
            'BinConf/PETBASE_CONF.json': {'UniqueKey': 'id', 'Properties': [{'Name':'id'},{'Name':'name'}]},
            'BinDataCompressed/PETBASE_CONF.json': {'RocoDataRows': {'2': {'id':2,'name':'月涌小宠'},'1': {'id':1,'name':'夜猫'}}},
            'BinConf/HIDDEN_CONF.json': {'UniqueKey': 'id', 'Properties':[{'Name':'id'},{'Name':'secret'}]},
            'BinDataCompressed/HIDDEN_CONF.json': {'RocoDataRows': {'1': {'id':1,'secret':'月涌不能搜索'}}},
            'BinDataCompressed/BinDataCompressed_ROW/SEASON_CONF.json': {'RocoDataRows': {'4': {'id':4,'s_title_subtitle':'international'}}},
            'BinLocalize/zh_Hans/SEASON_CONF.json': {'LocalizationStrings': {'1':'中文版'}},
        }
        self.write_zip()
        with merged_snapshot.Source(self.source) as src:
            manifest = merged_snapshot.make_snapshot(src,game_version='1.111.0.177',build_number='229314',capture_date='2026-10-30')
        self.manifest.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        self.doc = mq.load_manifest(self.manifest)
        self.entries = mq.index_tables(self.doc)

    def write_zip(self):
        with ZipFile(self.source,'w') as file:
            for path, data in sorted(self.fixture.items()):
                file.writestr(path, json.dumps(data,ensure_ascii=False).encode('utf-8'))

    def test_registered_tables_count_and_row_variant_excluded(self):
        self.assertEqual(len(self.entries),3)
        self.assertNotIn('BinDataCompressed_ROW/SEASON_CONF',self.entries)
        self.assertEqual(mq.tables(self.doc,self.entries,'SEASON')['total'],1)

    def test_get_full_record_and_status_flag(self):
        with mq.open_source(self.source,self.doc) as src:
            res = mq.get_record(self.doc,self.entries,src,'SEASON_CONF','4')
        self.assertEqual(res['record']['s_title_subtitle'],'月涌狂想')
        self.assertFalse(res['pak_mount_order_verified'])
        self.assertEqual(res['release_status'],'local_candidate_not_public_release')

    def test_search_by_curated_season_name(self):
        with mq.open_source(self.source,self.doc) as src:
            res = mq.match_name(self.doc,self.entries,src,'月涌',['season'])
        self.assertEqual(res['total_matches'],1)
        self.assertEqual(res['results'][0]['id'],'4')

    def test_search_domains_and_exact_match(self):
        with mq.open_source(self.source,self.doc) as src:
            res = mq.match_name(self.doc,self.entries,src,'月涌',['pet','season'])
            exact = mq.match_name(self.doc,self.entries,src,'月涌狂想',['season'],exact=True)
        self.assertEqual(res['total_matches'],2)
        self.assertEqual(exact['total_matches'],1)

    def test_uncurated_fields_not_searchable(self):
        with mq.open_source(self.source,self.doc) as src:
            self.assertEqual(mq.match_name(self.doc,self.entries,src,'不能搜索')['total_matches'],0)
            with self.assertRaisesRegex(ValueError,'curated'):
                mq.match_name(self.doc,self.entries,src,'不能搜索',table=['HIDDEN_CONF'])

    def test_invalid_limit_and_empty_query(self):
        with mq.open_source(self.source,self.doc) as src:
            with self.assertRaisesRegex(ValueError,'limit'):
                mq.match_name(self.doc,self.entries,src,'测试',limit=101)
            with self.assertRaisesRegex(ValueError,'nonblank'):
                mq.match_name(self.doc,self.entries,src,'  ')

    def test_english_casefold_and_result_cap(self):
        with mq.open_source(self.source,self.doc) as src:
            result = mq.match_name(self.doc,self.entries,src,'S4',['season'],limit=1)
        self.assertEqual(result['total_matches'],1)
        self.assertFalse(result['truncated'])

    def test_unknown_table_and_bad_table_path(self):
        with mq.open_source(self.source,self.doc) as src:
            with self.assertRaisesRegex(ValueError,'Unknown table'):
                mq.get_record(self.doc,self.entries,src,'NONEXISTENT','4')
            with self.assertRaisesRegex(ValueError,'Invalid table'):
                mq.get_record(self.doc,self.entries,src,'../secret','1')
            with self.assertRaisesRegex(ValueError,'Invalid table'):
                mq.get_record(self.doc,self.entries,src,'BinDataCompressed_ROW/SEASON_CONF','4')

    def test_reject_wrong_zip_digest_before_query(self):
        self.fixture['BinDataCompressed/PETBASE_CONF.json'] = {'RocoDataRows':{'1':{'id':1,'name':'TAMPER'}}}
        self.write_zip()
        with self.assertRaisesRegex(ValueError,'ZIP SHA-256'):
            mq.open_source(self.source,self.doc)

    def test_directory_mode_checks_per_file_hash(self):
        folder = self.root/'dir'
        for path,data in self.fixture.items():
            p=folder/path;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        with mq.open_source(folder,self.doc) as src:
            r=mq.get_record(self.doc,self.entries,src,'SEASON_CONF','4')
            self.assertEqual(r['id'],'4')
        altered=folder/'BinDataCompressed/SEASON_CONF.json'
        altered.write_text('{"RocoDataRows":{}}',encoding='utf-8')
        with mq.open_source(folder,self.doc) as src:
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                mq.get_record(self.doc,self.entries,src,'SEASON_CONF','4')

    def test_reject_manifest_duplicate_table(self):
        self.doc['tables'].append(dict(self.doc['tables'][0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            mq.index_tables(self.doc)

    def test_reject_forged_manifest_path(self):
        self.doc['tables'][0]['path']='../../private.json'
        with self.assertRaisesRegex(ValueError,'Invalid manifest table source'):
            mq.index_tables(self.doc)

    def test_reject_forged_manifest_hash(self):
        self.doc['tables'][0]['rows_semantic_sha256']='not_a_hash'
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            mq.index_tables(self.doc)

    def test_cli_get(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            rc=mq.main(['--manifest',str(self.manifest),'--source',str(self.source),'get','--table','SEASON_CONF','--id','4'])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(out.getvalue())['record']['s_title_subtitle'],'月涌狂想')

    def test_cli_tables(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            rc=mq.main(['--manifest',str(self.manifest),'--source',str(self.source),'tables','--filter','SEASON'])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(out.getvalue())['total'],1)

    def test_cli_search(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            rc=mq.main(['--manifest',str(self.manifest),'--source',str(self.source),'search','--domain','season','--query','月涌'])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(out.getvalue())['total_matches'],1)

    def test_cli_tables_without_source(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            rc=mq.main(['--manifest',str(self.manifest),'tables','--filter','SEASON'])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(out.getvalue())['total'],1)

    def test_cli_get_requires_source(self):
        err=io.StringIO()
        with contextlib.redirect_stderr(err):
            rc=mq.main(['--manifest',str(self.manifest),'get','--table','SEASON_CONF','--id','4'])
        self.assertEqual(rc,2)
        self.assertIn('--source',err.getvalue())

    def test_tables_with_source_verifies_zip(self):
        self.fixture['BinDataCompressed/PETBASE_CONF.json']={'RocoDataRows':{}}
        self.write_zip()
        err=io.StringIO()
        with contextlib.redirect_stderr(err):
            rc=mq.main(['--manifest',str(self.manifest),'--source',str(self.source),'tables'])
        self.assertEqual(rc,2)
        self.assertIn('SHA-256',err.getvalue())

    def test_missing_id_is_explicit_error(self):
        with mq.open_source(self.source,self.doc) as src:
            with self.assertRaisesRegex(ValueError,'not found'):
                mq.get_record(self.doc,self.entries,src,'SEASON_CONF','999')

    def test_no_raw_data_in_table_listing(self):
        listing=json.dumps(mq.tables(self.doc,self.entries),ensure_ascii=False)
        self.assertNotIn('月涌狂想',listing)
        self.assertNotIn('国际服',listing)


if __name__=='__main__':
    unittest.main()
