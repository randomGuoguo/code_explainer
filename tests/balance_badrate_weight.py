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
    功能描述: 调整DataFrame中样本权重，使调整后bad rate（目标列=1的比例）匹配指定值。支持全局或分组调整，可自定义初始权重。
    参数: df: Polars DataFrame; target_col: 目标列名（需为0/1二分类）; weight_col: 可选初始权重列，默认无（权重为1）; badrate_info: 调整目标bad rate，可为浮点数或含'badrate'列的DataFrame（其非'badrate'列作为分组列，group_cols参数忽略）; group_cols: 分组列列表（仅当badrate_info为数字时有效）; default_badrate_info: 分组badrate缺失时的默认值; adjusted_weight_name: 输出调整权重列名，默认'weight_adj'。
    返回值: 添加调整后权重列的DataFrame。
    关键规则: 仅计算target为0/1的行；badrate_info为DataFrame时需含'badrate'列且分组列与df一致；分组重复时保留首行并警告；调整因子 = (1-raw_badrate)/raw_badrate * (adj_badrate/(1-adj_badrate))；仅target=1时应用调整。
    示例: 全局：balance_badrate(df, 'y', badrate_info=0.1)；分组：badrate_df = pl.DataFrame({'g':['A','B'], 'badrate':[0.2,0.1]}); balance_badrate(df, 'y', badrate_info=badrate_df)（若badrate_df含分组列则无需group_cols）。
    实现说明: 计算原始bad rate，据badrate_info得调整值，推导调整因子，按target=1应用权重乘法。
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
    功能描述: 调整DataFrame中样本权重，使调整后总权重匹配指定值。支持全局或分组调整，可自定义初始权重。
    参数: df: Polars DataFrame; weight_col: 可选初始权重列，默认无（权重为1）; weight_info: 目标总权重，可为浮点数或含'total_wgt'列的DataFrame（其非'total_wgt'列作为分组列，group_cols参数忽略）; group_cols: 分组列列表（仅当weight_info为数字时有效）; adjusted_weight_name: 输出调整权重列名，默认'weight_adj'。
    返回值: 添加调整后权重列的DataFrame。
    关键规则: weight_info为DataFrame时需含'total_wgt'列且分组列与df一致；调整权重 = 原权重 * (目标总权重 / 组内原始总权重)；分组缺失组可能导致null值并警告；adjusted_weight_name已存在时覆盖并警告。
    示例: 全局：balance_weight(df, weight_info=10000)；分组：weight_df = pl.DataFrame({'g':['A','B'], 'total_wgt':[5000,5000]}); balance_weight(df, weight_info=weight_df)（若weight_df含分组列则无需group_cols）。
    实现说明: 从weight_info获取目标权重，计算组内原始总权重，求调整比例，应用乘法调整。
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