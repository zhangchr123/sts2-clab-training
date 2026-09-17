import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import goal_driver as g


class GoalTests(unittest.TestCase):
    def test_complete_review_accepts_start_next_batch(self):
        pending = {
            'kind': 'review',
            'request_id': 'req-complete',
            'snapshot': {'phase': 'complete'},
        }
        decision = {
            'request_id': 'req-complete',
            'action': 'start_next_batch',
            'summary_zh': '已完成本批。',
            'next_focus': '归档后继续新批次。',
        }
        self.assertEqual(g.parse(json.dumps(decision, ensure_ascii=False), pending), decision)

    def test_running_review_rejects_start_next_batch(self):
        pending = {
            'kind': 'review',
            'request_id': 'req-running',
            'snapshot': {'phase': 'running'},
        }
        decision = {
            'request_id': 'req-running',
            'action': 'start_next_batch',
            'summary_zh': '本批仍在运行。',
            'next_focus': '继续当前批次。',
        }
        with self.assertRaisesRegex(ValueError, 'Goal action not allowed'):
            g.parse(json.dumps(decision, ensure_ascii=False), pending)

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
            snap={'snapshot_id':'snap','completed':24,'valid':24,'invalid':0,'target_successes':0,
                  'phase':'complete','model_updated':True,'model_sha256':'abc','model_label':'candidate'}
            pending={'kind':'review','job_id':'goal_1','snapshot':snap}
            decision={'action':'publish_and_continue','summary_zh':'24局已结束，继续','next_focus':'未更新模型'}
            with patch.object(g,'ROOT',root),patch.object(g,'STATE',root/'state.json'),patch.object(g,'configure_publisher'),patch.object(g.pub,'publish',return_value={'commit':'abcd'}):
                g.execute(state,pending,decision,{'state':'completed'})
            self.assertIsNone(state['current'])
            self.assertIn('MiniMax',state['continue_authorized'])
            self.assertEqual(len(state['closed']),1)
            self.assertTrue(state['closed'][0]['model_updated'])
            self.assertEqual(state['closed'][0]['model_sha256'],'abc')
            self.assertEqual(state['closed'][0]['model_label'],'candidate')

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

    def test_only_verified_evaluation_summary_enters_goal_context(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'ASSESSMENT.json'
            path.write_text(json.dumps({
                'passed':True,'evaluation_complete':True,'games':120,'pairs':60,
                'control_first_boss_successes':2,'candidate_first_boss_successes':7,
                'candidate_only_success':6,'control_only_success':1,'one_sided_paired_p':0.0546875,
                'candidate_gate_passed':False,'deployment_authorized':False,
                'next_action':'candidate_rejected_keep_control','raw_files_verified':999,
                'reason':'must not leak unbounded verifier text'}),encoding='utf-8')
            context=g.evaluation_context(path)
            self.assertFalse(context['candidate_gate_passed'])
            self.assertFalse(context['deployment_authorized'])
            self.assertNotIn('raw_files_verified',context)
            self.assertNotIn('reason',context)

    def test_decision_diagnostics_only_expose_bounded_priority_context(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'PRIORITIES.json'
            path.write_text(json.dumps({
                'audited_natural_runs':87,'target_successes':1,'near_target_failures':10,
                'late_act3_review_decisions':27,
                'priorities':[{'rank':2,'area':'ordered_selection','large_detail':'omit'},
                              {'rank':1,'area':'events','large_detail':'omit'}],
                'interpretation':{'natural_outcomes_used_for_fitting':False},
                'near_target_review_queue':['must','not','enter','goal']}),encoding='utf-8')
            context=g.decision_diagnostic_context(path)
            self.assertEqual(context['controlled_acquisition_priority_areas'],['events','ordered_selection'])
            self.assertFalse(context['natural_outcomes_used_for_fitting'])
            self.assertNotIn('near_target_review_queue',context)

    def test_combined_dynamic_context_stays_within_mailbox_budget(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);spool=root/'spool';(spool/'inbox').mkdir(parents=True)
            state={'sequence':0,'closed':[],'current':None}
            snap={'phase':'complete','completed':24,'valid':24,'invalid':0,
                  'target_successes':1,'model_label':'fixture','model_sha256':'a'*64}
            evaluation={'passed':True,'evaluation_complete':True,'games':120,'pairs':60,
                        'candidate_gate_passed':False,'deployment_authorized':False}
            diagnostics={'audited_natural_runs':87,'target_successes':1,'near_target_failures':10,
                         'late_act3_review_decisions':27,
                         'controlled_acquisition_priority_areas':['events','selection','route','reward','rest'],
                         'natural_outcomes_used_for_fitting':False}
            goal_path=root/'GOAL.json'
            goal_path.write_text(json.dumps({
                'goal_id':'fixture-goal','objective':'持续训练直到稳定通过第三幕首个Boss',
                'completion_policy':'continue until the user explicitly pauses',
                'new_batches_allowed':True}),encoding='utf-8')
            with patch.object(g,'ROOT',root),patch.object(g,'STATE',root/'state.json'),\
                 patch.object(g,'SPOOL',spool),patch.object(g,'GOAL',goal_path),\
                 patch.object(g,'evaluation_context',return_value=evaluation),\
                 patch.object(g,'decision_diagnostic_context',return_value=diagnostics):
                g.ask(state,'review',snap)
            self.assertLessEqual(len(state['pending']['job']['text']),4000)


if __name__=='__main__':unittest.main(verbosity=2)
