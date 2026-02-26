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
    功能描述: 该函数返回一个Polars表达式，用于计算信息值（IV），基于好样本百分比和坏样本百分比。
    参数:
    - good_pct (str): 好样本百分比的列名
    - bad_pct (str): 坏样本百分比的列名
    返回值: pl.Expr: 计算IV的Polars表达式
    关键规则: IV = (G_pct - B_pct) * WOE，其中WOE由woe_expr计算；输入百分比列应为正数。
    示例: iv_expr('G_pct', 'B_pct')
    实现说明: 调用woe_expr并乘以差值，无额外逻辑。
    """
    return (pl.col(good_pct)-pl.col(bad_pct))*woe_expr(good_pct, bad_pct)


def woe_expr(good_pct,bad_pct):

    """
    功能描述: 该函数返回一个Polars表达式，用于计算证据权重（WOE），基于好样本百分比和坏样本百分比。
    参数:
    - good_pct (str): 好样本百分比的列名
    - bad_pct (str): 坏样本百分比的列名
    返回值: pl.Expr: 计算WOE的Polars表达式
    关键规则: 百分比被裁剪到MIN_WEIGHT（0.001）以避免除零或log(0)；WOE = log(G_pct / B_pct)。
    示例: woe_expr('G_pct', 'B_pct')
    实现说明: 计算好/坏百分比比并取log，使用clip确保最小值。
    """
    return (pl.col(good_pct).clip(MIN_WEIGHT, None) / pl.col(bad_pct).clip(MIN_WEIGHT, None)).log()


def _woe_table(df):

    """
    功能描述: 为分箱DataFrame添加计算列，包括总权重、百分比、WOE和IV。
    参数:
    - df (polars.DataFrame): 包含'B_wgt'和'G_wgt'列的分箱数据。
    返回值: polars.DataFrame: 添加了'Tot_wgt', 'B_pct', 'G_pct', 'Tot_pct', 'WoE', 'IV'列的DataFrame。
    关键规则: 基于B_wgt和G_wgt计算百分比；使用woe_expr计算WoE；IV = WoE * (G_pct - B_pct)。
    示例: _woe_table(df)
    实现说明: 链式调用with_columns添加各列，使用Polars表达式高效计算。
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
    功能描述: 根据指定模式合并分箱，基于累积好/坏权重比。
    参数:
    - wgt (np.ndarray): 形状(n,2)的数组，第一列为好权重，第二列为坏权重。
    - pattern (str): 合并模式，支持'A'（上升趋势）、'D'（下降趋势）、'AD'、'DA'。
    返回值: np.ndarray: 合并后的分箱起始索引数组。
    关键规则: 模式'A'找最小累积比，'D'找最大；'AD'和'DA'是组合模式；处理除零错误。
    示例: pattern_bin_merge(wgt, 'A')
    实现说明: 循环计算累积好/坏比，根据模式用argmin/argmax找合并点，使用np.seterr处理除零警告。
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
    功能描述: 合并正常分箱基于趋势，使用pattern_bin_merge，并保留缺失值分箱。
    参数:
    - df_woe (polars.DataFrame): 分箱表，包含'G_wgt', 'B_wgt', 'is_mv', 'bin'等列。
    - var_nm (str): 变量名。
    返回值: polars.DataFrame: 合并后的分箱表，包含更新后的分箱。
    关键规则: 分离is_mv为真和假的分箱；对正常分箱尝试模式'A'和'D'，选择使总IV最大的模式；重新分组基于区间下界；合并回缺失值分箱。
    示例: _pattern_bin_merge(df_woe, 'age')
    实现说明: 提取正常分箱，运行pattern_bin_merge，基于low值cut重新定义bin，concat回MV分箱。
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
    功能描述: 为多个变量创建分箱表，计算每个分箱的计数和权重，并可选按趋势合并。
    参数:
    - df_part (polars.DataFrame): 输入数据部分。
    - x_cols (list of str): 要分箱的变量名列表。
    - target_col (str): 目标列名（0/1）。
    - weight_col (str): 权重列名。
    - num_bins (int): 分箱数。
    - MV_dict (dict): 缺失值映射，如{缺失值: 'MV标签'}。
    - pattern_merge (bool): 是否按趋势合并分箱。
    返回值: polars.DataFrame: 所有变量的分箱表，列包括'var_nm', 'bin_idx', 'B_cnt', 'G_cnt', 'B_wgt', 'G_wgt', 'is_mv', 'bin'等。
    关键规则: 非负变量使用加权分位数分箱；MV_dict处理特定缺失值；如果pattern_merge为真，调用_pattern_bin_merge合并；分箱基于左闭区间。
    示例: bin_table(df, ['x1','x2'], 'target', 'weight', 10, {}, True)
    实现说明: 对每个变量，分离MV和正常数据，正常数据用cut分箱，应用_woe_table，可选合并。
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
    功能描述: 计算信息值（IV）的数值版本，基于好样本百分比和坏样本百分比。
    参数:
    - good_pct (float or np.ndarray): 好样本百分比。
    - bad_pct (float or np.ndarray): 坏样本百分比。
    返回值: float or np.ndarray: 计算的IV值。
    关键规则: 使用MIN_WEIGHT裁剪输入以避免log(0)或除零；IV = (good_pct - bad_pct) * log(good_pct / bad_pct)。
    示例: iv(0.3, 0.1)
    实现说明: 直接应用公式，使用np.maximum确保最小值。
    """
    res=(good_pct-bad_pct)*(np.log(np.maximum(good_pct, MIN_WEIGHT)/np.maximum(bad_pct, MIN_WEIGHT)))
    return res


def woe(good_pct,bad_pct):
   

    """
    功能描述: 计算证据权重（WOE）的数值版本，基于好样本百分比和坏样本百分比。
    参数:
    - good_pct (float or np.ndarray): 好样本百分比。
    - bad_pct (float or np.ndarray): 坏样本百分比。
    返回值: float or np.ndarray: 计算的WOE值。
    关键规则: 使用MIN_WEIGHT裁剪输入；WOE = log(good_pct / bad_pct)。
    示例: woe(0.3, 0.1)
    实现说明: 计算比并取log，使用np.maximum。
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
    功能描述: 计算多个变量的IV摘要，可选分段处理，返回详细分箱表和IV汇总。
    参数:
    - df (polars.DataFrame): 输入数据。
    - x_cols (list of str): 变量列表。
    - target_col (str): 目标列名（0/1）。
    - weight_col (str, optional): 权重列名，默认生成均匀权重。
    - seg_cols_ls (list of list of str, optional): 分段列列表，每个元素是分段列的子列表，用于分组计算。
    - num_bins (int): 分箱数，默认10。
    - MV_dict (dict, optional): 缺失值映射。
    返回值: tuple of (polars.DataFrame, polars.DataFrame): 第一个是详细分箱表（st_woe），第二个是IV汇总表（st_iv）。
    关键规则: 如果weight_col为None，生成uuid权重列；如果seg_cols_ls为None，创建单分组；目标列必须为0/1；当seg_cols为空时，调用calc_woe函数（未定义，可能存在错误），否则调用bin_table；调整列顺序并排序。
    示例: summary_iv(df, ['x1','x2'], 'target', num_bins=5)
    实现说明: 遍历分段，对每个分段调用bin_table，然后group_by汇总IV；使用adj_colorder调整列顺序。注意calc_woe未定义，需确认。
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
    功能描述: 基于IV摘要创建分布表，按IV范围分组，计算各机构分类的计数和百分比，可输出Excel。
    参数:
    - iv_summary (polars.DataFrame): IV汇总表，必须包含'IV'列。
    - org_class_col (str): 机构分类列名。
    - var_name_col (str): 变量名列名。
    - theme_col (str): 主题列名。
    - save_path (str, optional): Excel文件保存路径。
    返回值: tuple of (polars.DataFrame, polars.DataFrame): 第一个是计数输出（iv_summary_cnt_output），第二个是百分比输出（iv_summary_pct_output）。
    关键规则: IV范围使用预定义breaks；先按theme_col、org_class_col、var_name_col分组取IV均值，然后按IV范围分组；数据透视和取消透视重塑；如果save_path提供，写入Excel。
    示例: summary_iv_distribution(iv_df, 'org', 'var', 'theme', 'output.xlsx')
    实现说明: 使用cut将IV分箱，group_by聚合，pivot/unpivot转换格式，write_tables_to_excel保存。
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
    功能描述: 计算顶部变量IV分布，基于分位数阈值，筛选每个机构分类中IV最高的变量。
    参数:
    - res_iv (polars.DataFrame): IV汇总表，必须包含'IV'列。
    - top_pcts (list of float): 顶部百分比列表，如[0.1, 0.2]。
    - org_class_col (str): 机构分类列名。
    - var_name_col (str): 变量名列名。
    - theme_col (str): 主题列名。
    - save_path (str, optional): Excel文件保存路径。
    返回值: dict: 键为'topX%'（X为百分比整数），值为polars.DataFrame，包含计数、百分比、IV阈值等。
    关键规则: 对每个top_pct，按org_class_col分组计算IV分位数阈值，筛选IV大于等于阈值的变量，然后按theme_col分组计数和计算百分比；结果按org_class_col和theme_col排序。
    示例: summary_iv_top_distribution(iv_df, [0.1], 'org', 'var', 'theme')
    实现说明: 循环top_pcts，使用quantile over分组，过滤，group_by聚合，最后可写入Excel。
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
