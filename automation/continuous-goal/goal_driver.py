"""Durable continuous sampling goal, with MiniMax reviews and an idle watchdog.

Sampling uses a frozen validated runtime. Goal persistence is not a claim that
weights improve: fitting/deployment remains a separate, explicitly recorded step.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import cloud_automation as pub

ROOT = Path('/home/ubuntu/sts2-cloud-goal')
TEMPLATE = ROOT / 'runner_template.py'
SPOOL = Path('/home/ubuntu/sts2-agent/spool')
STATE = ROOT / 'state.json'
GOAL = ROOT / 'GOAL.json'
EVAL_ASSESSMENT = Path('/home/ubuntu/sts2-cloud-eval/progress-aux/assessment/ASSESSMENT.json')
EVENT_EVAL_ASSESSMENT = Path('/home/ubuntu/sts2-event-effect-paired-eval-20260918/assessment/ASSESSMENT.json')
SELECTION_EVAL_ASSESSMENT = Path('/home/ubuntu/sts2-selection-effect-paired-eval-20260918/assessment/ASSESSMENT.json')
DECISION_PRIORITIES = Path('/home/ubuntu/sts2-cloud-analysis/decision-structure-20260918-v1/PRIORITIES.json')
atomic, read, require = pub.atomic, pub.read, pub.require
CHILDREN = {}


def pid_identity(pid):
    text = Path('/proc', str(pid), 'stat').read_text()
    return text.rsplit(')', 1)[1].split()[19]


def configure_publisher(batch):
    pub.BATCH = batch['id']
    pub.BASE = Path(batch['path'])
    pub.RUNTIME = ROOT


def make_runner(template, batch_id, directory):
    require(batch_id.startswith('defect-cloud-goal-20260917-') and batch_id.rsplit('-', 1)[1].isdigit(), 'Invalid allocation ID')
    old = "OUT=pathlib.Path('/home/ubuntu/sts2-cloud-sampling-20260917a')"
    require(template.count(old) == 1, 'Runner template mismatch')
    result = template.replace(old, 'OUT=pathlib.Path(' + repr(str(directory)) + ')')
    result = result.replace('defect-cloud-training-20260917a', batch_id)
    compile(result, 'run_batch.py', 'exec')
    return result


def record(state, event, **fields):
    row = {'at': time.time(), 'event': event, **fields}
    with (ROOT / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())
    atomic(STATE, state)


def launch(state, source):
    require(shutil.disk_usage(ROOT).free > 8 * 1024**3, 'Cloud disk below 8 GiB reserve')
    number = state['next_batch']
    batch_id = f'defect-cloud-goal-20260917-{number:06d}'
    directory = ROOT / 'batches' / batch_id
    require(not directory.exists(), 'Batch allocation exists; never replay an allocated batch')
    directory.mkdir(parents=True)
    state['next_batch'] = number + 1
    batch = {'id': batch_id, 'path': str(directory), 'created_at': time.time(), 'published': 0,
             'phase': 'allocated', 'launch_source': source}
    state['current'] = batch
    record(state, 'batch_allocated', batch_id=batch_id, launch_source=source)
    template = TEMPLATE.read_text(encoding='utf-8')
    script = directory / 'run_batch.py'
    script.write_text(make_runner(template, batch_id, directory), encoding='utf-8')
    prepared = subprocess.run(['/usr/bin/python3', str(script), 'prepare'], capture_output=True, timeout=120)
    (directory / 'prepare.stdout.log').write_bytes(prepared.stdout)
    (directory / 'prepare.stderr.log').write_bytes(prepared.stderr)
    require(prepared.returncode == 0, 'Batch preparation failed; allocation retained')
    # Persist the attempt BEFORE Popen. Recovery never reruns this allocation.
    batch['phase'] = 'launch_attempted'; record(state, 'launch_attempted', batch_id=batch_id)
    log = (directory / 'runner.log').open('xb')
    try:
        child = subprocess.Popen(['/usr/bin/python3', '-u', str(script), 'run'], stdout=log, stderr=subprocess.STDOUT,
                                 cwd=directory, start_new_session=True)
    finally:
        log.close()
    CHILDREN[batch_id] = child
    identity = {'owner_pid': child.pid, 'start_ticks': pid_identity(child.pid)}
    batch.update(identity, phase='running', launched_at=time.time())
    atomic(directory / 'LAUNCH.json', dict(identity, continuous_goal=True, batch_id=batch_id,
                                         launch_source=source, automatic_seed_retry=False))
    record(state, 'batch_started', batch_id=batch_id, **identity)


def recover_interruption(state, batch, reason):
    directory = Path(batch['path'])
    protocol_file = directory / 'PROTOCOL.json'
    if not protocol_file.exists():
        batch['phase'] = 'preparation_failed'
        record(state, 'preparation_failed', batch_id=batch['id'], reason=reason)
        return
    protocol = read(protocol_file)
    completed, interrupted, unstarted = [], [], []
    for job in protocol['jobs']:
        receipt = directory / (job['name'] + '-audit.json')
        if receipt.exists():
            completed.append(read(receipt))
        elif (pub.RAW / job['name']).exists():
            interrupted.append(job['name'])
        else:
            unstarted.append(job['name'])
    atomic(directory / 'INTERRUPTION.json', {'reason': reason, 'planned': 24, 'audited': len(completed),
        'interrupted_unknown': interrupted, 'never_started': unstarted, 'automatic_retry': False,
        'raw_originals_retained': True, 'goal_completed': False})
    atomic(directory / 'public-status.json', {'phase': 'failed', 'planned': 24, 'completed': len(completed),
        'invalid': sum(not r['integration_passed'] for r in completed) + len(interrupted),
        'target_successes': sum(r['integration_passed'] and r['goal']['natural_goal_success'] for r in completed)})
    batch['phase'] = 'interrupted'
    record(state, 'interruption_preserved', batch_id=batch['id'], unknown=len(interrupted), never_started=len(unstarted))


def observe(state):
    batch = state.get('current')
    if not batch:
        return None
    child = CHILDREN.get(batch['id'])
    if child is not None:
        child.poll()  # Reap the owned process, so a zombie is never mistaken for active work.
    directory = Path(batch['path'])
    launch_file = directory / 'LAUNCH.json'
    status_file = directory / 'public-status.json'
    live = launch_file.exists() and pub.owner_state(read(launch_file)) == 'live'
    if live and time.time() - batch.get('launched_at', time.time()) > 9 * 3600:
        identity = read(launch_file)
        if pub.owner_state(identity) == 'live':
            os.killpg(identity['owner_pid'], signal.SIGTERM)
        recover_interruption(state, batch, 'Declared 9-hour batch deadline exceeded')
        return None
    if not live and not (status_file.exists() and read(status_file)['phase'] in ('complete', 'failed')):
        recover_interruption(state, batch, 'Previous owner absent or allocation interrupted; no seed replay')
    if not (directory / 'PROTOCOL.json').exists() or not launch_file.exists():
        # No game owner was safely recorded. Archive allocation facts and move on to a NEW ID.
        state.setdefault('closed', []).append({'id': batch['id'], 'phase': 'allocation_failed', 'planned': 24})
        state['current'] = None
        record(state, 'allocation_closed_without_retry', batch_id=batch['id'])
        return None
    configure_publisher(batch)
    snap = pub.snapshot()
    snap['new_batch_allowed'] = True
    snap['goal_id'] = read(GOAL)['goal_id']
    snap['snapshot_id'] = hashlib.sha256(json.dumps({k:v for k,v in snap.items() if k != 'snapshot_id'}, sort_keys=True).encode()).hexdigest()[:24]
    return snap


def evaluation_context(path=EVAL_ASSESSMENT):
    if not path.exists():
        return None
    value = read(path)
    allowed = ('passed', 'evaluation_complete', 'games', 'pairs', 'control_first_boss_successes',
               'candidate_first_boss_successes', 'candidate_only_success', 'control_only_success',
               'one_sided_paired_p', 'candidate_gate_passed', 'deployment_authorized', 'next_action')
    return {key: value[key] for key in allowed if key in value}


def decision_diagnostic_context(path=DECISION_PRIORITIES):
    if not path.exists():
        return None
    value = read(path)
    priorities = sorted(value['priorities'], key=lambda item: item['rank'])
    return {
        'audited_natural_runs': value['audited_natural_runs'],
        'target_successes': value['target_successes'],
        'near_target_failures': value['near_target_failures'],
        'late_act3_review_decisions': value['late_act3_review_decisions'],
        'controlled_acquisition_priority_areas': [item['area'] for item in priorities],
        'natural_outcomes_used_for_fitting': value['interpretation']['natural_outcomes_used_for_fitting'],
    }


def ask(state, kind, snap=None, nudge=False):
    state['sequence'] += 1
    job_id = f"continuous_goal_{state['sequence']:06d}"
    goal = read(GOAL)
    context = {k:v for k,v in (snap or {}).items() if k not in ('receipts', 'protocol')}
    context['persistent_goal'] = {
        'goal_id': goal['goal_id'],
        'objective': goal['objective'],
        'completion_policy': goal['completion_policy'],
        'new_batches_allowed': goal['new_batches_allowed'],
    }
    context['closed_batches'] = len(state.get('closed', []))
    context['baseline'] = {'games': 24, 'valid': 24, 'third_act_target_successes': 0}
    evaluation = evaluation_context()
    if evaluation is not None:
        context['progress_aux_evaluation'] = evaluation
    event_evaluation = evaluation_context(EVENT_EVAL_ASSESSMENT)
    if event_evaluation is not None:
        context['event_effect_evaluation'] = event_evaluation
    selection_evaluation = evaluation_context(SELECTION_EVAL_ASSESSMENT)
    if selection_evaluation is not None:
        context['selection_effect_evaluation'] = selection_evaluation
    diagnostics = decision_diagnostic_context()
    if diagnostics is not None:
        context['decision_diagnostics'] = diagnostics
    request_id = hashlib.sha256(json.dumps({'kind':kind,'context':context,'sequence':state['sequence']}, sort_keys=True).encode()).hexdigest()[:24]
    action = 'start_next_batch' if kind == 'start' else 'publish_and_continue'
    prompt = (
        '用户最新明确指令：让你持续跑下去不要停，并设置脚本督促MiniMax一个goal。'
        '旧的“24局后停止/不新开批次”授权已被这次指令覆盖。你只有一个持久goal：' + goal['objective'] +
        '除非用户明确暂停或改目标，否则批次结束、评估结束、模型回复超时和低胜率都不是停止条件。'
        '当前可执行阶段是固定已验证模型的持续自然局采样、诊断和归档。'
        '已对254个受控分支gate做过一次33参数拟合，但候选OOF选择值0.09737低于基线0.09825、NLL 1.45688高于1.41336，已被门禁拒绝且未部署。'
        '冻结事实里的样本数和结果是当前权威快照；只能把自然局结果当描述统计，不能把样本增加或一次拟合当成胜率提升。'
        '后续需要更高信号的受控分支样本、预声明的拟合轮次和干净的成对评估。'
        '每批24个全新种子，一批结束必须接新批；保留失败和未知，不重跑同一分配。'
        '你不直接执行工具，由固定宿主适配器执行允许的批次启动和GitHub归档上传。'
        '现在需要你选择 ' + action + ' 并给出简短复盘及下一步重点。'
        'running阶段的publish_and_continue仅上传已完结局并让当前批继续；complete/failed阶段则归档后继续下一批。'
        '只有明确资源/完整性故障才选择wait，且必须说明原因；不能因旧停止限制或仅0胜而停下。'
        '只输出JSON，字段恰为 request_id、action、summary_zh、next_focus。action只允许start_next_batch、publish_and_continue、wait。'
        'request_id=' + request_id + '。summary_zh和next_focus各不超过500字；next_focus要指出采样与真正改进模型之间还缺什么。'
        + ('这是督促：上一轮没有推进，请按用户最新持续运行授权行动。' if nudge else '')
        + '冻结事实=' + json.dumps(context, ensure_ascii=False))
    job = {'id':job_id,'kind':'manual','text':prompt}
    require(len(prompt) <= 4000, 'Goal prompt exceeds mailbox budget')
    pending = {'job_id':job_id,'request_id':request_id,'kind':kind,'snapshot':snap,
               'at':time.time(),'job':job,'nudge':nudge}
    state['pending'] = pending
    record(state, 'minimax_goal_requested', job_id=job_id, kind=kind)
    atomic(SPOOL / 'inbox' / (job_id+'.json'), job)


def parse(text, pending):
    value = json.loads(text.strip())
    require(isinstance(value,dict) and set(value)=={'request_id','action','summary_zh','next_focus'}, 'Goal decision schema differs')
    require(value['request_id']==pending['request_id'], 'Stale goal decision')
    snap = pending.get('snapshot') or {}
    if pending['kind'] == 'start':
        allowed = {'start_next_batch', 'wait'}
    elif snap.get('phase') in ('complete', 'failed'):
        # A finished review both publishes the closed batch and starts the next one.
        # MiniMax has used either verb for that combined transition; both are safe
        # because execute() performs the same publish/close/continue sequence.
        allowed = {'publish_and_continue', 'start_next_batch', 'wait'}
    else:
        allowed = {'publish_and_continue', 'wait'}
    require(value['action'] in allowed, 'Goal action not allowed in this phase')
    for key in ('summary_zh','next_focus'):
        require(isinstance(value[key],str) and 1<=len(value[key])<=1000 and not pub.SECRET.search(value[key].encode()), 'Invalid goal narrative')
    return value


def close_batch(state, snap):
    batch = state['current']
    state.setdefault('closed', []).append({'id':batch['id'],'planned':24,'completed':snap['completed'],
        'valid':snap['valid'],'invalid':snap['invalid'],'target_successes':snap['target_successes'],
        'phase':snap['phase'],'model_updated':snap.get('model_updated',False),
        'model_sha256':snap.get('model_sha256'),'model_label':snap.get('model_label','legacy-unrecorded')})
    state['current'] = None
    record(state, 'batch_closed_goal_continues', batch_id=batch['id'])


def execute(state, pending, decision, reply):
    state['pending'] = None
    state['last_decision'] = decision
    record(state, 'minimax_goal_decision', job_id=pending['job_id'], action=decision['action'])
    if decision['action']=='wait':
        state['deferred'] = {'kind':pending['kind'],'snapshot':pending['snapshot'],'at':time.time(),
                             'nudge':pending['nudge']}
        return
    if pending['kind']=='start':
        launch(state, 'MiniMax '+pending['job_id'])
        return
    snap = pending['snapshot']; batch = state['current']; configure_publisher(batch)
    try:
        d = {'snapshot_id':snap['snapshot_id'],'action':'publish_snapshot','summary_zh':decision['summary_zh']+'\n下一步：'+decision['next_focus']}
        receipt = pub.publish(snap,d,reply)
        batch['published'] = snap['completed']; state['last_upload'] = receipt
        record(state,'goal_snapshot_uploaded',batch_id=batch['id'],commit=receipt['commit'])
    except Exception as exc:
        # Do not rerun model requests or stop acquisition just because upload is ambiguous.
        state['upload_needs_review'] = {'type':type(exc).__name__,'reason':str(exc)[:400],
                                        'batch_id':batch['id'],'snapshot_id':snap['snapshot_id']}
        record(state,'upload_needs_review',batch_id=batch['id'])
    if snap['phase'] in ('complete','failed'):
        close_batch(state,snap)
        state['continue_authorized'] = 'MiniMax '+pending['job_id']


def fallback(state, kind, snap, reason):
    record(state,'watchdog_fallback',kind=kind,reason=reason)
    if kind=='start':
        launch(state,'User continuous-run authorization; watchdog '+reason)
    elif snap and snap['phase'] in ('complete','failed'):
        state.setdefault('deferred_uploads',[]).append({'batch':state['current'],'snapshot':snap,'reason':reason})
        close_batch(state,snap)
        state['continue_authorized']='User continuous-run authorization; watchdog '+reason
    elif snap:
        state['current']['last_review_count']=snap['completed']


def tick(state):
    goal=read(GOAL)
    if not goal['enabled']:
        return False
    snap=observe(state)
    if state.get('pending'):
        p=state['pending'];out=SPOOL/'outbox'/(p['job_id']+'.json')
        if out.exists():
            reply=read(out)
            try:
                require(reply['state']=='completed','MiniMax reply incomplete or unknown')
                decision=parse(reply['result']['text'],p)
            except Exception as exc:
                state['pending']=None
                record(state,'minimax_reply_rejected',job_id=p['job_id'],reason=type(exc).__name__)
                state['deferred']={'kind':p['kind'],'snapshot':p['snapshot'],'at':time.time(),'nudge':p['nudge']}
            else:
                execute(state,p,decision,reply)
        elif time.time()-p['at']>=600:
            state.setdefault('unresolved_model_jobs',[]).append(p['job_id']);state['pending']=None
            fallback(state,p['kind'],p['snapshot'],'model_response_timeout_no_replay')
        else:
            # Repair a crash between durable goal intent and inbox publication, without a new ID.
            path=SPOOL/'inbox'/(p['job_id']+'.json')
            if not path.exists():atomic(path,p['job'])
    elif state.get('deferred'):
        d=state['deferred']
        if time.time()-d['at']>=300:
            state.pop('deferred')
            if d['nudge']:fallback(state,d['kind'],d['snapshot'],'two_nonprogress_goal_rounds')
            else:ask(state,d['kind'],d['snapshot'],nudge=True)
    elif not state.get('current'):
        source=state.pop('continue_authorized',None)
        if source:launch(state,source)
        else:ask(state,'start')
    elif snap:
        batch=state['current'];last=max(batch.get('published',0),batch.get('last_review_count',0))
        due=snap['phase'] in ('complete','failed') or snap['completed']-last>=8
        if due:ask(state,'review',snap)
    current=state.get('current')
    progress={}
    if current and (Path(current['path'])/'public-status.json').exists():progress=read(Path(current['path'])/'public-status.json')
    atomic(ROOT/'public-status.json',{'phase':'continuous_goal_active','status':progress.get('phase','planning'),
        'planned':24,'completed':progress.get('completed',0),'invalid':progress.get('invalid',0),
        'target_successes':progress.get('target_successes',0),'total':len(state.get('closed',[])),
        'step':state['sequence'],'updated_unix':time.time()})
    atomic(STATE,state)
    return True


def main():
    import fcntl
    ROOT.mkdir(exist_ok=True)
    lock=(ROOT/'goal.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=read(STATE) if STATE.exists() else {'next_batch':1,'sequence':0,'closed':[],'current':None,'pending':None}
    record(state,'goal_driver_online',pid=os.getpid())
    while True:
        try:
            if not tick(state):return
        except Exception as exc:
            record(state,'goal_cycle_error',error_type=type(exc).__name__,reason=str(exc)[:500])
            atomic(ROOT/'public-status.json',{'phase':'continuous_goal_active','status':'resource_or_integrity_blocked',
                'completed':0,'planned':24,'updated_unix':time.time()})
            time.sleep(300)
        time.sleep(30)


if __name__=='__main__':main()
