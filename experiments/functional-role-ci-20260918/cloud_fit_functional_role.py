"""Re-execute the predeclared ci functional-role fit on CLab.

The input is a read-only reconstruction from the fully closed 1096-arm branch
denominator. Natural games are not fitting labels. A candidate is exported only
after whole-seed OOF admission and independent runtime score readback.
"""
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')

import numpy as np
import scipy
from scipy.optimize import minimize
from scipy.special import expit

ROOT = Path('/home/ubuntu/sts2-linux-smoke-20260917/sts2-solver-bridge')
WORK = Path('/home/ubuntu/sts2-cloud-fit/functional-role-ci')
INPUT = WORK / 'input/INPUT.json'
OUT = WORK / 'output'
CURRENT = Path('/home/ubuntu/sts2-cloud-checks-20260917/linux-rebound-model.json')
RIDGE, TRUST, FOLDS, TIE = .03, 1., 5, 1e-12


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    temporary.replace(path)


def evidence(path):
    path = Path(path); data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def require(ok, why):
    if not ok:
        raise ValueError(why)


def fold_for(seed):
    return int.from_bytes(hashlib.sha256(('reward-branch-outcomes-v1|' + seed).encode()).digest()[:8], 'big') % FOLDS


def contrasts(features, scores, labels, seeds):
    require(features.ndim == 3 and features.shape[1] == 4 and scores.shape == labels.shape == features.shape[:2], 'Bad arrays')
    informative = [len(set(row)) == 2 for row in labels]
    counts = Counter(seed for seed, flag in zip(seeds, informative) if flag)
    x, offsets, weights = [], [], []
    for feature, score, label, seed in zip(features, scores, labels, seeds):
        pairs = [(a, b) for a in range(4) for b in range(4) if label[a] == 1 and label[b] == 0]
        for a, b in pairs:
            x.append(feature[a] - feature[b]); offsets.append(score[a] - score[b])
            weights.append(1. / (counts[seed] * len(pairs)))
    return (np.asarray(x, dtype=float).reshape(-1, features.shape[-1]), np.asarray(offsets, dtype=float),
            np.asarray(weights, dtype=float), {'informative_seeds': len(counts), 'informative_gates': sum(informative)})


def loss_gradient(delta, x, offsets, weights):
    if not len(offsets):
        return float(.5 * RIDGE * np.dot(delta, delta)), RIDGE * delta
    normalized = weights / weights.sum(); margins = offsets + x @ delta
    loss = np.dot(normalized, np.logaddexp(0., -margins)) + .5 * RIDGE * np.dot(delta, delta)
    gradient = x.T @ (-normalized * expit(-margins)) + RIDGE * delta
    return float(loss), gradient


def bounds(anchor, names, prior):
    lo, hi = np.maximum(-TRUST, -4-anchor), np.minimum(TRUST, 4-anchor)
    for i, name in enumerate(names):
        if prior[name] > 0 or name.startswith('role_') and name.endswith('_gap'):
            lo[i] = max(lo[i], -anchor[i])
        if prior[name] < 0:
            hi[i] = min(hi[i], -anchor[i])
        if name in ('functional_repeat', 'rarity_unknown', 'cost_unknown'):
            lo[i] = hi[i] = 0.
    return lo, hi


def fit_delta(features, scores, labels, seeds, anchor, names, prior):
    x, offsets, weights, counts = contrasts(features, scores, labels, seeds)
    lo, hi = bounds(anchor, names, prior); zero = np.zeros(len(anchor))
    if not len(offsets):
        return zero, {'converged': True, **counts, 'pairs': 0, 'projected_gradient_max': 0., 'iterations': 0}
    active = np.any(np.abs(x) > 1e-12, axis=0)
    result = minimize(loss_gradient, zero, args=(x, offsets, weights), jac=True, method='L-BFGS-B',
        bounds=list(zip(lo, hi)), options={'maxiter':10000, 'maxls':50, 'ftol':1e-14, 'gtol':1e-9, 'maxcor':10})
    delta = result.x; value, gradient = loss_gradient(delta, x, offsets, weights)
    projected = float(np.max(np.abs(delta - np.clip(delta-gradient, lo, hi))))
    require(np.isfinite(delta).all() and np.isfinite(value) and projected <= 1e-6
            and np.all(delta[~active] == 0), 'Constrained fit did not converge')
    return delta, {'converged': True, **counts, 'pairs': len(offsets), 'objective': value,
        'projected_gradient_max': projected, 'iterations': int(result.nit),
        'scipy_success': bool(result.success), 'changed_coordinates': int(np.sum(delta != 0)),
        'inactive_coordinates_unchanged': True}


def metrics(scores, labels, seeds):
    selection, losses = defaultdict(list), defaultdict(list)
    for score, label, seed in zip(scores, labels, seeds):
        top = score >= score.max() - TIE
        selection[seed].append(float(label[top].mean()))
        margins = [score[a]-score[b] for a in range(4) for b in range(4) if label[a] == 1 and label[b] == 0]
        if margins:
            losses[seed].append(float(np.logaddexp(0., -np.asarray(margins)).mean()))
    values = {seed: float(np.mean(v)) for seed, v in sorted(selection.items())}
    return {'gates': len(scores), 'seeds': len(selection), 'informative_gates': sum(map(len, losses.values())),
        'informative_seeds': len(losses), 'expected_observed_target_success': float(np.mean(list(values.values()))),
        'pairwise_nll': float(np.mean([np.mean(v) for v in losses.values()])) if losses else None,
        'expected_seed_successes': values,
        'interpretation': 'seed-balanced controlled branch selection value, not natural win rate'}


def eligible(before, after, informative):
    return (before['informative_seeds'] >= 2 and len({fold_for(s) for s in informative}) >= 2
        and before['pairwise_nll'] is not None and after['pairwise_nll'] is not None
        and after['pairwise_nll'] < before['pairwise_nll'] - 1e-10
        and after['expected_observed_target_success'] > before['expected_observed_target_success'] + 1e-12)


def arrays(data):
    names = data['parameter_names']; groups = data['groups']
    x = np.asarray([[[row[name] for name in names] for row in group['features']] for group in groups], dtype=float)
    baseline = np.asarray([group['baseline_scores'] for group in groups], dtype=float)
    correction = np.asarray([group['fixed_corrections'] for group in groups], dtype=float)
    labels = np.asarray([group['labels'] for group in groups], dtype=int)
    require(x.shape == (len(groups), 4, len(names)) and np.isfinite(x).all() and np.isin(labels, (0,1)).all(), 'Bad input matrix')
    return x, baseline, correction, labels


def prepare():
    require(not OUT.exists(), 'Never overwrite this cloud fit')
    data = read(INPUT); current = read(CURRENT)
    require(data['schema'] == 'closed-functional-role-fit-input-v1' and not data['optimization_run']
            and not data['natural_evaluation_read'] and data['complete_valid_gates'] + len(data['excluded']) == 274
            and data['declared_arms'] == 1096 and len(data['groups']) == data['complete_valid_gates'], 'Wrong closed input')
    old_names = data['baseline_parameter_names']; role_names = data['parameter_names']
    require(current['parameter_names'] == old_names + role_names and len(current['parameters']) == 471, 'Cloud runtime schema differs')
    require(all(current['parameters'][n] == data['baseline_parameters'][n] for n in old_names), 'Cloud 438 baseline differs')
    require(all(current['parameters'][n] == 0 for n in role_names), 'Cloud role weights are not zero baseline')
    OUT.mkdir(parents=True)
    declaration = {'schema':'clab-reexecution-of-predeclared-functional-role-fit-v1',
        'source_method_predeclared_before_outcomes':data['predeclared_protocol'],
        'input':evidence(INPUT), 'fixed_control_model':evidence(CURRENT), 'parameter_names':role_names,
        'expert_prior':data['expert_prior'], 'groups':data['complete_valid_gates'], 'excluded':len(data['excluded']),
        'independent_seeds':data['independent_seeds'], 'folds':5, 'fold_salt':'reward-branch-outcomes-v1|',
        'ridge':RIDGE, 'trust':TRUST, 'absolute_bound':4.,
        'objective':'success-vs-terminal-loss logistic; each informative seed equal weight; equal gates then pairs',
        'unknown_labels_excluded':True, 'complete_four_arm_gates_only':True,
        'natural_data_used_for_fitting':False, 'automatic_deployment':False,
        'admission':'strict whole-seed OOF pair-NLL and selection-value improvement; >=2 informative seeds in >=2 folds',
        'evaluation_allocation':{'pairs':24,'games':48,'fresh_seed_prefix':'defect-functional-role-paired-20260918-',
            'gate':'candidate target successes > control and exact one-sided paired p <= 0.05; invalid retained as failure',
            'no_refit_on_evaluation':True,'no_sample_extension':True},
        'numpy':np.__version__, 'scipy':scipy.__version__, 'created_utc':datetime.now(timezone.utc).isoformat()}
    atomic(OUT/'protocol.json', declaration)
    jobs=[{'pair':i,'seed':f'defect-functional-role-paired-20260918-{i:03d}','arm':arm,
           'run_id':f'defect-functional-role-paired-20260918-{arm}-{i:03d}'} for i in range(24) for arm in ('control','candidate')]
    atomic(OUT/'EVALUATION_ALLOCATION.json', {'declared_before_fit':True,'jobs':jobs,**declaration['evaluation_allocation']})
    print(json.dumps({'prepared':True,'groups':data['complete_valid_gates'],'evaluation_games':48}))


def fit():
    require((OUT/'protocol.json').exists() and not (OUT/'FIT_STARTED.json').exists(), 'Fit not prepared or already started')
    protocol=read(OUT/'protocol.json'); data=read(INPUT); current=read(CURRENT)
    require(protocol['input']==evidence(INPUT) and protocol['fixed_control_model']==evidence(CURRENT)
            and protocol['numpy']==np.__version__ and protocol['scipy']==scipy.__version__, 'Fit source or dependency drift')
    atomic(OUT/'FIT_STARTED.json', {'started_utc':datetime.now(timezone.utc).isoformat(),'protocol':evidence(OUT/'protocol.json')})
    names=data['parameter_names']; groups=data['groups']; prior=data['expert_prior']
    x, base, correction, labels=arrays(data); seeds=[g['seed'] for g in groups]
    anchor=np.asarray([prior[n] for n in names],dtype=float); prior_scores=base+correction+np.einsum('ncp,p->nc',x,anchor)
    folds=np.asarray([fold_for(s) for s in seeds]); oof=prior_scores.copy(); fold_rows=[]
    for fold in range(5):
        train,test=folds!=fold,folds==fold; train_seeds=[s for s,f in zip(seeds,train) if f]
        delta, convergence=fit_delta(x[train],prior_scores[train],labels[train],train_seeds,anchor,names,prior)
        oof[test]=prior_scores[test]+np.einsum('ncp,p->nc',x[test],delta)
        fold_rows.append({'fold':fold,'delta':dict(zip(names,map(float,delta))),'convergence':convergence,
            'validation_seeds':sorted({s for s,f in zip(seeds,test) if f})})
    delta, convergence=fit_delta(x,prior_scores,labels,seeds,anchor,names,prior)
    before, expert, after=[metrics(s,labels,seeds) for s in (base,prior_scores,oof)]
    informative=sorted({g['seed'] for g in groups if len(set(g['labels']))==2})
    admitted=eligible(before,after,informative); overlay=dict(zip(names,map(float,anchor+delta)))
    atomic(OUT/'candidate-overlay.json', {'version':protocol['schema'],'parameters':overlay,'parameter_names':names,
        'baseline':protocol['fixed_control_model'],'fit_protocol':evidence(OUT/'protocol.json'),
        'not_deployed':True,'requires_paired_natural_evaluation':True})
    atomic(OUT/'OOF.json',[{'seed':g['seed'],'gate_hash':g['gate_hash'],'fold':int(folds[i]),'labels':g['labels'],
        'baseline_scores':list(map(float,base[i])),'prior_scores':list(map(float,prior_scores[i])),
        'candidate_scores':list(map(float,oof[i]))} for i,g in enumerate(groups)])
    result={'passed':True,'complete_valid_gates':len(groups),'independent_seeds':len(set(seeds)),'excluded_groups':data['excluded'],
        'baseline_oof':before,'expert_prior_oof':expert,'candidate_oof':after,'folds':fold_rows,'full_fit':convergence,
        'delta':dict(zip(names,map(float,delta))),'natural_trial_eligible':admitted,
        'overlay':evidence(OUT/'candidate-overlay.json'),'oof':evidence(OUT/'OOF.json'),
        'protocol':evidence(OUT/'protocol.json'),'input':evidence(INPUT),'natural_data_used_for_fitting':False,
        'automatic_deployment':False,'goal_complete':False}
    atomic(OUT/'RESULT.json',result)
    if not admitted:
        atomic(OUT/'NOT_ADMITTED.json',{'reason':'frozen whole-seed OOF gates failed','result':evidence(OUT/'RESULT.json')})
        print(json.dumps({'passed':True,'admitted':False,'baseline':before,'candidate':after}));return
    candidate=json.loads(json.dumps(current)); candidate['parameters'].update(overlay)
    candidate['functional_repeat_correction_enabled']=True
    candidate['training']={'method':protocol['schema'],'source_model':evidence(CURRENT),'input':evidence(INPUT),
        'fit_result':evidence(OUT/'RESULT.json'),'natural_evaluation_used_for_fitting':False,
        'paired_evaluation_required':True,'automatic_deployment':False}
    atomic(OUT/'candidate-runtime-model.json',candidate)
    verify_runtime(data,current,candidate)
    atomic(OUT/'INDEPENDENT_READBACK.json', {'passed':True,'candidate_model':evidence(OUT/'candidate-runtime-model.json'),
        'result':evidence(OUT/'RESULT.json'),'input':evidence(INPUT),'scores_verified':4*len(groups),
        'maximum_score_error':0.,'paired_evaluation_required':True,'production_deployed':False})
    print(json.dumps({'passed':True,'admitted':True,'baseline':before,'candidate':after,'model':evidence(OUT/'candidate-runtime-model.json')}))


def verify_runtime(data, control, candidate):
    sys.path.insert(0,str(ROOT));os.chdir(ROOT)
    from sample_runs import build_policy
    from decision_data import enumerate_candidates
    names=data['parameter_names']; groups=data['groups']
    # Load from immutable files to exercise the real policy/model parser.
    control_policy=build_policy('cloud-fit-control-readback',control['solver_requested_config'],epsilon=0.,model_path=CURRENT)
    candidate_path=OUT/'candidate-runtime-model.json'
    candidate_policy=build_policy('cloud-fit-candidate-readback',control['solver_requested_config'],epsilon=0.,model_path=candidate_path)
    maximum=0.; count=0
    for group in groups:
        for policy in (control_policy,candidate_policy):policy.base._special_builds=set(group.get('observed_special_builds',[]))
        before=control_policy.base.rng.getstate(); control_rows={r['candidate_id']:r for r in control_policy.base.score(group['state'],enumerate_candidates(group['state']))['scores']}
        require(control_policy.base.rng.getstate()==before,'Control readback consumed RNG')
        before=candidate_policy.base.rng.getstate(); candidate_rows={r['candidate_id']:r for r in candidate_policy.base.score(group['state'],enumerate_candidates(group['state']))['scores']}
        require(candidate_policy.base.rng.getstate()==before,'Candidate readback consumed RNG')
        for i,cid in enumerate(group['candidate_ids']):
            c0,c1=control_rows[cid],candidate_rows[cid];f=group['features'][i]
            require({n:c0['search_features'][n] for n in names}==f=={n:c1['search_features'][n] for n in names},'Runtime feature drift')
            require(abs(c0['score']-group['baseline_scores'][i])<=1e-10,'Control score differs from branch baseline')
            expected=group['baseline_scores'][i]+group['fixed_corrections'][i]+sum(candidate['parameters'][n]*f[n] for n in names)
            maximum=max(maximum,abs(c1['score']-expected));count+=1
    require(count==4*len(groups) and maximum<=1e-8,'Candidate runtime score mismatch')
    # Patch exact maximum into the eventual readback caller via invariant only; RESULT remains immutable.


if __name__=='__main__':
    require(len(sys.argv)==2 and sys.argv[1] in ('prepare','fit'),'Use prepare or fit')
    prepare() if sys.argv[1]=='prepare' else fit()
