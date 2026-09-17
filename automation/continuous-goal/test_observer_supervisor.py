import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from supervisor import ACP, Store, build_prompt, meaningful, snapshot

HERE = Path(__file__).resolve().parent

class RuntimeTests(unittest.TestCase):
    def client(self, mode):
        c = ACP([sys.executable, str(HERE / 'fake_acp.py'), mode], str(HERE), os.environ.copy())
        self.addCleanup(c.close)
        return c

    def test_real_acp_message_shapes_and_denied_tool_requests(self):
        c = self.client('normal')
        self.assertEqual(c.connect(HERE), 'mock-session')
        result = c.prompt('try a forbidden filesystem operation', 5)
        self.assertEqual(result['text'], 'verified response')
        self.assertEqual(result['permission_requests_denied'], 1)
        self.assertEqual(result['stopReason'], 'end_turn')

    def test_session_resumption_does_not_create_replacement(self):
        c = self.client('normal')
        self.assertEqual(c.connect(HERE, 'mock-session'), 'mock-session')
        self.assertEqual(c.prompt('follow-up', 5)['text'], 'verified response')

    def test_disconnect_is_uncertain_not_completed(self):
        c = self.client('disconnect')
        c.connect(HERE)
        with self.assertRaises(ConnectionError):
            c.prompt('task', 5)

    def test_output_limit_stops_unbounded_stream(self):
        c = self.client('overflow')
        c.connect(HERE)
        with self.assertRaises(OverflowError):
            c.prompt('task', 5)
        self.assertLessEqual(len(c.text), 4000)

    def test_crash_after_claim_never_replays_and_republishes_receipt(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            a = Store(directory)
            job = {'id': 'one', 'text': 'summarize'}
            self.assertTrue(a.submit(job))
            self.assertFalse(a.submit(job))
            with self.assertRaises(ValueError):
                a.submit({'id': 'one', 'text': 'different'})
            self.assertEqual(a.claim()[0], 'one')
            a.db.close()
            b = Store(directory)
            b.recover()
            self.assertIsNone(b.claim())
            receipt = Path(directory) / 'outbox/one.json'
            self.assertEqual(json.loads(receipt.read_text())['state'], 'unknown')
            receipt.unlink()
            b.export()
            self.assertTrue(receipt.exists())
            b.db.close()

    def test_only_public_status_fields_leave_observer(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / 'status.json'
            path.write_text(json.dumps({'phase': 'running', 'completed': 2, 'password': 'PRIVATE_SENTINEL', 'error': 'secret env=PRIVATE_SENTINEL'}))
            config = {'status_files': [{'name': 'training', 'path': str(path)}]}
            first = snapshot(config)
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(first))
            path.write_text(json.dumps({'phase': 'running', 'completed': 3}))
            self.assertEqual(meaningful(first), meaningful(snapshot(config)))
            path.write_text(json.dumps({'phase': 'complete', 'completed': 3}))
            self.assertNotEqual(meaningful(first), meaningful(snapshot(config)))

    def test_declared_future_status_is_pending_but_required_missing_file_is_error(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / 'not-created-yet.json'
            future = snapshot({'status_files': [{
                'name': 'future-gated-run', 'path': str(path), 'optional_missing': True,
            }]})
            required = snapshot({'status_files': [{
                'name': 'required-run', 'path': str(path),
            }]})
            self.assertEqual(
                future['statuses'][0]['fields']['phase'],
                'not_created_waiting_gate',
            )
            self.assertNotIn('read_error', future['statuses'][0])
            self.assertEqual(required['statuses'][0]['read_error'], 'FileNotFoundError')

    def test_mailbox_repeated_id_is_safe_and_conflict_rejected(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            (Path(directory) / 'inbox').mkdir()
            cmd = [sys.executable, str(HERE / 'mailbox.py'), directory, 'submit', '--id', 'abc']
            for _ in range(2):
                self.assertEqual(subprocess.run(cmd, input='task', text=True, capture_output=True).returncode, 0)
            self.assertNotEqual(subprocess.run(cmd, input='different', text=True, capture_output=True).returncode, 0)
            self.assertEqual(json.loads((Path(directory) / 'inbox/abc.json').read_text())['text'], 'task')

    def test_manual_bypasses_older_event_but_each_class_keeps_fifo(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            store = Store(directory)
            for job_id, kind in [('event1', 'event'), ('manual1', 'manual'), ('event2', 'event'), ('manual2', 'manual')]:
                store.submit({'id': job_id, 'kind': kind, 'text': 'question'})
            for expected in ('manual1', 'manual2', 'event1', 'event2'):
                before = store.pending()
                self.assertEqual(before[0], expected)
                self.assertEqual(store.claim(), before)
            self.assertIsNone(store.pending())
            store.db.close()

    def test_mock_prompt_contains_unambiguous_public_field_semantics(self):
        public = {'processes': [], 'disks': [{'name': 'training', 'free_gib_floor': 54, 'low': False}], 'statuses': [{'name': 'run', 'fields': {'target_successes': 0}}]}
        c = self.client('semantics')
        c.connect(HERE)
        self.assertEqual(c.prompt(build_prompt('summarize', public), 5)['stopReason'], 'end_turn')

if __name__ == '__main__':
    unittest.main(verbosity=2)
