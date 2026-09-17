import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import goal_driver as g


class GoalTests(unittest.TestCase):
    def test_unique_runner_and_invalid_id(self):
        template="OUT=pathlib.Path('/home/ubuntu/sts2-cloud-sampling-20260917a')\nseed='defect-cloud-training-20260917a-fresh-000'\n"
        a=g.make_runner(template,'defect-cloud-goal-20260917-000001',Path('/tmp/one'))
        b=g.make_runner(template,'defect-cloud-goal-20260917-000002',Path('/tmp/two'))
        self.assertNotEqual(a,b)
        self.assertNotIn('defect-cloud-training-20260917a',a)
        with self.assertRaises(ValueError):g.make_runner(template,'../../escape',Path('/tmp/one'))

    def test_goal_decision_has_no_command_or_completion_capability(self):
        p={'kind':'start','request_id':'abc'}
        d={'request_id':'abc','action':'start_next_batch','summary_zh':'继续','next_focus':'尚未更新权重'}
        self.assertEqual(g.parse(json.dumps(d),p),d)
        for bad in [dict(d,action='goal_complete'),dict(d,action='publish_and_continue'),dict(d,request_id='old'),dict(d,command='bash')]:
            with self.assertRaises(ValueError):g.parse(json.dumps(bad),p)

    def test_batch_end_authorizes_next_batch_instead_of_stop(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); batch={'id':'batch-1','path':str(root),'published':0}
            state={'current':batch,'pending':{'x':1},'closed':[]}
            snap={'snapshot_id':'snap','completed':24,'valid':24,'invalid':0,'target_successes':0,'phase':'complete'}
            pending={'kind':'review','job_id':'goal_1','snapshot':snap}
            decision={'action':'publish_and_continue','summary_zh':'24局已结束，继续','next_focus':'未更新模型'}
            with patch.object(g,'ROOT',root),patch.object(g,'STATE',root/'state.json'),patch.object(g,'configure_publisher'),patch.object(g.pub,'publish',return_value={'commit':'abcd'}):
                g.execute(state,pending,decision,{'state':'completed'})
            self.assertIsNone(state['current'])
            self.assertIn('MiniMax',state['continue_authorized'])
            self.assertEqual(len(state['closed']),1)
            self.assertFalse(state['closed'][0]['model_updated'])

    def test_interrupted_seeds_are_not_replayed(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); batch_dir=root/'batch';batch_dir.mkdir();raw=root/'raw';raw.mkdir();(raw/'started').mkdir()
            jobs=[{'name':'done'},{'name':'started'},{'name':'not_started'}]
            g.atomic(batch_dir/'PROTOCOL.json',{'jobs':jobs})
            g.atomic(batch_dir/'done-audit.json',{'integration_passed':True,'goal':{'natural_goal_success':False}})
            batch={'id':'batch-1','path':str(batch_dir)};state={'current':batch}
            with patch.object(g,'ROOT',root),patch.object(g,'STATE',root/'state.json'),patch.object(g.pub,'RAW',raw):
                g.recover_interruption(state,batch,'test reboot')
            result=g.read(batch_dir/'INTERRUPTION.json')
            self.assertEqual(result['interrupted_unknown'],['started'])
            self.assertEqual(result['never_started'],['not_started'])
            self.assertFalse(result['automatic_retry'])

    def test_model_timeout_continues_under_user_scope_without_replay(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);state={'current':None}
            with patch.object(g,'ROOT',root),patch.object(g,'STATE',root/'state.json'),patch.object(g,'launch') as launch:
                g.fallback(state,'start',None,'model_response_timeout_no_replay')
                self.assertEqual(launch.call_count,1)
                self.assertIn('User continuous-run authorization',launch.call_args.args[1])


if __name__=='__main__':unittest.main(verbosity=2)
