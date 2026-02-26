import numpy as np
import polars as pl
from polars_common import adj_colorder


def summary_performance(df, score_cols, target_cols, weight_col, seg_cols_ls, dcast_params=dict()):
    """
    功能描述:
    计算多个分数列在多个目标列上的性能指标（KS、AUC、hitrate），支持按多组分段列分组统计，并可通过dcast_params参数将结果pivot为宽表以便对比分析。
    
    参数:
    df: polars.DataFrame，输入数据框，需包含分数列、目标列（0/1）、权重列及分段列。
    score_cols: list[str]，待评估的分数列名列表。
    target_cols: list[str]，目标变量列名列表（二分类，取值0或1）。
    weight_col: str，权重列名，用于加权计算。
    seg_cols_ls: list[list[str]]，分段列名列表的列表，每个内层列表表示一组分段列，空列表表示全局统计。
    dcast_params: dict, optional，指定需pivot的指标列及其对应的pivot列，例如{'KS': ['app_ym']}将KS值按app_ym列展开。默认空字典。
    
    返回值:
    dict，包含以下键：
      'cnt': polars.DataFrame，明细表，记录每个分数分段（四舍五入到3位）的正负样本数、权重和、累计百分比等。
      'KS': polars.DataFrame，汇总表，包含每个分组（若有）、每个目标、每个分数对应的KS、AUC、KS_score等核心指标。
      若dcast_params非空，额外提供键如'KS_dcast'，为pivot后的宽表。
    
    关键规则:
    - 分数列自动四舍五入到3位，防止内存爆炸。
    -KS计算：取每个分组-目标-分数下，正负样本累计百分比差值（diff_cumpct）绝对值最大的分数点作为KS点，并记录对应分数与累计百分比。
    -AUC计算：采用梯形法近似，公式为sum(0.5*(B_cumpct_i+B_cumpct_{i+1})*(G_cumpct_{i+1}-G_cumpct_i))。
    -hitrate = 分组总权重（正负样本权重和） / 该分组下有标签样本总权重（target_col为0或1的权重）。
    - 每个seg_cols组合独立计算后合并，分段列顺序按首次出现保留。
    
    示例:
    df = pl.DataFrame({'score':[0.1,0.2,0.3], 'y':[0,1,0], 'weight':[1,1,1], 'month':['2023-01','2023-01','2023-02']})
    result = summary_performance(df, score_cols=['score'], target_cols=['y'], weight_col='weight', seg_cols_ls=[['month']], dcast_params={'KS':['month']})
    # 返回按month分组的KS/AUC明细及KS_dcast宽表（行索引为其他分段列，列名为month）。
    
    实现说明(<=100字):
    内部通过polars lazy API并行计算每个目标-分数组合的累计分布，合并后分组聚合求KS/AUC，hitrate基于权重比计算，最后按需pivot。临时列用于无分段场景。
    """
    def calc_ks_cnt(df_part, score_cols, target_cols, weight_col, seg_cols):
        is_noseg = len(seg_cols) == 0
        if is_noseg:
            df_part = df_part.with_columns(pl.lit(1).alias('__tmp__'))
            seg_cols = ['__tmp__']
        lazy_jobs = []
        for target_col in target_cols:
            for score_col in score_cols:  # 分数需要round，避免取值太多导致内存爆炸
                lazy_job = df_part.lazy().filter(pl.col(target_col).is_in([0,1]) & 
                                                pl.col(score_col).is_not_null())\
                    .with_columns(pl.col(score_col).round(3))\
                    .group_by(seg_cols, score=score_col).agg(
                        G_cnt=(pl.col(target_col)==0).sum(),
                        B_cnt=(pl.col(target_col)==1).sum(),
                        G_wgt=(pl.col(weight_col).filter(pl.col(target_col)==0)).sum(),
                        B_wgt=(pl.col(weight_col).filter(pl.col(target_col)==1)).sum())\
                    .sort(seg_cols + ['score'])\
                    .with_columns(Tot_wgt = pl.col('B_wgt') + pl.col('G_wgt'))\
                    .with_columns(
                        Tot_pct = pl.col('Tot_wgt') / pl.col('Tot_wgt').sum().over(seg_cols),
                        G_pct = pl.col('G_wgt') / pl.col('G_wgt').sum().over(seg_cols),
                        B_pct = pl.col('B_wgt') / pl.col('B_wgt').sum().over(seg_cols))\
                    .with_columns(
                        Tot_cumpct = pl.col('Tot_pct').cum_sum().over(seg_cols),
                        G_cumpct = pl.col('G_pct').cum_sum().over(seg_cols),
                        B_cumpct = pl.col('B_pct').cum_sum().over(seg_cols))\
                    .with_columns(diff_cumpct = pl.col('B_cumpct') - pl.col('G_cumpct'))\
                    .with_columns(target_nm=pl.lit(target_col, dtype=pl.String),
                                  score_nm=pl.lit(score_col, dtype=pl.String))
                lazy_jobs.append(lazy_job)
        st = pl.concat(pl.collect_all(lazy_jobs), how='diagonal_relaxed') # score_cols may be diffrent types,eg int/float
        if is_noseg:
            st = st.drop('__tmp__')
        return st
    
    # basic cnt by score
    st_cnt_ls = []
    for seg_cols in seg_cols_ls:
        if len(seg_cols) == 0:
            st_cnt = calc_ks_cnt(df, score_cols, target_cols, weight_col, seg_cols)
            st_cnt_ls.append(st_cnt)
        else:
            for seg_nms, df_part in df.group_by(seg_cols):
                st_cnt = calc_ks_cnt(df_part, score_cols, target_cols, weight_col, seg_cols)
                st_cnt = st_cnt.with_columns(pl.lit(grp_nm, dtype=df.schema[seg_nm]).alias(seg_nm)
                                             for seg_nm, grp_nm in zip(seg_cols, seg_nms))
                st_cnt_ls.append(st_cnt)
    st_cnt = pl.concat(st_cnt_ls, how="diagonal")
    
    # KS/AUC
    all_seg_cols = []
    for seg_cols in seg_cols_ls:
        for x in seg_cols:
            if x not in all_seg_cols:
                all_seg_cols.append(x)
    st_cnt = adj_colorder(st_cnt, all_seg_cols + ['target_nm', 'score_nm', 'score'], insert_first=True)
    st_cnt = st_cnt.sort(all_seg_cols + ['target_nm', 'score_nm', 'score'])
    
    st_ks = st_cnt.group_by(all_seg_cols + ['target_nm', 'score_nm'])\
                .agg(
                    pl.col('G_cnt').sum(),
                    pl.col('B_cnt').sum(),
                    pl.col('G_wgt').sum(),
                    pl.col('B_wgt').sum(),
                    pl.col('Tot_wgt').sum(),
                    pl.col('score').get(pl.col('diff_cumpct').abs().arg_max()).alias('KS_score'),
                    pl.col('Tot_cumpct').get(pl.col('diff_cumpct').abs().arg_max()).alias('KS_percentile'),
                    pl.col('diff_cumpct').get(pl.col('diff_cumpct').abs().arg_max()).alias('KS'),
                    (0.5 * (pl.col('B_cumpct') + pl.col('B_cumpct').shift(fill_value=0))
                         * pl.lit(0).append(pl.col('G_cumpct')).diff(null_behavior="drop")).sum().alias('AUC')
                )\
                .sort(all_seg_cols + ['target_nm', 'score_nm'])
    
    # hitrate
    st_hit_ls = []
    for seg_cols in seg_cols_ls:
        if len(seg_cols) == 0:
            st_hit = pl.concat(df.select(
                        target_nm=pl.lit(target_col, dtype=pl.String),
                        Tot_wgt_withnohit=pl.col(weight_col).filter(pl.col(target_col).is_in([0,1])).sum())
                       for target_col in target_cols)
            st_hit_ls.append(st_hit)
        else:
            st_hit = pl.concat(df.group_by(seg_cols).agg(
                        target_nm=pl.lit(target_col, dtype=pl.String),
                        Tot_wgt_withnohit=pl.col(weight_col).filter(pl.col(target_col).is_in([0,1])).sum())
                       for target_col in target_cols)
            st_hit_ls.append(st_hit)
    st_hit = pl.concat(st_hit_ls, how="diagonal")
    st_ks = st_ks.join(st_hit, on=all_seg_cols + ['target_nm'], how='left', validate='m:1', join_nulls=True)\
            .with_columns(hitrate = pl.col('Tot_wgt') / pl.col('Tot_wgt_withnohit'))
    
    st_ks_tmp = st_ks.with_columns(pl.col('G_cnt').max().over(all_seg_cols + ['target_nm']).alias('G_cnt'), 
                    pl.col('B_cnt').max().over(all_seg_cols + ['target_nm']).alias('B_cnt'))
    
    res = {'cnt':st_cnt, 'KS': st_ks}
    if dcast_params:
        for value_col, on_cols in dcast_params.items():
            index_cols = [_ for _ in all_seg_cols + ['target_nm', 'score_nm', 'B_cnt', 'G_cnt'] if _ not in on_cols]
            res[f'{value_col}_dcast'] = st_ks_tmp.pivot(on=on_cols, index=index_cols,
                                                    values=value_col)
    return res