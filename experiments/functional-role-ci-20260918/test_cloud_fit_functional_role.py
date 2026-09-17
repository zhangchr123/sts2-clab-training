import json
import unittest
import numpy as np
import cloud_fit_functional_role as f


class FitContracts(unittest.TestCase):
    def test_whole_seed_weights_sum_to_one(self):
        x=np.zeros((2,4,2));x[0,:,0]=[2,0,1,0];x[1,:,0]=[0,1,0,2]
        scores=np.zeros((2,4));labels=np.asarray([[1,0,1,0],[0,1,0,1]])
        contrast,offset,weights,counts=f.contrasts(x,scores,labels,['same','same'])
        self.assertEqual(counts,{'informative_seeds':1,'informative_gates':2})
        self.assertAlmostEqual(float(weights.sum()),1.)
        self.assertEqual(len(contrast),8)

    def test_sign_and_fixed_zero_bounds(self):
        names=['positive','negative','role_attack_gap','functional_repeat','rarity_unknown','cost_unknown']
        prior={'positive':1.,'negative':-1.,'role_attack_gap':0.,'functional_repeat':0.,'rarity_unknown':0.,'cost_unknown':0.}
        lo,hi=f.bounds(np.asarray([prior[n] for n in names]),names,prior)
        self.assertTrue(lo[0]>=-1 and 1+lo[0]>=0)
        self.assertTrue(hi[1]<=1 and -1+hi[1]<=0)
        self.assertGreaterEqual(lo[2],0)
        self.assertTrue(np.all(lo[3:]==0) and np.all(hi[3:]==0))

    def test_fit_prefers_observed_winner_and_is_finite(self):
        x=np.zeros((4,4,1));labels=[];seeds=[]
        for i in range(4):
            x[i,:,0]=[1,0,0,0];labels.append([1,0,0,0]);seeds.append('s'+str(i))
        labels=np.asarray(labels);scores=np.zeros((4,4));anchor=np.zeros(1)
        delta,receipt=f.fit_delta(x,scores,labels,seeds,anchor,['role_attack_gap'],{'role_attack_gap':0.})
        self.assertGreater(delta[0],0);self.assertTrue(receipt['converged'])
        self.assertLess(f.metrics(scores+np.einsum('ncp,p->nc',x,delta),labels,seeds)['pairwise_nll'],f.metrics(scores,labels,seeds)['pairwise_nll'])

    def test_eligibility_requires_selection_value_too(self):
        before={'informative_seeds':2,'pairwise_nll':1.,'expected_observed_target_success':.4}
        after={'informative_seeds':2,'pairwise_nll':.9,'expected_observed_target_success':.4}
        self.assertFalse(f.eligible(before,after,['a','b']))


if __name__=='__main__':unittest.main(verbosity=2)
