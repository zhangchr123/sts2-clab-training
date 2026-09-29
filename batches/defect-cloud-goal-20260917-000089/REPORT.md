# CLab 当前批次报告

确定性统计：8/24 已结束并审计；有效 8，无效或未知 0，观测到第三幕首领目标成功 1。

冻结模型：`linux-validated-baseline-471`，SHA256 `59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4`；相对原 Linux 基线是否更新：`false`。

本批为单一冻结模型自然采样，不是与另一模型的成对比较，不据此单独声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

批次 defect-cloud-goal-20260917-000089 处于 running 阶段，已完结 8/24 局且全部 valid，target_successes=1；当前快照 step=1447、closed_batches=88。persistent_goal 要求 256 个全新自然 seed 中至少 205 个具备第三幕首 Boss 真实击败证据（经验胜率 ≥80%）且环境/有效性/worker/审计/磁盘零失败。冻结事实显示：progress_aux 120局 candidate 1 vs control 3、one_sided_p=0.9375 候选门禁未通过、未授权部署；merchant paired 21/120 双端目标成功均为 0；254 受控分支 gate 的 33 参数拟合 OFF=0.09737（<0.09825 基线）、NLL=1.45688（>1.41336）被拒；模型 linux-validated-baseline-471（sha256 59d11c9…）保持未更新。disks.cloud-training free_gib_floor=49、low=false；processes=[] 不推断进程身份；target_successes=1 仅为来源观测值，不证明完成率。本批 running，选择 publish_and_continue：上传已完结局，让当前批继续采集直到 24 局。
下一步：采样与真正改进模型之间仍缺：① 高信号受控分支样本——progress_aux 60 对、merchant paired 21/120 均不足，candidate vs control 在 progress_aux 1 vs 3、merchant 双0，分辨力弱，需扩样本并提升分歧占比；② 预声明的拟合轮次与停止准则——上次 33 参数拟合 OFF/NLL 双劣于基线被拒，下次需先声明轮次、参数集、接受门槛再做拟合；③ 分歧局导向的拟合输入——利用 candidate_only 与 control_only 的种子差集构造下一次受控评估，再用其结果驱动新一轮候选参数；④ event/selection/full-route/reward/rest 等候选链仍处 validated_not_deployed等待父链 gate，须先通过其受控分支评估；⑤ 在 candidate 未通过预声明门槛前，自然局只做描述统计，不得以扩样本或单次拟合声称为胜率提升。
