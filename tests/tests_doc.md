## 文件概述

这是一个Python模块，提供两个数据平衡函数：balance_badrate用于根据目标坏账率调整样本权重，balance_weight用于调整样本权重到指定总重。适用于金融风控等领域的数据预处理。

## 函数概要

| 函数名 | 入参 | 返回值 | 功能概述 |
| --- | --- | --- | --- |
| balance_badrate | df, target_col, *, weight_col, badrate_info, group_cols, default_badrate_info, adjusted_weight_name |  | 调整样本权重以实现目标坏账率平衡。 |
| balance_weight | df, *, weight_col, weight_info, group_cols, adjusted_weight_name |  | 调整样本权重以实现目标总重平衡。 |
