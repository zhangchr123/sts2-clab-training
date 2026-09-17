# CLab 当前批次报告

确定性统计：15/24 已结束并审计；有效 15，无效或未知 0，观测到第三幕首领目标成功 0。

固定模型自然采样，不是与另一模型的成对比较，不据此声称训练提升。

## MiniMax 报告（模型生成，以上方可核验统计为准）

批次 defect-cloud-training-20260917a 冻结快照：计划 24 局，已完成 15 局，有效 15 局，无效 0，target_successes=0，阶段 running，模型未更新，不允许新批次，partial_upload_authorized=true 且 adapter_revision=3 明确允许分批归档；owner_state=live。实时计数已达 22/24，进程 cloud-sampling-owner 仍 live，磁盘 53 GiB 正常。按最新授权，已有 15 局已结束（含有效与无效局），选择 publish_snapshot，归档冻结快照中的已结束局至私有仓库 zhangchr123/sts2-clab-training；不修改模型、不删除原始资料、不新开批次。下一冻结快照可再行评估，注意实时计数接近完成。
