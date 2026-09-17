import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cloud_automation as a


class ContractTests(unittest.TestCase):
    def test_known_model_lineage(self):
        self.assertEqual(a.model_lineage(a.BASELINE_MODEL_SHA256), 'linux-validated-baseline-471')
        self.assertEqual(a.model_lineage(a.PROGRESS_AUX_MODEL_SHA256), 'progress-aux-candidate-471')
        self.assertTrue(a.model_lineage('a' * 64).startswith('nonbaseline-unregistered-'))

    def test_snapshot_records_frozen_model_lineage(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);model=base/'model.json';model.write_text('{}')
            info={'path':str(model),**a.file_info(model)}
            jobs=[{'name':f'job-{i:02d}','seed':f'seed-{i:02d}'} for i in range(24)]
            (base/'PROTOCOL.json').write_text(json.dumps({'batch_id':'lineage-batch','planned_games':24,
                                                          'jobs':jobs,'model':info}))
            (base/'public-status.json').write_text(json.dumps({'phase':'complete'}))
            (base/'LAUNCH.json').write_text(json.dumps({'owner_pid':99999999,'start_ticks':'1'}))
            audit={'job':jobs[0],'report':{'run_id':jobs[0]['name'],'outcome':'defeat'},
                   'integration_passed':True,'goal':{'natural_goal_success':False}}
            (base/(jobs[0]['name']+'-audit.json')).write_text(json.dumps(audit))
            with patch.multiple(a,BASE=base,BATCH='lineage-batch',BASELINE_MODEL_SHA256=info['sha256'],
                                KNOWN_MODEL_LABELS={info['sha256']:'fixture-baseline'}):
                snap=a.snapshot()
            self.assertEqual(snap['model_sha256'],info['sha256'])
            self.assertEqual(snap['model_label'],'fixture-baseline')
            self.assertFalse(snap['model_updated'])

    def test_owner_identity_reuse_and_missing_process(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); folder = root / '123'; folder.mkdir()
            launch = {'owner_pid': 123, 'start_ticks': '456'}
            fields = ['S'] + ['0'] * 18 + ['456']
            stat = folder / 'stat'
            stat.write_text('123 (name with spaces) ' + ' '.join(fields))
            self.assertEqual(a.owner_state(launch, root), 'live')
            fields[19] = '457'; stat.write_text('123 (name with spaces) ' + ' '.join(fields))
            self.assertEqual(a.owner_state(launch, root), 'identity_mismatch_or_zombie')
            stat.unlink()
            self.assertEqual(a.owner_state(launch, root), 'missing')

    def test_decision_rejects_unapproved_actions_and_extra_parameters(self):
        good = {'snapshot_id': 'abc', 'action': 'publish_snapshot', 'summary_zh': '仅归档完成局。'}
        self.assertEqual(a.parse_decision(json.dumps(good), 'abc'), good)
        for bad in [dict(good, action='run_shell'), dict(good, command='git push other'),
                    dict(good, snapshot_id='old'), dict(good, summary_zh=''), {'action': 'publish_snapshot'}]:
            with self.assertRaises(ValueError):
                a.parse_decision(json.dumps(bad), 'abc')

    def test_credentials_rejected_in_nested_json_and_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            for suffix in ('.json', '.jsonl'):
                p = Path(d) / ('data' + suffix)
                p.write_text(json.dumps({'nested': [{'password': 'not-a-real-secret'}]}))
                with self.assertRaises(ValueError):
                    a.safe_bytes(p)

    def test_archive_roundtrip_and_changed_audit_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); raw = root / 'raw'; base = root / 'base'; repo = root / 'repo'
            folder = raw / 'test'; folder.mkdir(parents=True); base.mkdir(); repo.mkdir()
            report = {'run_id': 'test', 'outcome': 'defeat'}
            for name in a.REQUIRED:
                obj = report if name == 'report.json' else {'sample': name}
                (folder / name).write_text(json.dumps(obj) + '\n')
            audit = base / 'test-audit.json'; audit.write_text(json.dumps({'report': report}))
            row = {'name': 'test', 'audit': a.file_info(audit), 'valid': True}
            with patch.multiple(a, RAW=raw, BASE=base, REPO=repo):
                first = a.make_archive(row)
                self.assertEqual(a.make_archive(row), first)
                self.assertTrue(first['raw_originals_retained'])
                self.assertEqual(len(first['members']), len(a.REQUIRED))
                audit.write_text(json.dumps({'report': {'changed': True}}))
                with self.assertRaises(ValueError):
                    a.make_archive(row)

    def test_archive_rejects_unapproved_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); raw = root / 'raw'; folder = raw / 'test'; folder.mkdir(parents=True)
            for name in a.REQUIRED | {'.credentials.yaml'}:
                (folder / name).write_text('{}')
            with patch.object(a, 'RAW', raw), self.assertRaises(ValueError):
                a.make_archive({'name': 'test'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
