## 文件概述

该文件实现了一个LightGBM快速评估工具，支持按组进行网格搜索交叉验证，输出模型文件、特征重要性及性能指标报告，并修改输入数据添加预测列。

## 函数概要

| 函数名 | 入参 | 返回值 | 功能概述 |
| --- | --- | --- | --- |
| lgb_quick_eval | df_merge, var_cols, target_col, weight_col, group_col, Kfold_col, output_dir, grid_params, n_cores |  | 分组LightGBM网格搜索交叉验证评估函数 |
