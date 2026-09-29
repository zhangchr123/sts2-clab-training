# CLab 当前批次报告

确定性统计：24/24 已结束并审计；有效 24，无效或未知 0，观测到第三幕首领目标成功 1。

冻结模型：`linux-validated-baseline-471`，SHA256 `59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4`；相对原 Linux 基线是否更新：`false`。

本批为单一冻结模型自然采样，不是与另一模型的成对比较，不据此单独声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

批次 defect-cloud-goal-20260917-000092 phase=complete：planned/completed/valid=24，invalid=0，target_successes=1，model_sha256=59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4（linux-validated-baseline-471），model_updated=false，new_batch_allowed=true，partial_upload_authorized=true，closed_batches=91，owner_state=missing，step=1457。环境/有效性/worker/审计/磁盘零失败，disks.free_gib_floor=47、low=false。progress_aux_evaluation 60 对 control3 vs candidate 1、one_sided_paired_p=0.9375、candidate_gate_passed=false、deployment_authorized=false；merchant paired 21/120 双 0；其余4 候选 validated_not_deployed 等待父链门禁。complete 阶段选 publish_and_continue，上传本批 24 局归档并启动下一批 24 个全新自然 seed，禁止重跑本批。
下一步：采样与真正改进模型之间仍缺：① 高信号受控分支样本——progress_aux 仅 60 对 control:candidate=3:1、one_sided_paired_p=0.9375 分辨力弱；merchant paired 21/120 双 0；其余4 候选 validated_not_deployed 等待父链门禁；event-effect/selection-effect 双链卡在 smoke_failed，需扩样本并提高分歧占比、预声明最低配对数与停止准则；② 预声明拟合轮次——上次 33 参数拟合 OFF 0.09737<NLL 1.45688>基线 0.09825/1.41336 被拒，下次须先声明参数集、轮次、OOF/NLL 接受门槛再拟合，禁止把自然局增量或单次拟合当胜率提升；③ 分歧局导向输入——利用 controlled_acquisition_priority 五区(event_effect/ordered_card/route_damage/card_reward/rest_heal)的 control vs candidate 分歧局作拟合输入，禁止重跑已启动 seed；④ 持续维持 linux-validated-baseline-471 冻结基线至 256/205 门槛达成，禁止自动部署任何候选。
