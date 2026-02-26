## 文件概述

本模块提供信用评分卡建模中的分箱、WOE与IV计算功能，涵盖表达式工具、分箱表构建、基于累积odds趋势的自动合并算法、批量IV汇总及分布分析，适用于Polars DataFrame，支持权重和缺失值处理。

## 函数概要

| 函数名 | 入参 | 返回值 | 功能概述 |
| --- | --- | --- | --- |
| iv_expr | good_pct, bad_pct |  | 通过Polars表达式快速计算IV。 |
| woe_expr | good_pct, bad_pct |  | 计算WOE表达式，处理极小值。 |
| _woe_table | df |  | 计算分箱表的总权重、占比、WOE和IV。 |
| pattern_bin_merge | wgt, pattern |  | 基于累积odds趋势合并分箱索引。 |
| _pattern_bin_merge | df_woe, var_nm |  | 对分箱表应用趋势合并优化，选择最佳模式。 |
| bin_table | df_part, x_cols, target_col, weight_col, num_bins, MV_dict, pattern_merge |  | 生成多变量分箱表，支持缺失值和趋势合并。 |
| iv | good_pct, bad_pct |  | 计算IV，有极小值保护。 |
| woe | good_pct, bad_pct |  | 计算WOE，防除零。 |
| summary_iv | df, x_cols, target_col, weight_col, seg_cols_ls, num_bins, MV_dict |  | 批量计算变量IV和分箱明细，支持分段。 |
| summary_iv_distribution | iv_summary, org_class_col, var_name_col, theme_col, save_path |  | 分析IV分布，输出机构在区间的变量计数和占比。 |
| summary_iv_top_distribution | res_iv, top_pcts, org_class_col, var_name_col, theme_col, save_path |  | 评估各机构IV顶部变量的占比和阈值。 |
