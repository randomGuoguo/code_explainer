## 文件概述

该文件提供了一套基于Polars的IV（信息值）和WOE（证据权重）计算工具，主要用于信用风险评分卡的分箱、趋势合并和特征评估。包含分箱创建、按趋势合并分箱、以及IV分布摘要生成等功能，支持缺失值处理和分段计算。

## 函数概要

| 函数名 | 入参 | 返回值 | 功能概述 |
| --- | --- | --- | --- |
| iv_expr | good_pct, bad_pct |  | 计算IV的Polars表达式。 |
| woe_expr | good_pct, bad_pct |  | 计算WOE的Polars表达式。 |
| _woe_table | df |  | 为分箱表添加WOE和IV列。 |
| pattern_bin_merge | wgt, pattern |  | 基于趋势合并分箱索引。 |
| _pattern_bin_merge | df_woe, var_nm |  | 按趋势合并正常分箱。 |
| bin_table | df_part, x_cols, target_col, weight_col, num_bins, MV_dict, pattern_merge |  | 创建变量分箱表并可选合并。 |
| iv | good_pct, bad_pct |  | 计算IV数值。 |
| woe | good_pct, bad_pct |  | 计算WOE数值。 |
| summary_iv | df, x_cols, target_col, weight_col, seg_cols_ls, num_bins, MV_dict |  | 计算IV摘要，支持分段。 |
| summary_iv_distribution | iv_summary, org_class_col, var_name_col, theme_col, save_path |  | 生成IV分布摘要表。 |
| summary_iv_top_distribution | res_iv, top_pcts, org_class_col, var_name_col, theme_col, save_path |  | 计算头部IV分布。 |
