# CLab 鸡煲自然局结构快照

快照包含 78 局已结束且审计有效的 A10 自然局：1 次击败第三幕第一个 Boss，9 次抵达该 Boss 但未通过，68 次更早失败。该统计来自同一冻结模型的自然采样，只用于描述和决定下一步实验，不作为模型提升或卡牌因果价值证明。

牌组规模符合用户约束。71/78 局终局不超过 25 张，6 局为 26–36 张；唯一 52 张局检测到 `REFLECTIONS_SHATTER` 特殊构筑，未发现没有特殊构筑豁免而超过 36 张的局。唯一目标成功局恰好 25 张。9 个近目标失败局的牌组中位数也是 25；去掉 52 张特殊构筑后，另外 8 局均值为 24.75。

成功局在 6 HP 击败 Queen 后进入第二 Boss，最终于 Act 3 Floor 16 失败。25 张终局牌组有 6 张升级牌，核心包括两张 Capacitor、Coolheaded+、Hologram、Chill、Coolant、Chaos、Lightning Rod、Loop、Echo Form、Machine Learning、Overclock 与 Charge Battery+；遗物包括 Data Disk、Pael's Eye、Lizard Tail、Book of Five Rings 等。单个成功样本不能证明这些牌或遗物的因果作用。

动作日志按 `decision_id` 合并计划与执行记录后，78 局共实际拿牌 817 次、跳过奖励 415 次。更早失败局占 68/78，说明下一轮不能只继续压牌组规模；需要由已预声明的 60 对自然评估先判断“首 Boss 主目标 + 失败进度辅助”候选是否改善整体选择，再依据配对结果扩充受控分支与特征。

