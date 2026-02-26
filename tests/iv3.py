"""20251117: 加入按趋势合并分箱功能"""
import numpy as np
import polars as pl
import polars.selectors as cs

import sys
sys.path.append(rf'D:\wise\A86\modeling_pl')

import uuid
from basic_stats import pl_quantile_wtd
from polars_common import adj_colorder, write_tables_to_excel

MIN_WEIGHT=0.001


def iv_expr(good_pct,bad_pct):

    """
    功能描述: 计算信息价值（IV）的Polars表达式。
    参数:
    - good_pct (str): 好样本占比列名
    - bad_pct (str): 坏样本占比列名
    返回值: Polars表达式对象，用于在DataFrame中计算IV列
    关键规则: 内部调用woe_expr计算WOE；适用于Polars的lazy或急切计算；不直接处理数据，需在select或with_columns中使用
    示例: `df.with_columns(iv=iv_expr('G_pct', 'B_pct'))`
    实现说明: 基于公式IV = (good_pct - bad_pct) * WOE实现。
    """
    return (pl.col(good_pct)-pl.col(bad_pct))*woe_expr(good_pct, bad_pct)


def woe_expr(good_pct,bad_pct):

    """
    功能描述: 计算优势比（WOE）的Polars表达式，并处理极小值防除零。
    参数:
    - good_pct (str): 好样本占比列名
    - bad_pct (str): 坏样本占比列名
    返回值: Polars表达式对象，用于计算WOE列
    关键规则: 使用clip将占比限制在MIN_WEIGHT以上（默认0.001），避免log(0)或除零错误；适用于Polars延迟计算
    示例: `df.with_columns(woe=woe_expr('G_pct', 'B_pct'))`
    实现说明: WOE = log(good_pct / bad_pct)，有下界保护。
    """
    return (pl.col(good_pct).clip(MIN_WEIGHT, None) / pl.col(bad_pct).clip(MIN_WEIGHT, None)).log()


def _woe_table(df):

    """
    功能描述: 为分箱基础统计DataFrame添加总权重、占比、WOE和IV列。
    参数:
    - df (polars.DataFrame): 包含至少'B_wgt'和'G_wgt'列的分箱表
    返回值: 添加了'Tot_wgt', 'B_pct', 'G_pct', 'Tot_pct', 'WoE', 'IV'列的新DataFrame
    关键规则: 列按顺序添加；依赖全局MIN_WEIGHT和woe_expr函数；输入通常由group_by聚合后得到
    示例: 输入分箱聚合后的DataFrame，输出完整WOE表
    实现说明: 链式调用with_columns逐步计算各衍生统计量。
    """
    return df.with_columns(
            Tot_wgt = pl.col('B_wgt') + pl.col('G_wgt'),
            B_pct = pl.col('B_wgt') / pl.col('B_wgt').sum(),
            G_pct = pl.col('G_wgt') / pl.col('G_wgt').sum())\
           .with_columns(Tot_pct = pl.col('Tot_wgt') / pl.col('Tot_wgt').sum())\
           .with_columns(WoE = woe_expr('G_pct', 'B_pct'))\
           .with_columns(IV=pl.col('WoE') * (pl.col('G_pct') - pl.col('B_pct')))


def pattern_bin_merge(wgt, pattern):

    """
    功能描述: 根据累积优势比（cumulative odds）趋势和指定模式合并相邻分箱的起始索引。
    参数:
    - wgt (np.ndarray): n行2列数组，第0列为好权重，第1列为坏权重
    - pattern (str): 合并模式，'A'表示希望坏占比下降（找cum odds最小点），'D'表示希望坏占比上升（找最大点），'AD'/'DA'为两阶段组合模式
    返回值: 合并后分箱的起始索引数组（numpy数组）
    关键规则: 使用numpy计算累积权重比；忽略除零警告（np.seterr）；模式'AD'先按A后按D，'DA'先按D后按A；返回索引对应合并后分箱的第一个原始索引位置
    示例: `indices = pattern_bin_merge(wgt_array, 'A')`
    实现说明: 对剩余段计算cum odds，根据模式寻找极值点作为合并边界，循环直至处理完所有行。
    """
    np.seterr(divide="ignore")
    start_idx=0
    n=len(wgt)
    fine_bin_groups=[]
    while start_idx<n:
        cum_odds=wgt[start_idx:n,0].cumsum()/wgt[start_idx:n,1].cumsum()
        if pattern in ["A","AD"]:
            end_idx=np.argmin(cum_odds)
        elif pattern in ["D","DA"]:
            end_idx=np.argmax(cum_odds)
        else:
            raise(ValueError("No such pattern."))
        fine_bin_groups.append(range(start_idx,start_idx+end_idx+1))
        start_idx+=end_idx+1
    if pattern in ["AD","DA"] and len(fine_bin_groups)>1:
        start_idx=fine_bin_groups[-1][0]
        del fine_bin_groups[-1]
        while start_idx<n:
            cum_odds=wgt[start_idx:n,0].cumsum()/wgt[start_idx:n,1].cumsum()
            end_idx=np.argmax(cum_odds) if pattern =="AD" else np.argmin(cum_odds)
            fine_bin_groups.append(range(start_idx,start_idx+end_idx+1))
            start_idx+=end_idx+1

    indices=np.array([x[0] for x in fine_bin_groups])
    np.seterr(divide="warn")
    
    return indices


def _pattern_bin_merge(df_woe, var_nm):

    """
    功能描述: 对单个变量的分箱表执行基于趋势的自动合并优化，并选择使总IV最大的模式。
    参数:
    - df_woe (polars.DataFrame): 变量分箱表，需含'G_wgt','B_wgt','is_mv','bin'等列
    - var_nm (str): 变量名，用于输出标记
    返回值: 合并优化后的分箱表（DataFrame），列结构类似输入但bin可能合并，添加var_nm和bin_idx列
    关键规则: 仅处理正常分箱（is_mv=False）；尝试模式['A','D']，计算合并后总IV，选择最大者；缺失分箱（is_mv=True）保持不变；重建bin为区间字符串；输出表按grp排序
    示例: 输入原始分箱表，返回趋势合并后分箱
    实现说明: 提取权重数组，调用pattern_bin_merge，按合并索引分组聚合统计量，重新分配bin标签，拼接缺失分箱。
    """
    mv_bin = df_woe.filter(pl.col('is_mv'))
    normal_bin = df_woe.filter(~pl.col('is_mv'))
    if normal_bin.height == 0:
        return df_woe
    
    wgt = normal_bin.select(['G_wgt', 'B_wgt']).to_numpy()
    
    iv_vals=[]
    ids = []
#     pattern_all= ["A","D","AD","DA"]
    pattern_all = ['A', 'D']
    for pattern in pattern_all:
        id_new=pattern_bin_merge(wgt,pattern)
        ids.append(id_new)
        wgt_new=np.add.reduceat(wgt, id_new)
        iv_val=iv(wgt_new[:,0]/wgt_new[:,0].sum(),wgt_new[:,1]/wgt_new[:,1].sum()).sum()
        iv_vals.append(iv_val)
        
    idx=np.argmax(iv_vals)
    normal_bin_new = normal_bin.with_columns(low=pl.col('bin').str.extract('\[(-?\d+(?:\.\d+)?)').cast(pl.Float64).fill_null(-np.inf),
                                grp=pl.arange(pl.len()).cut(ids[idx], left_closed=True))\
                      .group_by('grp').agg(
                                cs.by_name(['G_cnt', 'B_cnt', 'G_wgt', 'B_wgt']).sum(),
                                is_mv=pl.col('is_mv').first(),
                                low=pl.col('low').min())\
                      .sort('grp')
    breaks = normal_bin_new.filter(pl.col('low').is_finite())['low']
    normal_bin_new = normal_bin_new.with_columns(bin=pl.col('low').cut(breaks, left_closed=True))\
                         .drop(['low', 'grp'])
    df_new = pl.concat([mv_bin, normal_bin_new], how='diagonal_relaxed')\
            .with_columns(var_nm=pl.lit(var_nm),
                     bin_idx=pl.arange(pl.len()))
    return df_new


def bin_table(df_part, 
          x_cols, 
          target_col, 
          weight_col,
          num_bins,
          MV_dict,
          pattern_merge):

    """
    功能描述: 为数据子集计算多个变量的分箱统计表（含WOE/IV），支持缺失值映射、等频分箱和趋势合并。
    参数:
    - df_part (polars.DataFrame): 输入数据子集
    - x_cols (list[str]): 需分箱的变量列表
    - target_col (str): 目标变量列名（取值0/1）
    - weight_col (str): 样本权重列名
    - num_bins (int): 分箱数，用于等频切分
    - MV_dict (dict): 缺失值到分箱标签的映射，例如{np.nan: 'MV00', -999: 'MV99'}
    - pattern_merge (bool): 是否按趋势合并分箱
    返回值: 合并所有变量的分箱表（DataFrame），包含列：bin, B_cnt, G_cnt, B_wgt, G_wgt, is_mv, WoE, IV, var_nm, bin_idx等
    关键规则: 仅对x_col大于0的观测使用pl_quantile_wtd计算等频断点；缺失值按MV_dict指定分箱；若pattern_merge=True，则调用_pattern_bin_merge进一步合并；每个变量独立处理，最终concat
    示例: `bin_table(df, ['age','income'], 'bad', weight_col='w', num_bins=10, MV_dict={}, pattern_merge=True)`
    实现说明: 为每个变量并行创建两个lazy frame（MV和正常），分别处理分箱和聚合，合并后pipe _woe_table，最后可选趋势合并。
    """
    probs = np.arange(1/num_bins, 1, 1/num_bins)
    # x_col非负变量
    breaks_ls = pl.collect_all([pl_quantile_wtd(df_part.lazy()
                                      .filter(pl.col(x_col).gt(0)),
                                  x_col, weight_col, probs)
                       for x_col in x_cols])
    breaks_ls = [np.sort(np.unique(_['quantile'].to_list() + [0])) for _ in breaks_ls]


    lazy_jobs = []
    for i, x_col in enumerate(x_cols):
        cond_mv = pl.col(x_col).is_null()|pl.col(x_col).is_in(MV_dict.keys())
        df_mv = df_part.lazy()\
                  .select([x_col, target_col, weight_col])\
                   .filter(cond_mv)\
                   .with_columns(bin=pl.col(x_col).replace_strict(MV_dict, default=None)
                                           .fill_null('MV00'))\
                   .group_by('bin')\
                   .agg(
                    B_cnt=(pl.col(target_col)==1).sum(),
                    G_cnt=(pl.col(target_col)==0).sum(),
                    B_wgt=(pl.col(weight_col).filter(pl.col(target_col)==1)).sum(),
                    G_wgt=(pl.col(weight_col).filter(pl.col(target_col)==0)).sum())\
                   .sort('bin')\
                   .with_columns(is_mv=pl.lit(True))

        df_normal = df_part.lazy()\
                     .select([x_col, target_col, weight_col])\
                      .filter(~cond_mv)\
                      .with_columns(bin=pl.col(x_col).cut(breaks_ls[i], left_closed=True))\
                      .group_by('bin')\
                      .agg(
                        B_cnt=(pl.col(target_col)==1).sum(),
                        G_cnt=(pl.col(target_col)==0).sum(),
                        B_wgt=(pl.col(weight_col).filter(pl.col(target_col)==1)).sum(),
                        G_wgt=(pl.col(weight_col).filter(pl.col(target_col)==0)).sum())\
                      .sort('bin')\
                      .with_columns(is_mv=pl.lit(False),
                               bin=pl.col('bin').cast(pl.String))

        df_woe_lazy = pl.concat([df_mv, df_normal])\
                   .pipe(_woe_table)\
                   .with_columns(var_nm=pl.lit(x_col, dtype=pl.String),
                            bin_idx=pl.arange(pl.len()))
        lazy_jobs.append(df_woe_lazy)
    st_woe = pl.concat(pl.collect_all(lazy_jobs))

    # 按趋势合并分箱
    if pattern_merge:
        st_woe_merged = []
        for (var_nm, ), df_bin in st_woe.group_by('var_nm'):
            st_woe_merged.append(df_bin.pipe(_pattern_bin_merge, var_nm).pipe(_woe_table))
        st_woe = pl.concat(st_woe_merged)

    return st_woe


def iv(good_pct,bad_pct):

    """
    功能描述: 计算信息价值（IV），支持标量或数组输入。
    参数:
    - good_pct (float or np.ndarray): 好样本占比
    - bad_pct (float or np.ndarray): 坏样本占比
    返回值: IV值，形状与输入相同
    关键规则: 使用np.maximum将输入限制在MIN_WEIGHT（0.001）以上，防止log(0)或除零；公式IV = (good - bad) * log(good / bad)
    示例: `iv(0.6, 0.2)` 或 `iv(np.array([0.3,0.5]), np.array([0.1,0.2]))`
    实现说明: 数值安全计算，避免下溢。
    """
    res=(good_pct-bad_pct)*(np.log(np.maximum(good_pct, MIN_WEIGHT)/np.maximum(bad_pct, MIN_WEIGHT)))
    return res


def woe(good_pct,bad_pct):

    """
    功能描述: 计算优势比（WOE），支持标量或数组输入。
    参数:
    - good_pct (float or np.ndarray): 好样本占比
    - bad_pct (float or np.ndarray): 坏样本占比
    返回值: WOE值，形状与输入相同
    关键规则: 使用np.maximum限制最小值MIN_WEIGHT；WOE = log(good / bad)
    示例: `woe(0.6, 0.2)`
    实现说明: 对数变换比值，有下界保护。
    """
    woe_val=(np.log(np.maximum(good_pct, MIN_WEIGHT)/np.maximum(bad_pct, MIN_WEIGHT)))
    return woe_val


def summary_iv(df, 
          x_cols, 
          target_col, 
          weight_col=None, 
          seg_cols_ls=None, 
          num_bins=10, 
          MV_dict=None):
    
    """
    功能描述: 批量计算多个变量的IV值及其详细分箱信息，支持按分段字段分组处理。
    参数:
    - df (polars.DataFrame): 源数据
    - x_cols (list[str]): 需计算IV的变量列表
    - target_col (str): 目标列（0/1）
    - weight_col (str, optional): 权重列，默认None则添加均匀权重列
    - seg_cols_ls (list[list[str]], optional): 分段字段组合列表，每个内列表指定一个分组方式；默认None则整体计算
    - num_bins (int): 分箱数，默认10
    - MV_dict (dict): 缺失值映射，默认空字典
    返回值: (st_woe, st_iv) 元组，st_woe为所有分段所有变量的分箱明细表，st_iv为各变量IV汇总表
    关键规则: 若weight_col为None，生成UUID列作为权重；若seg_cols_ls为None，创建虚拟分组列；每个分段组合独立调用bin_table（pattern_merge=True）；最终合并所有结果，按all_seg_cols + ['var_nm']排序；若使用虚拟分组则自动丢弃该列。注意：当seg_cols为空列表时，调用未定义的calc_woe函数，可能为错误，待确认。
    示例: `woe_tbl, iv_tbl = summary_iv(df, num_vars, 'bad', weight_col='w', seg_cols_ls=[['region']], num_bins=10)`
    实现说明: 遍历seg_cols_ls，对每个分段组合调用bin_table，拼接明细，按变量分组求和IV，调整列顺序并排序。
    """
    if MV_dict is None:
        MV_dict = dict()
        
    if weight_col is None:
        weight_col = f'weight_{str(uuid.uuid4())}'
        df = df.with_columns(pl.lit(1).alias(weight_col))
        
    if seg_cols_ls is None:
        group_col = f'group_{str(uuid.uuid4())}'
        df = df.with_columns(pl.lit(1).alias(group_col))
        seg_cols_ls = [[group_col]]
        drop_group_col = True
    else:
        drop_group_col = False
    
    st_woe_ls = []
    
    df = df.filter(pl.col(target_col).is_in([0,1]))
    for seg_cols in seg_cols_ls:
        if len(seg_cols) == 0:
            st_woe = calc_woe(df, x_cols, target_col, weight_col)
            st_woe_ls.append(st_woe)
        else:
            for seg_nms, df_part in df.group_by(seg_cols):
                st_woe = bin_table(df_part, 
                             x_cols, 
                              target_col=target_col, 
                              weight_col=weight_col,
                              num_bins=num_bins,
                              MV_dict=MV_dict,
                              pattern_merge=True)
                st_woe = st_woe.with_columns(pl.lit(grp_nm, dtype=df.schema[seg_nm]).alias(seg_nm) for seg_nm, grp_nm in zip(seg_cols, seg_nms))
                st_woe_ls.append(st_woe)
    st_woe = pl.concat(st_woe_ls, how="diagonal")
    
    # IV
    all_seg_cols = []
    for seg_cols in seg_cols_ls:
        for x in seg_cols:
            if x not in all_seg_cols:
                all_seg_cols.append(x)
    st_woe = adj_colorder(st_woe, all_seg_cols + ['var_nm', 'bin_idx'], insert_first=True)
    st_woe = st_woe.sort(all_seg_cols + ['var_nm', 'bin_idx'])
    st_iv = st_woe.group_by(all_seg_cols + ['var_nm'])\
                  .agg(pl.col('IV').sum())\
                  .sort(all_seg_cols + ['var_nm'])
    
    if drop_group_col:
        st_woe = st_woe.drop(all_seg_cols)
        st_iv = st_iv.drop(all_seg_cols)
    
    return st_woe, st_iv


def summary_iv_distribution(iv_summary,
                   org_class_col,
                   var_name_col,
                   theme_col,
                   save_path=None):
    
    """
    功能描述: 基于IV汇总表分析IV值分布，统计各机构分类在不同IV区间的变量数量及占比。
    参数:
    - iv_summary (polars.DataFrame): IV汇总表，需包含IV列及指定的主题、机构、变量名列
    - org_class_col (str): 机构分类列名
    - var_name_col (str): 变量名列名
    - theme_col (str): 主题列名
    - save_path (str, optional): 保存结果Excel的路径，默认None不保存
    返回值: (cnt_tbl, pct_tbl) 两个透视表，分别为变量计数和占比，机构分类为行，IV区间为列
    关键规则: IV区间固定为[0,0.05,0.1,0.15,0.2,0.25,0.3,0.35,0.4,0.5]，左闭右开；先按(theme, org_class, var_name)求IV均值，再分区间；百分比起源于区间内变量数除以该机构在主题下的总变量数
    示例: `cnt_tbl, pct_tbl = summary_iv_distribution(iv_df, 'org_type','var_name','theme', save_path='output.xlsx')`
    实现说明: 计算每个变量的平均IV，cut分区间，分组计数并透视，生成机构在IV区间的变量分布。
    """
    breaks = [0,0.05,0.1,0.15,0.2,0.25,0.3,0.35,0.4,0.5]
    iv_summary = iv_summary.with_columns(IV_range = pl.col('IV').cut(breaks, left_closed=True))
    
    iv_summary_cnt=iv_summary.group_by([theme_col,org_class_col,var_name_col]).agg(pl.col('IV').mean())\
                            .with_columns( IV_range = pl.col('IV').cut(breaks, left_closed=True))\
                            .group_by([theme_col,org_class_col,'IV_range']).agg(cnt = pl.col('IV').len())\
                            .sort([theme_col,org_class_col,'IV_range'])\
                            .pivot(index = [theme_col,'IV_range'], on=org_class_col, values='cnt').fill_null(0)
    
    iv_summary_cnt_output=iv_summary_cnt.unpivot(cs.numeric(),index=[theme_col,"IV_range"],variable_name='机构分类',value_name='cnt')\
                                        .pivot(on=theme_col,index=['机构分类', 'IV_range'],values='cnt')\
                                        .sort(['机构分类', 'IV_range'])\
                                        .with_columns(pl.col("IV_range").cast(pl.String)).fill_null(0)
    
    iv_summary_pct=iv_summary.group_by([theme_col,org_class_col,var_name_col]).agg(pl.col('IV').mean())\
                            .with_columns( IV_range = pl.col('IV').cut(breaks, left_closed=True))\
                            .group_by([theme_col,org_class_col,'IV_range']).agg(cnt = pl.col('IV').len())\
                            .with_columns(ratio = pl.col('cnt')/pl.col('cnt').sum().over([theme_col,org_class_col]))\
                            .sort([theme_col,org_class_col,'IV_range'])\
                            .pivot(index = [theme_col,'IV_range'], on=org_class_col, values='ratio').fill_null(0)

    iv_summary_pct_output=iv_summary_pct.unpivot(cs.numeric(), index=[theme_col,"IV_range"],variable_name='机构分类',value_name='pct')\
                                      .pivot(on=theme_col,index=['机构分类', 'IV_range'],values='pct')\
                                      .sort(['机构分类', 'IV_range'])\
                                      .with_columns(pl.col("IV_range").cast(pl.String)).fill_null(0)

    df_dict = {\
               'pct_output': iv_summary_pct_output,\
               'cnt_output': iv_summary_cnt_output,\
              }
    if save_path is not None:
        write_tables_to_excel(df_dict,save_path)
    
    return iv_summary_cnt_output,iv_summary_pct_output


def summary_iv_top_distribution(res_iv,
                      top_pcts,
                      org_class_col,
                      var_name_col,
                      theme_col,
                      save_path=None):

    """
    功能描述: 评估每个机构分类中IV值位于指定顶部百分位的变量数量、占比及其最低IV阈值。
    参数:
    - res_iv (polars.DataFrame): IV汇总表
    - top_pcts (list[float]): 顶部百分比列表，如[0.2,0.1]表示前20%和前10%
    - org_class_col (str): 机构分类列名
    - var_name_col (str): 变量名列名
    - theme_col (str): 主题列名
    - save_path (str, optional): 保存结果Excel路径，默认None
    返回值: dict，键为'topX%'，值为对应统计表，包含列：org_class_col, theme_col, cnt, pct, iv_threshold
    关键规则: 对每个top_pct，按机构分别计算IV的(1-pct)分位数作为阈值；筛选IV>=阈值的变量；统计每个(机构,主题)的变量数及占比（占该机构总变量数）；输出按机构和变量数降序排列
    示例: `result = summary_iv_top_distribution(iv_df, [0.2,0.5], 'org','var','theme')`
    实现说明: 遍历top_pcts，使用窗口函数quantile计算阈值，过滤后按机构主题聚合，计算占比和最低IV。
    """
    res = dict()
    for pct in top_pcts:  
        res[f'top{int(pct*100)}%'] = res_iv.group_by([org_class_col, theme_col,var_name_col]).agg(pl.col('IV').mean())\
                                 .with_columns(qtl=pl.col('IV').quantile(1 - pct).over(org_class_col))\
                                 .filter(pl.col('IV').ge(pl.col('qtl')))\
                                 .group_by([org_class_col,theme_col])\
                                 .agg(cnt=pl.len(),iv_threshold=pl.col('IV').min())\
                            .with_columns(pct=pl.col('cnt')/pl.col("cnt").sum().over(org_class_col))\
                            .sort([org_class_col,theme_col],descending=True)\
                            .select([org_class_col,theme_col,"cnt","pct","iv_threshold"])\
                            .sort([org_class_col,"cnt"],descending=True)
        
    if save_path is not None:
        write_tables_to_excel(res,save_path)  
    
    return res
