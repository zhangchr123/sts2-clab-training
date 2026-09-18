# CLab 自然局决策结构诊断 v2

冻结快照覆盖 115 局鸡煲 A10 自然局：4 局击败第三幕首个 Boss，12 局到达目标附近但未通过，98 局更早失败，1 局无效并保留。

共核验 7384 个策略决策；5481 个为多候选决策，其中 1431 个未校准分差不超过 0.10。分差不是概率或因果效应；自然结局只用于描述分层，没有进入拟合、选模或部署。

近目标复核队列共有 693 个决策，结果文件保留稳定排序的 250 个；其中第三幕第 10 层及以后有 28 个。下一轮受控采样重点依次为：event_effect_and_probability、ordered_card_selection_and_transform_effects、route_damage_and_full_path_evaluation、card_reward_mechanism_and_current_stats、rest_heal_and_future_route_damage。
