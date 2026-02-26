import numpy as np
import polars as pl
import lightgbm as lgb
import os
from polars_common import adj_colorder, write_tables_to_excel
from tqdm import tqdm
from ks import summary_performance
from sklearn.metrics import roc_curve

def lgb_quick_eval(df_merge, var_cols, target_col, weight_col, group_col, Kfold_col, output_dir, grid_params=None, n_cores=20):
    """
    功能描述: 对输入Polars DataFrame按分组列进行分组，每组内使用LightGBM进行K折交叉验证网格搜索，训练模型并评估KS和AUC性能，输出模型、特征重要性及性能指标文件，并在原数据添加预测列。
    参数:
    - df_merge (pl.DataFrame): 包含特征、目标、权重、分组和K折列的输入数据框。
    - var_cols (list of str): 特征列名列表，用于模型训练。
    - target_col (str): 二分类目标列名。
    - weight_col (str): 样本权重列名，用于加权训练和评估。
    - group_col (str): 分组列名，函数将按此列的值分组，每组独立训练模型。
    - Kfold_col (str): K折交叉验证列名，值应为整数0到nfold-1，指定每行数据属于哪个折。
    - output_dir (str): 输出目录路径，将保存每组模型文件、特征重要性文件及汇总性能报告。
    - grid_params (dict, optional): 网格搜索参数字典，键为LightGBM参数名，值为参数值列表或单个值。默认为None，使用内置默认参数集。
    - n_cores (int, optional): LightGBM训练使用的CPU核心数。默认20。
    返回值:
    pl.DataFrame: 输入的df_merge添加了预测列，列名为'pred_{group_nm}'，其中group_nm为分组列的唯一值，表示该组的预测概率。
    关键规则:
    - 自动计算scale_pos_weight以平衡正负样本权重，基于权重列和目标列。
    - 网格搜索通过遍历grid_params所有组合进行，使用AUC-mean作为最佳参数选择标准。
    - 每组训练使用lgb.cv进行交叉验证，早停轮数为20。
    - 最佳模型为所有折中AUC最高的参数对应的模型集合，保存为'model_fold{i}.lgb'。
    - 特征重要性基于'gain'和'split'计算，并按gain降序排序。
    - 预测使用所有折模型的平均预测（1 - 平均预测），因为lightgbm预测为正类概率。
    - 输出文件：每组有模型和重要性CSV；汇总有网格搜索性能CSV和跨组性能Excel。
    示例:
    # 示例数据准备：df_merge应包含var_cols, target_col, weight_col, group_col, Kfold_col列
    df_result = lgb_quick_eval(
        df_merge=df,
        var_cols=['feat1', 'feat2'],
        target_col='label',
        weight_col='sample_weight',
        group_col='segment',
        Kfold_col='fold',
        output_dir='./output',
        grid_params={'max_depth': [3, 5], 'learning_rate': [0.1]},
        n_cores=4
    )
    # 返回df_merge将添加'pred_segment1', 'pred_segment2'等列
    实现说明(<=100字): 函数内部定义辅助函数，按组循环，每组内执行网格搜索交叉验证，基于AUC选择最佳LightGBM模型，计算特征重要性并输出文件。最终添加预测列并汇总性能。
    """
    nfold = df_merge[Kfold_col].max() + 1
    
    def eval_ks(preds, train_data):
        tmp = np.isnan(preds)
        if np.any(tmp):
            print(np.mean(tmp))
            preds[tmp] = 0
        fpr, tpr,_ = roc_curve(train_data.label, preds, sample_weight=train_data.weight)
        ks = np.max(np.abs(fpr-tpr))
        return ('KS', ks, True)

    def gen_grid_search_params(params):
        def tmp_modify_dict(old_dict, k, new_v):
            new_dict = old_dict.copy()
            new_dict[k] = new_v
            return new_dict

        all_params = [{k: None for k in params}]
        for k, v in grid_params.items():
            if not (isinstance(v, list) or isinstance(v, tuple)):
                v = [v]
            new_all_params = []
            for v0 in v:
                new_all_params += [tmp_modify_dict(_, k, v0) for _ in all_params]
            all_params = new_all_params
        return all_params
    
    def importance_table(bst):
        st = pl.DataFrame({'feature_name':bst.feature_name(), 
                           'gain': bst.feature_importance('gain'),
                           'split': bst.feature_importance('split')})
        st = st.with_columns(gain_rate = pl.col('gain') / pl.col('gain').sum(),
                             split_rate = pl.col('split') / pl.col('split').sum())
        st = st.sort('gain', descending=True)
        return st
    
    # default grid_params
    if grid_params is None:
        grid_params = {'objective': 'binary', 
                        'max_depth': [2, 3, 4],
                        'learning_rate': [0.01, 0.05, 0.1],
                        'min_child_weight': 0.00,
                        'min_child_samples': 50,
                        'subsample': 0.8,
                        'colsample_bytree': 0.8,
                        'reg_alpha': 0.0,
                        'reg_lambda': 0.0,
                        'verbosity': -1}
    all_params_ls = gen_grid_search_params(grid_params)
    
    os.makedirs(output_dir, exist_ok=True)
    
    
    def eval_df(df_model, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        folds = [((df_model[Kfold_col]!=i).arg_true().to_list(),
              (df_model[Kfold_col]==i).arg_true().to_list()) for i in range(nfold)]

        model_data = lgb.Dataset(df_model[var_cols].to_numpy(),
                             label=df_model[target_col].to_numpy(),
                             weight=df_model[weight_col].to_numpy(),
                             feature_name=var_cols)
        scale_pos_weight = df_model.select(tmp=pl.col(weight_col).filter(pl.col(target_col)==0).sum()/
                    pl.col(weight_col).filter(pl.col(target_col)==1).sum())[0, 'tmp']
        
        # cv train
        metrics_ls = []
        best_bst = None
        best_auc = -1
        for i, params in enumerate(all_params_ls):
            params['scale_pos_weight'] = scale_pos_weight# 好坏权重平衡
            params['n_jobs'] = n_cores
            res_this = lgb.cv(
                params,
                train_set=model_data,
                num_boost_round=1000,
                folds=folds,
                metrics=['auc'],
                feval = [eval_ks],
                #verbose_eval=False,
                callbacks=[lgb.early_stopping(stopping_rounds=20)],
                eval_train_metric=False,
                return_cvbooster=True
            )
            res_this = {k.replace('valid ',''): v for k,v in res_this.items()}
            metrics = {'param_index': i}
            metrics.update(params)
            metrics['best_iteration'] = np.argmax(res_this['auc-mean'])
            metrics['auc-mean'] = res_this['auc-mean'][metrics['best_iteration']]
            metrics['auc-stdv'] = res_this['auc-stdv'][metrics['best_iteration']]
            metrics['KS-mean'] = res_this['KS-mean'][metrics['best_iteration']]
            metrics['KS-stdv'] = res_this['KS-stdv'][metrics['best_iteration']]
            metrics_ls.append(metrics)

            if metrics['auc-mean'] > best_auc:
                best_bst = res_this['cvbooster'].boosters
                best_auc = metrics['auc-mean']
        st_metrics = pl.DataFrame(metrics_ls)
        st_metrics.write_csv(os.path.join(output_dir, 'grid_search_perf.csv'))
        st_metrics_best = st_metrics[st_metrics['auc-mean'].arg_max()]
        # save lgb model
        for i in range(nfold):
            best_bst[i].save_model(os.path.join(output_dir, f'model_fold{i}.lgb'))
        # save lgb importance
        st_imp = pl.concat([importance_table(bst).with_columns(pl.lit(i).alias('fold_idx')) for i, bst in enumerate(best_bst)])
        st_imp.write_csv(os.path.join(output_dir, 'best_bst_importance.csv'))
        
        return st_metrics_best, best_bst
    
    st_metrics_ls = []
    X = df_merge[var_cols].to_numpy()
    all_groups = []
    for (group_nm, ), df_part in tqdm(df_merge.group_by(group_col)):
        print(group_nm)
        this_output_dir = os.path.join(output_dir, str(group_nm))
        st_metrics, bsts = eval_df(df_part, this_output_dir)
        st_metrics = st_metrics.with_columns(pl.lit(group_nm, dtype=df_merge.schema[group_col]).alias(group_col))
        st_metrics_ls.append(st_metrics)
        # scoring
        pred_ls = np.array([bsts[i].predict(X) for i in range(nfold)])
        pred = 1 - np.mean(pred_ls, axis=0)
        df_merge = df_merge.with_columns(pl.Series(pred).alias(f'pred_{group_nm}'))
        all_groups.append(group_nm)
    st_metrics = pl.concat(st_metrics_ls)
    st_metrics = adj_colorder(st_metrics, group_col, insert_first=True)
    
    ## scoring
    score_cols = [f'pred_{x}' for x in sorted(all_groups)]
    res_ks = summary_performance(df_merge, score_cols, [target_col], weight_col, 
                              [[group_col]], dcast_params={'KS': 'score_nm', 'AUC': 'score_nm'})
    res_ks.pop('cnt')
    res_ks['KS_dcast'] = adj_colorder(res_ks['KS_dcast'], score_cols, insert_last=True)
    res_ks['AUC_dcast'] = adj_colorder(res_ks['AUC_dcast'], score_cols, insert_last=True)
    res_ks['self_perf'] = st_metrics
    write_tables_to_excel(res_ks, os.path.join(output_dir, 'cross_perf.xlsx'))
    return df_merge
        
        
        
        
