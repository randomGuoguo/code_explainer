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
    创建一个polars表达式，计算信息值（IV）。
    参数:
    good_pct: str, 好样本百分比的列名
    bad_pct: str, 坏样本百分比的列名
    返回值:
    pl.Expr: IV表达式，公式为 (good_pct - bad_pct) * woe_expr(good_pct, bad_pct)。
    关键规则:
    IV计算依赖于woe_expr，后者使用clip确保权重不低于MIN_WEIGHT（0.001）。
    示例:
    df.with_columns(IV=iv_expr('G_pct', 'B_pct'))
    实现说明:
    直接组合good_pct和bad_pct的差与WOE表达式。无复杂逻辑。
    """
    return (pl.col(good_pct)-pl.col(bad_pct))*woe_expr(good_pct, bad_pct)


def woe_expr(good_pct,bad_pct):

    """
    功能描述:
    创建一个polars表达式，计算证据权重（WOE）。
    参数:
    good_pct: str, 好样本百分比的列名
    bad_pct: str, 坏样本百分比的列名
    返回值:
    pl.Expr: WOE表达式，公式为 log(good_pct / bad_pct)，其中good_pct和bad_pct已通过clip限制最小值为MIN_WEIGHT。
    关键规则:
    使用clip将good_pct和bad_pct下限设为MIN_WEIGHT=0.001，确保比值有效且log有定义。
    示例:
    df.with_columns(WoE=woe_expr('G_pct', 'B_pct'))
    实现说明:
    通过clip和log计算比值。clip应用于good和bad百分比列。
    """
    return (pl.col(good_pct).clip(MIN_WEIGHT, None) / pl.col(bad_pct).clip(MIN_WEIGHT, None)).log()


def _woe_table(df):

    """
    功能描述:
    内部函数，为分箱DataFrame添加总权重、百分比、WOE和IV列。
    参数:
    df: pl.DataFrame, 包含分箱统计的DataFrame，必须至少列：'B_wgt', 'G_wgt'。
    返回值:
    pl.DataFrame: 添加了'Tot_wgt', 'B_pct', 'G_pct', 'Tot_pct', 'WoE', 'IV'列的新DataFrame。
    关键规则:
    百分比基于对应类别的总权重计算；IV使用iv_expr计算，确保数值稳定性。
    示例:
    通常在bin_table或_pattern_bin_merge中pipe调用：df.pipe(_woe_table)。
    实现说明:
    链式调用with_columns逐步计算：先加Tot_wgt、B_pct、G_pct，再加Tot_pct，然后WoE用woe_expr，最后IV。
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
    根据指定模式合并分箱，基于累积优势比（cumulative odds）的变化来确定合并点。
    参数:
    wgt: np.ndarray, 形状为(n,2)的数组，第一列为G_wgt，第二列为B_wgt。
    pattern: str, 合并模式，可选'A', 'D', 'AD', 'DA'。
    返回值:
    np.ndarray: 合并后的分箱起始索引数组，每个索引对应一个新分箱的起始行号。
    关键规则:
    - 模式'A'或'AD'：寻找cum_odds的最小值点作为合并边界。
    - 模式'D'或'DA'：寻找cum_odds的最大值点。
    - 'AD'模式：先正向合并（A模式）剩余部分，再反向合并（D模式）。
    - 'DA'模式：先正向合并（D模式）再反向合并（A模式）。
    示例:
    假设wgt为[[1,2],[3,4],[5,6]]，模式'A'：计算cum_odds = [0.5, (1+3)/(2+4)=0.667, (1+3+5)/(2+4+6)=0.667]，最小值在索引0，所以第一个分箱从0到0；然后从1开始，cum_odds=[4/6=0.667, (4+?)/?]，等等。
    实现说明:
    使用numpy计算累积和与比值，用argmin/argmax找合并点。循环处理直到所有行分配完毕。对于AD/DA模式，先处理一般部分，再对剩余部分反向处理。
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
    内部函数，应用pattern_bin_merge到单个变量的分箱表，通过尝试不同合并模式选择最优（最大化IV）的合并结果。
    参数:
    df_woe: pl.DataFrame, 单个变量的分箱表，必须包含列：'G_wgt', 'B_wgt', 'is_mv', 'bin'（分箱标签）。
    var_nm: str, 变量名，用于输出列。
    返回值:
    pl.DataFrame: 合并后的分箱表，列包括：var_nm, bin_idx, 以及合并后的统计列（G_cnt, B_cnt, G_wgt, B_wgt, is_mv, bin）。分箱数减少（如果合并发生）。
    关键规则:
    - 分离缺失值分箱（is_mv=True）和正常分箱（is_mv=False）。
    - 对正常分箱，提取权重数组，尝试模式'A'和'D'，计算合并后总IV，选择IV最大的模式对应的索引。
    - 根据索引重新分组：将正常分箱按切割点分组，聚合统计量（和），并提取最低下限（low）重建分箱区间。
    - 合并缺失值分箱回结果，并添加var_nm和bin_idx列。
    示例:
    在bin_table的pattern_merge步骤中自动调用，无需手动示例。
    实现说明:
    调用pattern_bin_merge获取合并索引；使用np.add.reduceat聚合权重；计算IV比较。使用pl的cut和group_by重建分箱区间和统计。最后concatenate缺失值分箱。
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
    为多个变量计算加权分箱表，包括缺失值处理和可选的趋势合并。
    参数:
    df_part: pl.DataFrame, 输入数据子集。
    x_cols: list[str], 需要分箱的变量列名列表。
    target_col: str, 目标变量列名（二分类，0/1）。
    weight_col: str, 权重列名。
    num_bins: int, 正常值的目标分箱数（近似，实际可能因数据分布而异）。
    MV_dict: dict, 缺失值映射，键为特殊值（如-999），值为分箱标签（字符串）。空字典表示无特殊缺失值映射。
    pattern_merge: bool, 是否启用按趋势合并分箱（使用pattern_bin_merge优化IV）。
    返回值:
    pl.DataFrame: 所有变量的分箱明细表，列包括：var_nm, bin_idx, bin（分箱标签），G_cnt, B_cnt, G_wgt, B_wgt, is_mv, IV, WoE等。按var_nm和bin_idx排序。
    关键规则:
    - 正常值分箱：首先使用加权分位数（pl_quantile_wtd）对正数（>0）计算切分点，切分点包括0，然后使用cut将数据分配到分箱。注意：0值会进入第一个分箱（因为breaks包含0）。
    - 缺失值处理：根据MV_dict将特定值映射到指定分箱；null值映射到'MV00'。
    - 分箱统计：每个分箱计算好样本和坏样本的计数和权重。
    - WOE/IV计算：通过_woe_table自动添加。
    - 合并：若pattern_merge=True，对每个变量调用_pattern_bin_merge进行趋势合并（尝试A和D模式，选IV最大）。
    示例:
    通常由summary_iv调用：st_woe = bin_table(df_part, x_cols, 'target', 'weight', num_bins=10, MV_dict={-999: 'Missing'}, pattern_merge=True)。
    实现说明:
    对每个变量并行（lazy）计算：先构建缺失值分箱的lazy DataFrame，再构建正常值分箱的lazy DataFrame，合并后pipe _woe_table。收集所有变量后，若启用合并，则按变量分组并应用_pattern_bin_merge。返回concatenated DataFrame。
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
    计算信息值（IV）的数值，给定好样本和坏样本的百分比。
    参数:
    good_pct: array-like, 好样本百分比（或比例），可以是标量、列表或数组。
    bad_pct: array-like, 坏样本百分比，形状与good_pct广播兼容。
    返回值:
    float or np.ndarray: IV值，形状与输入广播后相同。公式：IV = (good_pct - bad_pct) * log(good_pct / bad_pct)。
    关键规则:
    使用np.maximum将输入限制至少为MIN_WEIGHT（0.001），以避免log(0)或除零错误。这是逐元素操作。
    示例:
    iv(0.6, 0.3) ≈ (0.6-0.3)*log(0.6/0.3)=0.3*log(2)=0.3*0.693=0.208
    iv([0.6,0.4], [0.3,0.7]) 返回数组。
    实现说明:
    简单向量化计算：先计算比值，取log，再乘以差。使用np.maximum确保下界。
    """
    res=(good_pct-bad_pct)*(np.log(np.maximum(good_pct, MIN_WEIGHT)/np.maximum(bad_pct, MIN_WEIGHT)))
    return res


def woe(good_pct,bad_pct):

    """
    功能描述:
    计算证据权重（WOE）的数值，给定好样本和坏样本的百分比。
    参数:
    good_pct: array-like, 好样本百分比。
    bad_pct: array-like, 坏样本百分比。
    返回值:
    float or np.ndarray: WOE值，形状与输入广播后相同。公式：WOE = log(good_pct / bad_pct)。
    关键规则:
    使用np.maximum将输入限制至少为MIN_WEIGHT（0.001），确保比值有效且log有定义。
    示例:
    woe(0.7, 0.3) ≈ log(0.7/0.3)=log(2.333)=0.847
    实现说明:
    向量化log比值计算，带下界保护。
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
    功能描述:
    计算数据集中多个变量在分组条件下的IV汇总表，并生成详细分箱表。
    参数:
    df: pl.DataFrame, 输入数据。
    x_cols: list[str], 需要计算IV的变量列名列表。
    target_col: str, 目标列名（必须为0或1）。
    weight_col: str, optional, 权重列名；如果为None，则创建常数列1。
    seg_cols_ls: list[list[str]], optional, 分组列名列表的列表。每个内层列表定义一组分组列（交叉分组）。如果为None，则所有数据视为一组。
    num_bins: int, 正常值分箱的目标数，默认10。
    MV_dict: dict, optional, 缺失值映射，同bin_table。
    返回值:
    tuple[pl.DataFrame, pl.DataFrame]:
      - 第一元素（st_woe）: 详细分箱表，包含所有变量所有分组的分箱级统计（G_cnt, B_cnt, G_wgt, B_wgt, IV, WoE等）。
      - 第二元素（st_iv）: IV汇总表，每行对应一个分组（由seg_cols_ls定义）和一个变量，列IV为各分箱IV之和。
    关键规则:
    - 数据预处理：自动创建权重列（如果weight_col为None）和分组列（如果seg_cols_ls为None，创建单一分组列）。
    - 过滤：仅保留target_col为0或1的行。
    - 分组循环：对seg_cols_ls中的每个分组配置：
        - 如果分组列列表为空，则调用calc_woe函数（需在别处定义）计算无分组分箱。
        - 否则，使用bin_table（pattern_merge固定为True）计算分箱。
    - 收集所有分箱表后，按所有分组列和变量名汇总IV（求和）。
    - 调整列顺序：所有分组列在前，然后var_nm和bin_idx。
    - 如果使用了临时分组列（drop_group_col=True），则从输出表中删除这些列。
    示例:
    st_woe, st_iv = summary_iv(df, x_cols=['age','income'], target_col='target', weight_col='weight', seg_cols_ls=[['region','product']])
    实现说明:
    循环处理每个分组配置：对非空分组调用bin_table；对空分组调用calc_woe（未提供）。使用pl.concat合并所有分箱表。然后group_by所有分组列和var_nm对IV求和得到st_iv。使用adj_colorder调整列顺序。如果无实际分组列，删除临时列。
    注意：calc_woe函数在提供源码中未定义，可能依赖外部模块。
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
    功能描述:
    基于IV汇总表，生成IV区间分布统计表（计数和比例），按主题和机构分类展示。
    参数:
    iv_summary: pl.DataFrame, IV汇总表，必须包含列：IV以及指定的org_class_col, theme_col, var_name_col。
    org_class_col: str, 机构分类列名。
    var_name_col: str, 变量名列名（用于去重计数）。
    theme_col: str, 主题列名（分布分析的主题维度）。
    save_path: str, optional, 保存结果到Excel的路径；如果提供，则写入文件。
    返回值:
    tuple[pl.DataFrame, pl.DataFrame]:
      - 第一元素（cnt_output）: 计数表，行索引为[theme_col, IV_range]，列为机构分类，值为该主题下各IV区间的变量计数。
      - 第二元素（pct_output）: 比例表，类似结构，但值为比例（每个机构分类内各IV区间的变量占比）。
    关键规则:
    - IV区间：使用固定breaks=[0,0.05,0.1,0.15,0.2,0.25,0.3,0.35,0.4,0.5]进行cut分组。
    - 统计过程：先按(theme_col, org_class_col, var_name_col)计算平均IV（去重），然后按(theme_col, org_class_col, IV_range)计数。
    - 表格转换：通过pivot和unpivot操作，最终形成：行是机构分类与IV区间的组合，列是各theme_col（主题），值为计数或比例。
    示例:
    cnt, pct = summary_iv_distribution(st_iv, org_class_col='bank', var_name_col='var', theme_col='model')
    实现说明:
    两次类似处理：一次计数，一次计算比例。比例基于每个(theme_col, org_class_col)组内的总变量数。使用pivot将长表转为宽表，再调整格式。
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
    功能描述:
    从IV汇总表中，针对每个机构分类，筛选IV值最高的top X%变量，统计各主题下的分布。
    参数:
    res_iv: pl.DataFrame, IV汇总表，必须包含列：IV以及指定的org_class_col, theme_col, var_name_col。
    top_pcts: list[float], 百分比列表（如[0.1,0.2]），表示要筛选的前X%阈值。
    org_class_col: str, 机构分类列名。
    var_name_col: str, 变量名列名。
    theme_col: str, 主题列名（在结果中作为分组之一）。
    save_path: str, optional, 保存结果到Excel的路径。
    返回值:
    dict[str, pl.DataFrame]: 字典，键为'top10%'等（根据top_pcts生成），值为对应DataFrame，列包括：org_class_col, theme_col, cnt, pct, iv_threshold。每个DataFrame显示每个机构分类和主题下，筛选出的变量数、占比及IV门槛值。
    关键规则:
    - 对每个pct，计算每个机构分类内IV的分位数阈值（1-pct分位数）。
    - 筛选IV >= 阈值的变量（每个机构分类内独立筛选）。
    - 按(org_class_col, theme_col)分组，计算筛选出的变量数(cnt)，并取这些变量中最小IV作为iv_threshold（表示该组门槛）。
    - 计算比例：cnt除以该机构分类下筛选出的总变量数（即每个机构分类内，所有主题的cnt之和）。
    - 排序：最终结果按机构分类升序、cnt降序排列。
    示例:
    res = summary_iv_top_distribution(st_iv, [0.1,0.2], 'bank', 'var', 'model')
    实现说明:
    循环每个pct，使用quantile over分组计算阈值，过滤后分组统计。使用polars的over窗口计算比例。最后返回字典。
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
