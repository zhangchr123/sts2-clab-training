"""24 fresh Defect A10 natural training samples; fixed verified model, no fitting or deployment."""
import json,os,pathlib,sys,hashlib,time,shutil,traceback
ROOT=pathlib.Path('/home/ubuntu/sts2-linux-smoke-20260917/sts2-solver-bridge')
OUT=pathlib.Path('/home/ubuntu/sts2-cloud-sampling-20260917a')
BASE_CHECKS=pathlib.Path('/home/ubuntu/sts2-cloud-checks-20260917')
COUNT=24
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
os.environ['DOTNET_ROOT']='/home/ubuntu/.dotnet'
os.environ['PATH']='/home/ubuntu/.dotnet:'+os.environ['PATH']
from sample_runs import run_one
from audit_batch import _Audit
from boss_progress import observed_progress
from whole_run_audit import validate_whole_run_choices
from merchant_removal_audit import validate_merchant_lifecycle
from merchant_removal_value import validate_previews
from public_route_learning import validate_trace_observations,policy_input
from map_observation import validate_map_observation
from run_metadata import file_evidence
from persistent_acquisition_policy import require_parent_integration,VERSION

def write(path,data):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(path)

def require(ok,msg):
 if not ok:raise ValueError(msg)

def verify_maps(records,policies,traces):
 before=[];current={'type':'initializing'}
 for t in traces:
  before.append(current);response=t.get('response')
  if isinstance(response,dict) and (response.get('type')=='decision' or (t['request']['cmd'] in ('action','start_run') and response.get('type')=='error')):current=response
 used=[];cursor=0
 for record in records:
  packet=policies[record['decision_id']];state=record['state']
  if state.get('decision')!='map_select':
   require('map_observation' not in packet,'Map evidence on non-map decision');continue
  index=next((i for i in range(cursor,len(traces)) if before[i]==state and traces[i]['request']==record['chosen']['request']),None)
  require(index is not None and index>0,'Missing original map action')
  query=index-1;require(before[query]==state,'Map query current state differs')
  observation=packet['map_observation'];validate_map_observation(state,observation,traces[query])
  require(packet['scoring']['public_route_input']==policy_input(state,observation),'Map scoring input differs')
  used.append(query);cursor=index+1
 require(used==[i for i,t in enumerate(traces) if t['request']['cmd']=='get_map'],'Unaccounted map query')
 return {'passed':True,'map_queries':len(used)}

def prepare():
 require_parent_integration()
 require(json.loads((BASE_CHECKS/'PORTABILITY_RESULT.json').read_text())['passed'],'Scoring portability must pass')
 require(json.loads((BASE_CHECKS/'LINUX_NATURAL_RESULT.json').read_text())['passed'],'Original Linux integration must pass')
 model=BASE_CHECKS/'linux-rebound-model.json';a=json.loads(model.read_text())
 jobs=[{'name':f'defect-cloud-training-20260917a-{i:03}','seed':f'defect-cloud-training-20260917a-fresh-{i:03}'} for i in range(COUNT)]
 sources=list(ROOT.glob('*.py'))+list(ROOT.glob('*.json'))+list((ROOT/'reference_facts').rglob('*'))
 sources += list((ROOT.parent/'sts2-cli/lib').glob('*.dll'))+list((ROOT/'runtime').rglob('*.dll'))+[model,pathlib.Path(__file__),ROOT.parent/'BASE.json']
 sources += [BASE_CHECKS/'LINUX_NATURAL_RESULT.json',BASE_CHECKS/'LINUX_PROTOCOL.json',BASE_CHECKS/'PORTABILITY_RESULT.json']
 frozen=[file_evidence(p) for p in sources if p.is_file()]
 for job in jobs:require(not (ROOT/'outputs'/job['name']).exists(),'Never retry existing natural seed')
 p={'purpose':'Independent natural training-data collection using already integrated fixed 471-weight policy; no fitting, no model selection, no paired comparison', 'batch_id':'defect-cloud-training-20260917a', 'planned_games':COUNT, 'local_training_remains_paused':True, 'batch_raw_budget_bytes':8*1024**3, 'stop_when_free_below_bytes':8*1024**3, 'downstream_launch':False,'jobs':jobs,'model':file_evidence(model),'config':a['solver_requested_config'],'sampling':{'ascension':10,'epsilon':0.,'max_seconds':1200,'max_decisions':500,'selection_budget':256},'frozen_sources':frozen,'parallel_workers':1,'automatic_retry':False,'goal_claim':False}
 with (OUT/'PROTOCOL.json').open('x') as f:json.dump(p,f,indent=2)
 print(json.dumps({'prepared':True,'planned':COUNT}),flush=True)

def run():
 p=json.loads((OUT/'PROTOCOL.json').read_text());receipts=[]
 def unchanged():return all(file_evidence(x['path'])==x for x in p['frozen_sources'])
 require(unchanged(),'Frozen source drift')
 with (OUT/'STARTED.json').open('x') as f:json.dump({'pid':os.getpid(),'at':time.time(),'automatic_retry':False},f)
 def status(phase):
  write(OUT/'public-status.json',{'phase':phase,'planned':COUNT,'completed':len(receipts),'invalid':sum(not x['integration_passed'] for x in receipts),'target_successes':sum(x['integration_passed'] and x['goal']['natural_goal_success'] for x in receipts)})
 try:
  for job in p['jobs']:
   require(unchanged(),'Frozen source drift before game');require(shutil.disk_usage(ROOT).free>p['stop_when_free_below_bytes'],'Less than 8 GiB free before next game')
   require(sum(f.stat().st_size for j in p['jobs'] for f in (ROOT/'outputs'/j['name']).rglob('*') if f.is_file()) < p['batch_raw_budget_bytes'],'Raw batch reached 8 GiB budget')
   require(not (ROOT/'outputs'/job['name']).exists(),'Never retry a started seed');status('natural_training_sampling')
   report=run_one(job['name'],job['seed'],settings=p['config'],model_path=pathlib.Path(p['model']['path']),**p['sampling'])
   folder=ROOT/'outputs'/job['name'];audit=_Audit(folder);records,_=audit.run(report)
   traces=[json.loads(x) for x in (folder/'trace.jsonl').read_text().splitlines()]
   policies=[json.loads(x) for x in (folder/'policy.jsonl').read_text().splitlines()];pmap={x['decision_id']:x for x in policies}
   goal=observed_progress(traces,natural=True,expected_seed=job['seed']);issues=list(audit.issues);maps=None
   try:
    require(len(pmap)==len(policies),'Duplicate policy ID');validate_whole_run_choices(records,pmap)
    validate_trace_observations(records,pmap,traces);maps=verify_maps(records,pmap,traces)
    merchant=validate_merchant_lifecycle(traces);validate_previews(traces)
   except Exception:issues.append({'reason':'explicit_choice_or_map_or_merchant_audit','detail':traceback.format_exc()})
   manifest=json.loads((folder/'manifest.json').read_text())
   bound=manifest['provenance']['policy_source']==p['model'] and manifest['provenance']['id']==VERSION and manifest['provenance']['origin']=='natural' and not manifest['provenance']['llm_involved'] and manifest['solver_requested_config']==p['config'] and manifest['seed']==job['seed'] and manifest['ascension']==10 and manifest['character']=='Defect'
   receipt={'job':job,'report':report,'goal':goal,'issues':issues,'explicit_map_readback':maps,'policy_bound':bound,'integration_passed':bool(bound and not issues and not goal['errors'] and report['outcome'] in ('victory','defeat') and unchanged()),'not_performance_comparison':True, 'training_data_candidate':True}
   write(OUT/(job['name']+'-audit.json'),receipt);receipts.append(receipt)
  result={'passed':all(x['integration_passed'] for x in receipts),'planned':COUNT,'completed':len(receipts),'receipts':receipts,'goal_complete':False,'performance_improvement_claimed':False,'new_natural_games':len(receipts),'metric_valid_games':sum(x['integration_passed'] for x in receipts),'invalid_or_censored_games':sum(not x['integration_passed'] for x in receipts),'target_successes':sum(x['integration_passed'] and x['goal']['natural_goal_success'] for x in receipts),'downstream_launched':False,'model_updated':False}
  require(unchanged(),'Frozen source drift at batch closure')
  write(OUT/'RESULT.json',result)
  write(OUT/'SOURCE_CLOSURE.json',{'protocol':file_evidence(OUT/'PROTOCOL.json'),'result':file_evidence(OUT/'RESULT.json'),'raw_originals_retained':True,'sources':[file_evidence(f) for j in p['jobs'] for f in (ROOT/'outputs'/j['name']).rglob('*') if f.is_file()]})
  status('complete' if result['passed'] else 'failed')
 except BaseException:
  write(OUT/'RUNNER_ERROR.json',{'error':traceback.format_exc(),'automatic_retry':False});status('failed');raise

if __name__=='__main__':
 if sys.argv[1:] == ['prepare']:prepare()
 elif sys.argv[1:] == ['run']:run()
 else:raise SystemExit('Use prepare or run')
