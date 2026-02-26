## 文件概述

该文件定义了一个用于计算分类模型性能指标（KS、AUC、hitrate）的函数，支持多分数列、多目标列、多分组维度，并提供pivot宽表输出功能。核心通过polars lazy API并行计算累计分布，适用于模型监控与分析场景。

## 函数概要

| 函数名 | 入参 | 返回值 | 功能概述 |
| --- | --- | --- | --- |
| summary_performance | df, score_cols, target_cols, weight_col, seg_cols_ls, dcast_params |  | 计算多分数列的多目标性能指标（KS/AUC/hitrate），支持多维度分组与pivot宽表输出。 |
