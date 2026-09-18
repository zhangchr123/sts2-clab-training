import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).with_name("analyze_cloud_policy_decisions.py")
SPEC = importlib.util.spec_from_file_location("decision_analysis", SOURCE)
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def line(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value) + "\n")


class DecisionAnalysisTests(unittest.TestCase):
    def fixture(self, root, chosen_score=1.0, truncated=False):
        outputs=root/'outputs';folder=outputs/'run-1';folder.mkdir(parents=True)
        audit_path=root/'run-1-audit.json'
        audit={'job':{'name':'run-1','seed':'seed-1'},'integration_passed':True,
               'report':{'run_id':'run-1','decisions':1},
               'goal':{'natural_goal_success':False,'max_act_observed':3,'max_floor_in_max_act':15}}
        write(audit_path,audit)
        state={'decision':'card_reward','context':{'act':3,'floor':14,'room_type':'Monster'}}
        line(folder/'decisions.jsonl',{'decision_id':'run-1:000','state':state,'execution':{}})
        scores=[
            {'candidate_id':'take','request':{'action':'select_card_reward'},'score':chosen_score,
             'is_skip':False,'features':{'deck_size':24,'mechanism_draw':1},
             'search_features':{'card_tag_draw':1},'missing':['rare_card_replacement_model'],
             'uncertainty':'uncalibrated'},
            {'candidate_id':'skip','request':{'action':'skip_card_reward'},'score':0.9,
             'is_skip':True,'features':{'deck_size':24},'search_features':{},'missing':[],
             'uncertainty':None},
        ]
        line(folder/'policy.jsonl',{'decision_id':'run-1:000','candidate_id':'take',
             'request':{'cmd':'action','action':'select_card_reward'},
             'scoring':{'policy_version':'model-sha','candidate_count':3 if truncated else 2,
                        'evaluated_candidate_count':2 if truncated else None,
                        'candidate_space_representation':'ordered_selection_implicit_v1' if truncated else 'explicit_v1',
                        'selection_search':{'budget':2} if truncated else None,
                        'evaluated_candidates_complete':not truncated,'scores':scores}})
        return audit_path,outputs

    def test_near_failure_low_margin_is_queued(self):
        with tempfile.TemporaryDirectory() as name:
            audit,outputs=self.fixture(Path(name))
            run=a.parse_run(audit,outputs)
            result=a.summarize([run])
            self.assertEqual(result['category_counts']['near_target_failure'],1)
            self.assertEqual(result['near_target_review_queue_total'],1)
            self.assertAlmostEqual(result['near_target_review_queue'][0]['score_margin'],0.1)
            self.assertEqual(result['by_category']['near_target_failure']['chosen_mechanism_counts'],
                             {'mechanism_draw':1})

    def test_nonmaximal_choice_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            audit,outputs=self.fixture(Path(name),chosen_score=0.8)
            with self.assertRaisesRegex(ValueError,'not score-maximal'):
                a.parse_run(audit,outputs)

    def test_truncated_ordered_selection_is_retained_and_marked(self):
        with tempfile.TemporaryDirectory() as name:
            audit,outputs=self.fixture(Path(name),truncated=True)
            run=a.parse_run(audit,outputs)
            row=run['rows'][0]
            self.assertFalse(row['candidate_space_complete'])
            self.assertEqual(row['candidate_count'],3)
            self.assertEqual(row['evaluated_candidate_count'],2)
            self.assertEqual(a.group_summary([run])['truncated_candidate_spaces'],1)

    def test_nominal_cost_guard_sentinel_is_separate_from_numeric_margin(self):
        rows=[{'score_margin':1e100,'guarded_sentinel_score':True,'candidate_space_complete':True},
              {'score_margin':0.2,'guarded_sentinel_score':False,'candidate_space_complete':True}]
        metrics=a.margin_metrics(rows)
        self.assertEqual(metrics['multi_candidate_decisions'],2)
        self.assertEqual(metrics['numeric_margin_decisions'],1)
        self.assertEqual(metrics['guarded_sentinel_decisions'],1)
        self.assertEqual(metrics['margin_mean'],0.2)

    def test_invalid_run_is_separate(self):
        audit={'integration_passed':False,'goal':{'natural_goal_success':False,
               'max_act_observed':3,'max_floor_in_max_act':15}}
        self.assertEqual(a.category(audit),'invalid')


if __name__ == '__main__':
    unittest.main(verbosity=2)
