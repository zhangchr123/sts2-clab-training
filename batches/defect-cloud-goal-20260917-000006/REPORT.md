# CLab 当前批次报告

确定性统计：16/24 已结束并审计；有效 16，无效或未知 0，观测到第三幕首领目标成功 2。

冻结模型：`linux-validated-baseline-471`，SHA256 `59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4`；相对原 Linux 基线是否更新：`false`。

本批为单一冻结模型自然采样，不是与另一模型的成对比较，不据此单独声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

新批次 defect-cloud-goal-20260917-000006（goal defect-continuous-training-20260917）冻结快照：计划 24 局，已完成 16 局，有效 16 局，无效 0，target_successes=2，阶段 running，模型 linux-validated-baseline-471（sha256 59d11c...）未更新，new_batch_allowed=true，partial_upload_authorized=true，adapter_revision=3，owner_state=live，closed_batches=5，基线 24 局 0 目标成功。progress_aux_evaluation 120 局 60 对，candidate 1 vs control 3，p=0.9375，candidate_gate_passed=false。诊断：audited_natural_runs=115、target_successes=4、near_target_failures=12。merchant_candidate_pipeline：smoke 1/1 complete、paired 21/120（1 无效，0 目标成功）。实时状态：continuous-defect-goal step=23/completed=16/target_successes=2；磁盘 46 GiB。按持久目标指令与 running 阶段规则，选 publish_and_continue：上传已完结的 16 局并让当前批继续。
下一步：采样与真正改进模型之间仍缺：一、高信号受控分支样本——progress_aux 60 对样本仍小，candidate 1 vs control 3 被拒，merchant paired 21/120 仍 0 目标成功；二、预声明的拟合轮次——上次 33 参数拟合 OFF/NLL 失败，需明确轮次与停止准则；三、利用分歧局做下次拟合——candidate_rejected_keep_control_and_use_disagreements_for_next_fit；四、目标层稳定通关——基线 0 vs audited target_successes=4/near_target_failures=12，远未达每次稳定通关；五、五个 controlled_acquisition_priority_areas 需针对性受控样本；六、event-effect 冒烟失败原因仍待排查；七、merchant paired 评估 control & candidate 均 0 目标成功，需扩大样本。本批重点：完成剩余 8 局，收集分歧局与近失败局元数据，为高信号受控样本与下次拟合提供输入。
