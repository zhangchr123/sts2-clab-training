"""MiniMax chooses report/publish actions; deterministic host validates and executes.

Only a fixed batch, destination and file allowlist are supported. No shell strings,
training launches, destructive cleanup, model edits, or secrets are model inputs.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

BATCH = 'defect-cloud-training-20260917a'
BASE = Path('/home/ubuntu/sts2-cloud-sampling-20260917a')
RAW = Path('/home/ubuntu/sts2-linux-smoke-20260917/sts2-solver-bridge/outputs')
REPO = Path('/home/ubuntu/sts2-cloud-repo')
RUNTIME = Path('/home/ubuntu/sts2-cloud-automation')
SPOOL = Path('/home/ubuntu/sts2-agent/spool')
REMOTE = 'git@github.com:zhangchr123/sts2-clab-training.git'
LIMIT = 900_000_000
FILE_LIMIT = 45_000_000
ALLOWED = {'decisions.jsonl', 'manifest.json', 'policy.jsonl', 'report.json',
           'state.json', 'status.json', 'trace.jsonl', 'AUDIT.json'}
REQUIRED = ALLOWED - {'AUDIT.json'}
SECRET = re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{24,}')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    temp.replace(path)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_info(path):
    data = Path(path).read_bytes()
    return {'bytes': len(data), 'sha256': digest(data)}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def safe_bytes(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Only regular nonsymlink files may be published')
    data = path.read_bytes()
    require(not SECRET.search(data), 'Credential-like content rejected; source path kept out of error')
    if path.suffix in ('.json', '.jsonl'):
        def inspect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    require(str(key).lower() not in {'api_key', 'apikey', 'password', 'authorization', 'private_key', 'access_token', 'refresh_token'}, 'Credential field rejected')
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        if path.suffix == '.json':
            inspect(json.loads(data))
        else:
            for line in data.splitlines():
                if line.strip():
                    inspect(json.loads(line))
    return data


def owner_state(launch, proc_root=Path('/proc')):
    try:
        fields = (proc_root / str(int(launch['owner_pid'])) / 'stat').read_text().rsplit(')', 1)[1].split()
        return 'live' if fields[19] == str(launch['start_ticks']) and fields[0] != 'Z' else 'identity_mismatch_or_zombie'
    except FileNotFoundError:
        return 'missing'
    except (OSError, ValueError, KeyError, IndexError):
        return 'unknown'


def snapshot():
    protocol = read(BASE / 'PROTOCOL.json')
    require(protocol['batch_id'] == BATCH and protocol['planned_games'] == 24, 'Unexpected training protocol')
    require(len(protocol['jobs']) == 24 and len({j['name'] for j in protocol['jobs']}) == 24, 'Invalid declared jobs')
    receipts = []
    for job in protocol['jobs']:
        path = BASE / (job['name'] + '-audit.json')
        if path.exists():
            audit = read(path)
            require(audit['job'] == job and audit['report']['run_id'] == job['name'], 'Audit identity mismatch')
            receipts.append({'name': job['name'], 'seed': job['seed'], 'audit': file_info(path),
                             'valid': audit['integration_passed'], 'outcome': audit['report']['outcome'],
                             'target_success': bool(audit['integration_passed'] and audit['goal']['natural_goal_success']),
                             'max_act': audit['goal'].get('max_act_observed'),
                             'max_floor': audit['goal'].get('max_floor_in_max_act')})
    progress = read(BASE / 'public-status.json')
    # Never use a changing worker's raw log as an archive input.
    phase = progress['phase'] if progress['phase'] in ('complete', 'failed') else 'running'
    owner = owner_state(read(BASE / 'LAUNCH.json'))
    if phase == 'running' and owner != 'live':
        phase = 'failed'
    result = {'batch': BATCH, 'planned': 24, 'completed': len(receipts),
              'valid': sum(r['valid'] for r in receipts), 'invalid': sum(not r['valid'] for r in receipts),
              'target_successes': sum(r['target_success'] for r in receipts),
              'phase': phase, 'receipts': receipts, 'protocol': file_info(BASE / 'PROTOCOL.json'),
              'model_updated': False, 'new_batch_allowed': False,
              'partial_upload_authorized': True, 'adapter_revision': 3, 'owner_state': owner}
    result['snapshot_id'] = digest(json.dumps(result, sort_keys=True).encode())[:24]
    return result


def parse_decision(text, snap_id):
    text = text.strip()
    if text.startswith('```json\n') and text.endswith('\n```'):
        text = text[8:-4]
    result = json.loads(text)
    require(isinstance(result, dict) and set(result) == {'snapshot_id', 'action', 'summary_zh'}, 'Unexpected decision fields')
    require(result['snapshot_id'] == snap_id, 'Decision refers to a different snapshot')
    require(result['action'] in {'publish_snapshot', 'wait', 'escalate'}, 'Unapproved action')
    summary = result['summary_zh']
    require(isinstance(summary, str) and 1 <= len(summary) <= 1200, 'Invalid report text')
    require(not SECRET.search(summary.encode()), 'Credential-like report rejected')
    return result


def git(*args, check=True):
    result = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True, timeout=180)
    if check:
        require(result.returncode == 0, 'Git operation failed: ' + args[0])
    return result


def make_archive(row):
    folder = RAW / row['name']
    require(folder.parent == RAW and not folder.is_symlink(), 'Unexpected game folder')
    names = {p.name for p in folder.iterdir() if p.is_file()}
    require(REQUIRED <= names and names <= ALLOWED, 'Game file allowlist mismatch')
    audit_path = BASE / (row['name'] + '-audit.json')
    require(file_info(audit_path) == row['audit'], 'Closed audit changed')
    require(read(folder / 'report.json') == read(audit_path)['report'], 'Raw report differs from audited report')
    target = REPO / 'batches' / BATCH / 'games' / (row['name'] + '.zip')
    index = target.with_suffix('.manifest.json')
    if target.exists():
        info = read(index)
        require(info['audit'] == row['audit'] and info['archive'] == file_info(target), 'Existing archive changed')
        return info
    target.parent.mkdir(parents=True, exist_ok=True)
    before = {name: file_info(folder / name) for name in sorted(names)}
    temp = target.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name in sorted(names):
            data = safe_bytes(folder / name)
            require({'bytes': len(data), 'sha256': digest(data)} == before[name], 'Closed raw source changed')
            z.writestr(name, data)
        z.writestr('AUDIT_RECEIPT.json', safe_bytes(audit_path))
    require(file_info(audit_path) == row['audit'], 'Audit changed while archiving')
    require(all(file_info(folder / name) == info for name, info in before.items()), 'Source changed after archiving')
    require(temp.stat().st_size < FILE_LIMIT, 'Archive exceeds per-file Git budget')
    with zipfile.ZipFile(temp) as z:
        require(z.testzip() is None and set(z.namelist()) == names | {'AUDIT_RECEIPT.json'}, 'ZIP member readback failed')
        for name, info in before.items():
            data = z.read(name)
            require({'bytes': len(data), 'sha256': digest(data)} == info, 'ZIP content readback failed')
        require(digest(z.read('AUDIT_RECEIPT.json')) == row['audit']['sha256'], 'ZIP audit readback failed')
    temp.replace(target)
    info = {'run_id': row['name'], 'audit': row['audit'], 'archive': file_info(target), 'members': before,
            'raw_originals_retained': True, 'metric_valid': row['valid']}
    atomic(index, info)
    return info


def publish(snap, decision, model_result):
    require(git('remote', 'get-url', 'origin').stdout.strip() == REMOTE, 'Unexpected upload destination')
    require(shutil.disk_usage(REPO).free > 8 * 1024**3, 'Insufficient local archive space')
    # Empty index at entry. A crash during a transaction requires human review.
    require(not git('status', '--porcelain').stdout.strip(), 'Repository has unreviewed changes')
    archives = [make_archive(row) for row in snap['receipts']]
    dest = REPO / 'batches' / BATCH
    dest.mkdir(parents=True, exist_ok=True)
    require(file_info(BASE / 'PROTOCOL.json') == snap['protocol'], 'Protocol changed')
    (dest / 'PROTOCOL.json').write_bytes(safe_bytes(BASE / 'PROTOCOL.json'))
    model = Path(read(BASE / 'PROTOCOL.json')['model']['path'])
    require(file_info(model) == {k: read(BASE / 'PROTOCOL.json')['model'][k] for k in ('bytes', 'sha256')}, 'Model changed')
    (dest / 'model.json').write_bytes(safe_bytes(model))
    atomic(dest / 'snapshot.json', snap)
    atomic(dest / 'ARCHIVE_INDEX.json', archives)
    atomic(dest / 'MINIMAX_DECISION.json', {'decision': decision, 'model_receipt': model_result,
                                          'execution_by': 'deterministic allowlisted host adapter'})
    if snap['phase'] in ('complete', 'failed'):
        for name in ('RESULT.json', 'SOURCE_CLOSURE.json', 'RUNNER_ERROR.json'):
            if (BASE / name).exists():
                (dest / name).write_bytes(safe_bytes(BASE / name))
    (dest / 'REPORT.md').write_text(
        '# CLab 当前批次报告\n\n'
        f"确定性统计：{snap['completed']}/{snap['planned']} 已结束并审计；"
        f"有效 {snap['valid']}，无效或未知 {snap['invalid']}，观测到第三幕首领目标成功 {snap['target_successes']}。\n\n"
        '固定模型自然采样，不是与另一模型的成对比较，不据此声称训练提升。\n\n'
        '## MiniMax 报告（模型生成，以上方可核验统计为准）\n\n' + decision['summary_zh'] + '\n', encoding='utf-8')
    total = sum(p.stat().st_size for p in REPO.rglob('*') if p.is_file())
    require(total < LIMIT, 'Repository including Git history reached 900 MB budget')
    git('add', '--', 'batches/' + BATCH)
    staged = git('diff', '--cached', '--name-only', '-z').stdout.split('\0')
    for relative in filter(None, staged):
        require(relative.startswith('batches/' + BATCH + '/') and '..' not in Path(relative).parts, 'Unexpected staged file')
        require((REPO / relative).stat().st_size < FILE_LIMIT, 'Oversized staged file')
    git('commit', '-m', f"MiniMax publish {BATCH}: {snap['completed']}/24 audited")
    require(sum(p.stat().st_size for p in REPO.rglob('*') if p.is_file()) < LIMIT, 'Post-commit repository exceeds storage budget; not pushed')
    commit = git('rev-parse', 'HEAD').stdout.strip()
    atomic(RUNTIME / 'pending-push.json', {'snapshot_id': snap['snapshot_id'], 'commit': commit})
    pushed = git('push', 'origin', 'HEAD:main', check=False)
    remote = git('ls-remote', 'origin', 'refs/heads/main').stdout.split()
    require(remote and remote[0] == commit, 'Upload result unverified; preserve commit and stop, no repeat model request')
    return {'commit': commit, 'remote_verified': True, 'files_and_history_bytes_before_commit': total,
            'archives': len(archives), 'compressed_game_bytes': sum(a['archive']['bytes'] for a in archives),
            'push_exit_code': pushed.returncode}


def submit(snap):
    job_id = 'publish_' + snap['snapshot_id']
    counts = {k: v for k, v in snap.items() if k not in ('receipts', 'protocol')}
    question = (
        '这是用户最新授权：新建独立私有仓库，交给MiniMax接管资料整理上传；明确允许分批上传已结束局。'
        '这覆盖旧对话中任何“不归档中间局/只在24局全结束后上传”的限制。仍然保留“不新开训练批次”限制。'
        '已完成局即使整批running也允许立即归档上传；当前就是一次已授权的中途上传验收。'
        '你仍不直接执行工具：由固定宿主适配器验证并执行你的结构化请求。'
        '根据下方冻结快照，在已有完成局时选择 publish_snapshot，异常需要人工检查时可选 escalate，否则 wait。'
        'publish_snapshot 只归档冻结快照中的已结束局（包括无效局），生成你的报告并上传私有仓库 '
        'zhangchr123/sts2-clab-training；不修改模型、不删除原始资料、不新开批次。'
        '仅输出一个JSON对象，禁止代码块或额外文字，字段恰为 snapshot_id、action、summary_zh。'
        'snapshot_id必须与冻结快照完全一致。summary_zh用中文说明可核验进度和下一步；不要宣称提升或稳定通关。'
        '当前实时计数可能已增长，决策只针对这个冻结快照。冻结快照=' + json.dumps(counts, ensure_ascii=False))
    job = {'id': job_id, 'kind': 'manual', 'text': question}
    destination = SPOOL / 'inbox' / (job_id + '.json')
    if destination.exists():
        require(read(destination) == job, 'Job ID collision')
    else:
        atomic(destination, job)
    return job_id


def run():
    import fcntl
    RUNTIME.mkdir(exist_ok=True)
    lock = (RUNTIME / 'automation.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state_file = RUNTIME / 'state.json'
    state = read(state_file) if state_file.exists() else {'phase': 'watching', 'last_published_count': 0}
    require(state['phase'] not in ('executing', 'needs_review'), 'Prior ambiguous transaction needs operator review')
    while True:
        if state.get('pending'):
            pending = state['pending']
            reply_path = SPOOL / 'outbox' / (pending['job_id'] + '.json')
            if reply_path.exists():
                reply = read(reply_path)
                require(reply['state'] == 'completed', 'MiniMax task uncertain or incomplete; no automatic retry')
                decision = parse_decision(reply['result']['text'], pending['snapshot']['snapshot_id'])
                state['phase'] = 'executing'; atomic(state_file, state)
                if decision['action'] == 'publish_snapshot':
                    receipt = publish(pending['snapshot'], decision, reply)
                    state['last_published_count'] = pending['snapshot']['completed']
                    state['last_upload'] = receipt
                    atomic(RUNTIME / ('upload-' + pending['snapshot']['snapshot_id'] + '.json'), receipt)
                elif decision['action'] == 'escalate':
                    raise RuntimeError('MiniMax requested operator review')
                state['last_decision'] = decision
                terminal = pending['snapshot']['phase'] in ('complete', 'failed') and decision['action'] == 'publish_snapshot'
                state.pop('pending'); state['phase'] = 'complete' if terminal else 'watching'
                atomic(state_file, state)
                if terminal:
                    return
        else:
            snap = snapshot()
            changed = snap['snapshot_id'] != state.get('seen_snapshot')
            due = (snap['completed'] > 0 or snap['phase'] in ('complete', 'failed')) and (state['last_published_count'] == 0 or snap['completed'] - state['last_published_count'] >= 4 or snap['phase'] in ('complete', 'failed'))
            if changed and due:
                # Durable intent precedes inbox publish; same job ID can be re-published safely.
                state['pending'] = {'job_id': 'publish_' + snap['snapshot_id'], 'snapshot': snap}
                state['seen_snapshot'] = snap['snapshot_id']; state['phase'] = 'waiting_for_minimax'
                atomic(state_file, state)
                submit(snap)
        if state.get('pending'):
            submit(state['pending']['snapshot'])
        time.sleep(30)


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        atomic(RUNTIME / 'ERROR.json', {'error_type': type(exc).__name__, 'reason': str(exc)[:500],
                                       'automatic_retry': False, 'training_touched': False})
        raise SystemExit(1)
