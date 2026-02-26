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
    功能描述:
    - 

    参数:
    - good_pct: 
    - bad_pct: 

    返回值:
    - 

    关键规则:
    - 

    示例:
    - 

    实现说明(<=100字):
    - 
    """

    return (pl.col(good_pct)-pl.col(bad_pct))*woe_expr(good_pct, bad_pct)


def woe_expr(good_pct,bad_pct):
    """
    功能描述:
    - 

    参数:
    - good_pct: 
    - bad_pct: 

    返回值:
    - 

    关键规则:
    - 

    示例:
    - 

    实现说明(<=100字):
    - 
    """

    return (pl.col(good_pct).clip(MIN_WEIGHT, None) / pl.col(bad_pct).clip(MIN_WEIGHT, None)).log()


def _woe_table(df):
    """
    功能描述:
    - 

    参数:
    - df: 

    返回值:
    - 

    关键规则:
    - 

    示例:
    - 

    实现说明(<=100字):
    - 
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
    功能描述:
    - 

    参数:
    - wgt: 
    - pattern: 

    返回值:
    - 

    关键规则:
    - 

    示例:
    - 

    实现说明(<=100字):
    - 
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
    功能描述:
    - 

    参数:
    - df_woe: 
    - var_nm: 

    返回值:
    - 

    关键规则:
    - 

    示例:
    - 

    实现说明(<=100字):
    - 
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
    功能描述:
    - 

    参数:
    - df_part: 
    - x_cols: 
    - target_col: 
    - weight_col: 
    - num_bins: 
    - MV_dict: 
    - pattern_merge: 

    返回值:
    - 

    关键规则:
    - 

    示例:
    - 

    实现说明(<=100字):
    - 
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
    功能描述:
    - 

    参数:
    - good_pct: 
    - bad_pct: 

    返回值:
    - 

    关键规则:
    - 

    示例:
    - 

    实现说明(<=100字):
    - 
    """

    res=(good_pct-bad_pct)*(np.log(np.maximum(good_pct, MIN_WEIGHT)/np.maximum(bad_pct, MIN_WEIGHT)))
    return res


def woe(good_pct,bad_pct):
    """
    功能描述:
    - 

    参数:
    - good_pct: 
    - bad_pct: 

    返回值:
    - 

    关键规则:
    - 

    示例:
    - 

    实现说明(<=100字):
    - 
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
    """计算变量IV值。
    
    params:
        df: pl.DataFrame 数据表
        x_cols: list[str] 需要计算IV的变量，必须为数值型变量，因为目前不支持离散变量分箱。
        target_col: str 标签列
        weight_col: str|None 权重列。如果为None，则默认所有样本的权重为1
        seg_cols_ls: list[list[str]]|None 需要分组计算IV的列名
        num_bins: int 计算IV需要的分箱箱数
        MV_dict: dict[str, numeric]|None 特殊值映射表
    return: 
        st_woe: pl.DataFrame WoE表
        st_iv： pl.DataFrame IV表
    
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
    
    """根据主题计算iv分布
        :param iv_summary: pl.DataFrame 由summary_iv计算的iv结果
        :param org_class_col: str 机构大类分组
        :param var_name_col: str 变量名称列
        :param theme_col: str 变量主题列
        :param save_path: str 需要保存的文件路径
        
        :return iv_summary_cnt_output,iv_summary_pct_output：返回cnt和pct的iv分布计算结果
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
    """分机构大类计算TopIV中各主题的计数与占比。
    
    params:
        res_iv: pl.DataFrame
          summary_iv返回的IV计算结果
        top_pcts: list[float]
          需要划定的topIV百分比范围，例：top1%变量，top5%变量
        org_class_col: str
          机构大类分组
        var_name_col: str
          变量名称列
        theme_col: str 
          变量主题列
        save_path: str|None
          需要保存的文件路径。默认为None，不保存。
          
    return: pl.DataFrame
        topIV主题成分表   
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
