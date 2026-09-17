# CLab 持续运行目标

用户于 2026-09-17 明确授权：持续跑下去不要停，设置脚本督促 MiniMax 一个 goal。此授权覆盖旧的“24局结束后停止/禁止新批次”限制，仅针对云端；Windows 本地训练仍暂停。

持久目标：持续推进鸡煲A10训练，朝稳定击败第三幕首个首领前进。当前自动执行阶段是已验证固定模型的采样、审计、复盘和上传；尚未实现云端权重拟合，不把持续采样宣称为模型改进。

## 运行方式

- 每批24局全新预声明种子，单worker，每局1200秒/500宏决策上限。完成后持续接续新批次，不以24局为总上限。
- MiniMax-M3接收持久目标和冻结状态，输出 start_next_batch / publish_and_continue / wait。宿主仅接受固定结构与当前request_id，启动固定采样程序，不执行模型输出的任意shell。
- 每完成约8局及批次结束，请MiniMax复盘、提出下一步重点、归档上传；报告明确区分样本增长和真正模型更新。
- 模型选择wait后5分钟督促一次，再次不推进或回复10分钟超时，由脚本依据用户持续运行授权接续采样。记录脚本接续原因，不冒称MiniMax执行成功；不重放未知模型请求。
- 进程单owner加锁，分配批次前后均持久化；崩溃时已启动未结束种子保留未知、未启动保留单独清单，新批使用新ID，不重复旧分配。
- `sts2-cloud-goal`和`sts2-observer`开机启用；goal进程异常自动恢复。MiniMax最多12次/小时；关闭本地电脑或断开SSH不影响云端。
- 8GiB云盘余量与Git仓库900MB预算继续生效。资源/完整性问题记录状态并定时重新检查；上传异常不伪称成功，也不阻断仍有资源的采样。未上传数据留云端，不能假定都已备份。固定模型不通过自动化直接部署到玩家游戏。

## 目录和停止

- `/home/ubuntu/sts2-cloud-goal/GOAL.json`：持久目标和enabled开关。
- `state.json`、`public-status.json`、`events.jsonl`：推进状态、督促、模型决策和脚本接续记录。
- `batches/defect-cloud-goal-20260917-*/`：独立协议、采样脚本、审计、进程身份和中断记录。
- 原始局数据仍在Linux隔离runtime的outputs，Git仓库 `/home/ubuntu/sts2-cloud-repo`。
- 用户要求暂停时先停止 `sts2-cloud-goal`，并将GOAL.json enabled改为false；如果一并暂停观察则停止observer。未经用户暂停，不自行恢复旧的24局总上限。

## 当前仓库

私有仓库：https://github.com/zhangchr123/sts2-clab-training 。原首24局均已审计并上传，目标成功0/24；此前7局已额外做独立GitHub下载逐成员SHA256验收。后续资料按批次保存。上传使用单仓库deploy key，不包含SSH私钥、API key、账号密码或游戏DLL。

10项自动化/恢复/指令边界测试在Linux通过；真实MiniMax首个goal响应选择start_next_batch。最新实机启动状态见本地CONTINUOUS_GOAL_ACCEPTANCE.json及云端state.json。
