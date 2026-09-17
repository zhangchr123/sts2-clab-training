import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cloud_automation as a


class ContractTests(unittest.TestCase):
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
