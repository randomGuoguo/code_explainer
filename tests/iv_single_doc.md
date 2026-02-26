## 文件概述

本模块提供信用评分模型的变量分箱、WOE/IV计算及汇总分析功能。主要流程：基于加权分位数自动分箱，支持缺失值映射；可选按趋势合并分箱以优化IV；计算分箱的WOE和IV；支持分组汇总IV；生成IV分布统计和Top变量分析。关键函数包括bin_table、summary_iv等。

## 函数概要

| 函数名 | 入参 | 返回值 | 功能概述 |
| --- | --- | --- | --- |
| iv_expr | good_pct, bad_pct |  | 计算IV的polars表达式。 |
| woe_expr | good_pct, bad_pct |  | 计算WOE的polars表达式。 |
| _woe_table | df |  | 分箱表的WOE/IV计算。 |
| pattern_bin_merge | wgt, pattern |  | 基于趋势合并分箱索引。 |
| _pattern_bin_merge | df_woe, var_nm |  | 对单个变量分箱合并并优化IV。 |
| bin_table | df_part, x_cols, target_col, weight_col, num_bins, MV_dict, pattern_merge |  | 计算多个变量的加权分箱表。 |
| iv | good_pct, bad_pct |  | 计算IV值。 |
| woe | good_pct, bad_pct |  | 计算WOE值。 |
| summary_iv | df, x_cols, target_col, weight_col, seg_cols_ls, num_bins, MV_dict |  | 计算变量IV并汇总。 |
| summary_iv_distribution | iv_summary, org_class_col, var_name_col, theme_col, save_path |  | 生成IV区间分布统计表。 |
| summary_iv_top_distribution | res_iv, top_pcts, org_class_col, var_name_col, theme_col, save_path |  | 生成机构分类内IV top变量分布。 |
