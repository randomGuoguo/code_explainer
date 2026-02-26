import polars as pl
import warnings
from numbers import Number


def balance_badrate(df,  
                    target_col,
                    *,
                    weight_col=None,
                    badrate_info=0.05,
                    group_cols=None,
                    default_badrate_info=0.05,
                    adjusted_weight_name='weight_adj'):
    """
    功能描述:
    根据目标坏账率调整样本权重，使数据集的坏账率符合指定值。
    参数:
    df: polars DataFrame，包含目标列和可选权重列。
    target_col: str，目标列名，应为二分类标签（0或1）。
    weight_col: str, optional, 权重列名，默认为None（权重为1）。
    badrate_info: float or pl.DataFrame, 目标坏账率或包含分组和坏账率的DataFrame，默认为0.05。
    group_cols: list, optional, 分组列名列表，用于分组计算，默认为None。
    default_badrate_info: float, 当badrate_info为DataFrame且缺失坏账率时的默认值，默认为0.05。
    adjusted_weight_name: str, 调整后的权重列名，默认为'weight_adj'。
    返回值:
    pl.DataFrame，包含调整后的权重列。
    关键规则:
    目标列必须是二分类（0或1）。
    如果badrate_info是DataFrame，必须包含'badrate'列，且group_cols指定分组列。
    调整因子计算：adj_factor = (1 - raw_badrate) / raw_badrate * (adj_badrate / (1 - adj_badrate))。
    应用调整因子：当目标=1时，新权重 = adj_factor * 原始权重；否则保留原始权重。
    示例:
    ```python
    import polars as pl
    df = pl.DataFrame({
        "target": [1, 0, 1, 0, 1],
        "weight": [1, 2, 1, 2, 1]
    })
    # 调整坏账率到0.2
    df_balanced = balance_badrate(df, target_col="target", badrate_info=0.2)
    ```
    实现说明:
    基于调整因子计算权重，使调整后的坏账率符合目标值。处理分组和缺失值。
    """
    if weight_col is None:
        weight = pl.lit(1)
    else:
        weight = pl.col(weight_col)
    target = pl.col(target_col)
    raw_badrate = weight.filter(target.eq(1)).sum() / weight.filter(target.is_in([0,1])).sum()
        
    if isinstance(badrate_info, pl.DataFrame):
        if 'badrate' not in badrate_info.columns:
            raise ValueError('Column `badrate` is not in badrate_info.')
        group_cols = [col for col in badrate_info.columns if col != 'badrate']
        diff_cols = [col for col in df.columns if col not in set(group_cols)]
        if len(diff_cols) > 0:
            raise ValueError(f'Column(s) {", ".join(diff_cols)} not in data.')
        
        original_len = badrate_info.shape[0]
        badrate_info = badrate_info.unique(group_cols, keep='first')
        if badrate_info.shape[0] != original_len:
            warnings.warn('Group columns has multiple values in `badrate_info`. Keep the first occurrence of each value.')
            
        df_badrate = df.group_by(group_cols)\
                       .agg(raw_badrate=raw_badrate)\
                       .join(badrate_info,
                            on=group_cols,
                            join_nulls=True,
                            how='left')\
                       .with_columns(pl.col('badrate').fill_null(default_badrate_info))\
                       .rename({'badrate': 'adj_badrate'})
    elif isinstance(badrate_info, Number):
        if group_cols is None:
            group_cols = []
            df_badrate = df.select(raw_badrate=raw_badrate,
                                   adj_badrate = pl.lit(badrate_info))
        else:
            df_badrate = df.group_by(group_cols)\
                           .agg(raw_badrate=raw_badrate,
                                adj_badrate = pl.lit(badrate_info))
    else:
        raise TypeError(f'Unsupported bad rate type: {type(badrate_info)}')
        
    # calculate adj_factor
    df_badrate = df_badrate.with_columns(adj_factor = (1-pl.col('raw_badrate')) / pl.col('raw_badrate') *
                                           (pl.col('adj_badrate') / (1 - pl.col('adj_badrate'))))
    if len(group_cols) == 0:
        df = df.join(df_badrate, how='cross')
    else:
        df = df.join(df_badrate, 
                     on=group_cols, 
                     join_nulls=True,
                     validate='m:1',
                     how='left')
        assert df['adj_factor'].null_count() == 0
    
    # calculate adj badrate
    if adjusted_weight_name in df.columns:
        warnings.warn(f'Overwrite existed {adjusted_weight_name}')
    df = df.with_columns(pl.when(target.eq(1))
                            .then(pl.col('adj_factor').mul(weight))
                            .otherwise(pl.col(weight_col))
                            .alias(adjusted_weight_name))\
            .drop(['raw_badrate', 'adj_badrate', 'adj_factor'])   
    return df


def balance_weight(df, 
                   *,
                   weight_col=None,
                   weight_info=10000,
                   group_cols=None,
                   adjusted_weight_name='weight_adj'):
    """
    功能描述:
    调整样本权重以实现总权重平衡，可以全局或按组调整。
    参数:
    df: polars DataFrame，包含权重列或默认权重1。
    weight_col: str, optional, 权重列名，默认为None（权重为1）。
    weight_info: int or pl.DataFrame, 目标总权重或包含分组和总权重的DataFrame，默认为10000。
    group_cols: list, optional, 分组列名列表，默认为None。
    adjusted_weight_name: str, 调整后的权重列名，默认为'weight_adj'。
    返回值:
    pl.DataFrame，包含调整后的权重列。
    关键规则:
    如果weight_info是DataFrame，必须包含'total_wgt'列，且group_cols指定分组列。
    调整权重：新权重 = 原始权重 * (目标总权重 / 当前总权重)。
    按组调整时，确保组内总权重等于目标值。
    示例:
    ```python
    import polars as pl
    df = pl.DataFrame({
        "group": ["A", "A", "B", "B"],
        "weight": [1, 1, 2, 2]
    })
    # 调整总权重到10000
    df_balanced = balance_weight(df, weight_info=10000)
    ```
    实现说明:
    通过归一化权重到目标总值，实现样本平衡。处理分组和缺失值。
    """
    if weight_col is None:
        weight = pl.lit(1)
    else:
        weight = pl.col(weight_col)
    
    if adjusted_weight_name in df.columns:
        warnings.warn(f'Overwrite existed {adjusted_weight_name}')
        
    if isinstance(weight_info, pl.DataFrame):
        if 'total_wgt' not in weight_info.columns:
            raise ValueError('Column `total_wgt` is not in weight_info.')
        if group_cols is not None:
            warnings.warn(f'Overwrite `group_cols` by columns in `weight_info`.')
            
        group_cols = [col for col in weight_info.columns if col != 'total_wgt']
        diff_cols = [col for col in df.columns if col not in set(group_cols)]
        if len(diff_cols) > 0:
            raise ValueError(f'Column(s) {", ".join(diff_cols)} not in data.')
        
        original_len = weight_info.shape[0]
        weight_info = weight_info.unique(group_cols, keep='first')
        if weight_info.shape[0] != original_len:
            warnings.warn('Group columns has multiple values in `weight_info`. Keep the first occurrence of each value.')
            
        df = df.join(df_weight_info, 
                     on=group_cols, 
                     join_nulls=True,
                     validate='m:1',
                     how='left')\
               .with_columns(weight.mul(pl.col('total_wgt').truediv(weight.sum().over(group_cols)))
                                   .alias(adjusted_weight_name))
        
        num_null_weights = df[adjusted_weight_name].null_count()
        if num_null_weights > 0:
            warnings.warn(f'{num_null_weights} adjusted sample weights is null. Two possible reasons are:\n'
                           '1. Some groups are not included in weight balancing.\n'
                           '2. Some original sample weights are null.')
    elif isinstance(weight_info, Number):
        if group_cols is None:
            df = df.with_columns(weight.mul(pl.lit(weight_info).truediv(weight.sum()))
                                   .alias(adjusted_weight_name))
        else:
            df = df.with_columns(weight.mul(pl.lit(weight_info).truediv(weight.sum().over(group_cols)))
                                       .alias(adjusted_weight_name))
    else:
        raise TypeError(f'Unsupported weight_info type: {type(weight_info)}')
        
    return df