# CLab 当前批次报告

确定性统计：18/24 已结束并审计；有效 18，无效或未知 0，观测到第三幕首领目标成功 2。

冻结模型：`linux-validated-baseline-471`，SHA256 `59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4`；相对原 Linux 基线是否更新：`false`。

本批为单一冻结模型自然采样，不是与另一模型的成对比较，不据此单独声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

批次 defect-cloud-goal-20260917-000098 处于 running：planned=24、completed=18、valid=18、invalid=0、target_successes=2（仅该来源观察值，不等于全种子成功，亦不等于最终 205/256 门槛达成）；model_sha256=59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4（linux-validated-baseline-471），model_updated=false，new_batch_allowed=true，partial_upload_authorized=true，owner_state=live，closed_batches=97。诊断：audited_natural_runs=115、target_successes=4、near_target_failures=12、late_act3_review_decisions=28；baseline 24 局 third_act_target_successes=0；progress_aux_evaluation 60 对 3:1、one_sided_paired_p=0.9375 未过候选门禁，候选 OOF=0.09737 低于基线 0.09825 且 NLL=1.45688 高于 1.41336，已被拒绝、未部署；natural_outcomes_used_for_fitting=false；merchant paired 21/120 双 0；4 离线候选及 event/selection 链均 validated_not_deployed。资源：disk.free_gib_floor=44、low=false，非阈值告警；processes=[] 不推断进程。阶段 continuous_goal_active，本批未结束，按指令走 publish_and_continue：归档已完结局后让当前批继续。
下一步：采样与真正改进模型之间仍缺：① 高信号受控分支样本——progress_aux 60 对 3:1、p=0.9375 分辨力弱；merchant paired 21/120 双 0 证据不足；254 节点 33 参数一次拟合 OOF 0.09737<NLL 1.45688 未过基线 0.09825/1.41336，需更高样本与多轮受控拟合；② 干净成对评估与预声明拟合轮次——event-effect-smoke 已 failed（1/1 invalid=1），event-effect-paired-evaluation 与 selection-effect 双链均 waiting gate，需先修 smoke 再启成对；③ 候选门禁——4 离线候选与 event/selection 链均 validated_not_deployed，candidate_gate_passed=false，禁止把自然局当改进证据；下一步重点是 publish 已完结局让 000098 跑满 24，并在受控分支扩样本、补 event/selection smoke 与配对评估，再做下一轮拟合。
