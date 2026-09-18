# CLab 当前批次报告

确定性统计：24/24 已结束并审计；有效 24，无效或未知 0，观测到第三幕首领目标成功 2。

冻结模型：`linux-validated-baseline-471`，SHA256 `59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4`；相对原 Linux 基线是否更新：`false`。

本批为单一冻结模型自然采样，不是与另一模型的成对比较，不据此单独声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

新批次 defect-cloud-goal-20260917-000004（goal defect-continuous-training-20260917）冻结快照：计划 24 局，已完成 24 局，有效 24 局，无效 0，target_successes=2，阶段 complete，模型 linux-validated-baseline-471（sha256 59d11c...）未更新，new_batch_allowed=true，partial_upload_authorized=true，adapter_revision=3，owner_state=missing（自然退出），closed_batches=3，基线 24 局 0 目标成功。progress_aux_evaluation 120 局 60 对，candidate 1 vs control 3，p=0.9375，candidate_gate_passed=false，next_action=candidate_rejected_keep_control_and_use_disagreements_for_next_fit。实时状态：continuous-defect-goal step=18/status=complete/total=3；merchant-item-smoke-handoff 转为 merchant_smoke_active，merchant-item-smoke 进入 natural_integration_smoke（0/1）；event-effect-smoke 仍 failed。complete 阶段选 start_next_batch：归档本批 24 局后启动下一批 24 个全新种子自然局采样，仍固定已验证模型、不拟合新权重、不重跑同一分配。
下一步：采样与真正改进模型之间仍缺：一、高信号受控分支样本——progress_aux 60 对样本仍小，candidate 1 vs control 3 被拒；二、预声明的拟合轮次——上次 33 参数拟合 OFF/NLL 失败，需明确轮次；三、利用分歧局做下次拟合——next_action 建议用 disagreements_for_next_fit；四、目标层稳定通关——基线 0 vs 本批 2 成功，远未达每次稳定通关；五、五个 controlled_acquisition_priority_areas 需针对性受控样本；六、merchant-item 冒烟刚启动，需关注是否复现 event-effect 失败模式；七、event-effect 失败原因仍待排查。新批重点：保持 24 局全完结且有效，收集分歧局与近失败局元数据，为高信号受控样本与下次拟合提供输入。
