# CLab 当前批次报告

确定性统计：24/24 已结束并审计；有效 24，无效或未知 0，观测到第三幕首领目标成功 0。

固定模型自然采样，不是与另一模型的成对比较，不据此声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

批次 defect-cloud-training-20260917a 冻结快照：计划 24 局，已完成 24 局，有效 24 局，无效 0，target_successes=0，阶段 complete，模型未更新，不允许新批次，partial_upload_authorized=true 且 adapter_revision=3 允许分批归档；owner_state=missing（24 局自然退出，符合预期）。实时计数 24/24，进程 cloud-sampling-owner 已 missing，磁盘 53 GiB 正常。按规则 24 局自然退出为预期行为，选择 publish_snapshot 归档全部 24 局已结束局（含有效与无效局）至私有仓库 zhangchr123/sts2-clab-training；不修改模型、不删除原始资料、不新开批次。target_successes=0 仅为观察值，不构成性能结论。
