# CLab 当前批次报告

确定性统计：24/24 已结束并审计；有效 24，无效或未知 0，观测到第三幕首领目标成功 2。

冻结模型：`linux-validated-baseline-471`，SHA256 `59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4`；相对原 Linux 基线是否更新：`false`。

本批为单一冻结模型自然采样，不是与另一模型的成对比较，不据此单独声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

批次 defect-cloud-goal-20260917-000099 phase=complete：planned/completed/valid=24、invalid=0、target_successes=2（仅该来源观察值，不等于全种子成功，亦不等于最终 205/256 门槛达成）；model_sha256=59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4、model_label=linux-validated-baseline-471、model_updated=false；closed_batches=98、new_batch_allowed=true、partial_upload_authorized=true；baseline 24 局 valid=24 第三幕目标成功 0；progress_aux_evaluation 120 局 60 对，控制 3 胜 vs 候选 1 胜，单侧 p=0.9375，candidate_gate_passed=false、deployment_authorized=false；merchant smoke 1/1 通过、paired 21/120 双 0 含 1 invalid；254 受控分支 33 参数一次拟合 OOF 0.09737<NLL 1.45688 未过基线 0.09825/1.41336，候选已拒绝未部署；event-effect-smoke 仍 failed（1/1 invalid=1）阻塞 event/selection 链；磁盘 cloud-training 余 43 GiB low=false 未越阈值；processes=[] 仅表示未配置监控。按用户最新持续授权，本批归档并立即开新批 defect-cloud-goal-20260917-000100。
下一步：采样与真正改进模型之间仍缺：① 高信号受控分支样本——progress_aux 60 对 3:1、p=0.9375 几乎无分辨力；merchant paired 21/120 双 0 证据不足；254 节点 33 参数一次拟合 OOF 0.09737<NLL 1.45688 未过基线 0.09825/1.41336，候选被门禁拒绝且未部署；自然局仅作描述统计，不能等同于胜率提升。② 干净成对评估与预声明拟合轮次——需更高样本量、更多受控拟合轮次、明确预声明阈值，event-effect-smoke 1/1 invalid=1 需排查解锁 event/selection 链，使下游 paired/independent 可运行。③ 持续自然局 24 全新种子一批接一批，不重跑已启动 seed；保留失败与未知，等待受控分支信号改善后才有候选部署资格。
