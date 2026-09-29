# CLab 当前批次报告

确定性统计：8/24 已结束并审计；有效 8，无效或未知 0，观测到第三幕首领目标成功 0。

冻结模型：`linux-validated-baseline-471`，SHA256 `59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4`；相对原 Linux 基线是否更新：`false`。

本批为单一冻结模型自然采样，不是与另一模型的成对比较，不据此单独声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

新批次 defect-cloud-goal-20260917-000094 已启动并处 running：planned=24、completed=8、valid=8、invalid=0、target_successes=0；model_sha256=59d11c9fe8c6d94d2968928aaf567a3fb73ec6b53252feb0e2b7f7e164eacac4（model_label=linux-validated-baseline-471，model_updated=false），closed_batches=93，goal_id=defect-continuous-training-20260917，owner_state=live，partial_upload_authorized=true。连续采样器累计 93 局 step=1461（PUBLIC_STATUS 与本批 8/24 不同步，源数据冲突）。本批 target_successes=0 仅是本次源观测值，不构成训练失败亦不反推目标规模。配对评估：progress_aux 60 对 control:candidate=3:1、one_sided_paired_p=0.9375、candidate_gate_passed=false、deployment_authorized=false（上次 33 参数拟合 OOF 0.09737 低于基线 0.09825、NLL 1.45688 高于 1.41336 被拒未部署）；merchant paired 21/120 双 0；event-effect smoke failed（1 invalid/1）；其余 4 候选 validated_not_deployed 等父链门禁。磁盘 free_gib_floor=46、low=false，processes=[] 仅表示未配置进程监控。批次 running 且 partial_upload_authorized=true，按用户持续指令选择 publish_and_continue：上传已完结局并让当前批继续。
下一步：采样与真正改进模型之间仍缺：① 高信号受控分支样本——progress_aux 仅 60 对 control:candidate=3:1、one_sided_paired_p=0.9375 分辨力弱；merchant paired 21/120 双 0；其余 4 候选 validated_not_deployed 等父链门禁；event-effect smoke failed 阻塞 event/selection 双链；需扩样本并提高分歧占比、预声明最低配对数与停止准则；② 预声明拟合轮次——上次 33 参数拟合 OOF 0.09737 低于基线 0.09825、NLL 1.45688 高于 1.41336 被拒，下次须先声明参数集、轮次、接受门槛再拟合，禁止把自然局增量或单次拟合当胜率提升；③ 新批次 000094 running 中 completed 8/24、target_successes=0，PUBLIC_STATUS 连续采样器累计仍报 93 而本批已开始，源数据存在小不一致需运维确认；自然局结果只能当描述统计，不能替代最终 256 全新种子 ≥205 真实第三幕首 Boss 击败、胜率≥80%、零质量失败的门槛。
